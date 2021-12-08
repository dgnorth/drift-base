import copy
import logging
import boto3
import json
import re
from collections import defaultdict
from botocore.exceptions import ClientError, ParamValidationError
from flask import g, url_for
from aws_assume_role_lib import assume_role
from driftbase.parties import get_player_party, get_party_members
from driftbase.messages import post_message

from driftbase.resources.flexmatch import TIER_DEFAULTS

NUM_VALUES_FOR_LATENCY_AVERAGE = 3
REDIS_TTL = 1800

# FIXME: Figure out how to do multi-region matchmaking; afaik, the configuration isn't region based, but both queues and
#  events are. The queues themselves can have destination fleets in multiple regions.
AWS_REGION = "eu-west-1"

log = logging.getLogger(__name__)

# Latency reporting

def update_player_latency(player_id, region, latency_ms):
    region_key = _make_player_latency_key(player_id) + region
    with g.redis.conn.pipeline() as pipe:
        pipe.lpush(region_key, latency_ms)
        pipe.ltrim(region_key, 0, NUM_VALUES_FOR_LATENCY_AVERAGE-1)
        pipe.sadd(_make_player_regions_key(player_id), region)
        pipe.execute()

def get_player_latency_averages(player_id):
    player_latency_key = _make_player_latency_key(player_id)
    regions = _get_player_regions(player_id)
    with g.redis.conn.pipeline() as pipe:
        for region in regions:
            pipe.lrange(player_latency_key + region, 0, NUM_VALUES_FOR_LATENCY_AVERAGE)
        results = pipe.execute()
    return {
        region: int(sum(float(latency) for latency in latencies) / min(NUM_VALUES_FOR_LATENCY_AVERAGE, len(latencies)))
        for region, latencies in zip(regions, results)
    }


#  Matchmaking

def upsert_flexmatch_ticket(player_id, matchmaking_configuration, extra_matchmaking_data):
    with _LockedTicket(_get_player_ticket_key(player_id)) as ticket_lock:
        # Generate a list of players relevant to the request; this is the list of online players in the party if the player belongs to one, otherwise the list is just the player
        member_ids = _get_player_party_members(player_id)

        if ticket_lock.ticket:  # Existing ticket found
            ticket_status = ticket_lock.ticket["Status"]
            if ticket_status in ("QUEUED", "SEARCHING", "REQUIRES_ACCEPTANCE", "PLACING", "COMPLETED"):
                # TODO: Check if I need to add player_id to the ticket. This is the use case where someone accepts a party
                #  invite after matchmaking started.
                log.info(f"Returning existing ticket {ticket_lock.ticket['TicketId']} to player {player_id}")
                return ticket_lock.ticket  # Ticket is still valid
            # otherwise, we issue a new ticket

        gamelift_client = GameLiftRegionClient(AWS_REGION, _get_tenant_name())
        try:
            log.info(f"Issuing a new {matchmaking_configuration} matchmaking ticket for playerIds {member_ids} on behalf of calling player {player_id}")
            response = gamelift_client.start_matchmaking(
                ConfigurationName=matchmaking_configuration,
                Players=[
                    {
                        "PlayerId": str(member_id),
                        "PlayerAttributes": _get_player_attributes(member_id, extra_matchmaking_data),
                        "LatencyInMs": get_player_latency_averages(member_id)
                    }
                    for member_id in member_ids
                ],
            )
        except ParamValidationError as e:
            raise GameliftClientException("Invalid parameters to request", str(e))
        except ClientError as e:
            raise GameliftClientException("Failed to start matchmaking", str(e))

        ticket_lock.ticket = response["MatchmakingTicket"]
        log.info(f"New ticket {ticket_lock.ticket['TicketId']} issued by player {player_id}")
        _post_matchmaking_event_to_members(member_ids, "MatchmakingStarted", {"ticket_url": url_for("flexmatch.ticket", ticket_id=ticket_lock.ticket["TicketId"], _external=True)})
        return ticket_lock.ticket

def _cancel_locked_ticket(ticket_lock, player_id):
    ticket = ticket_lock.ticket
    if ticket["Status"] in ("COMPLETED", "PLACING", "REQUIRES_ACCEPTANCE"):
        log.info(f"Not cancelling ticket for player {player_id} as he has crossed the Rubicon on ticket {ticket['TicketId']}")
        return ticket["Status"]  # Don't allow cancelling if we've already put you in a match, or we're in the process of doing so
    log.info(f"Cancelling ticket {ticket['TicketId']} for player {player_id}, currently in state {ticket['Status']}")
    gamelift_client = GameLiftRegionClient(AWS_REGION, _get_tenant_name())
    try:
        response = gamelift_client.stop_matchmaking(TicketId=ticket["TicketId"])
    except ClientError as e:
        log.warning(f"ClientError from gamelift. Response: {e.response}")
        if e.response["Error"]["Code"] != "InvalidRequestException":
            raise GameliftClientException("Failed to cancel matchmaking ticket", str(e))
    log.info(f"Clearing player {player_id}'s ticket from cache: {ticket_lock.ticket}")
    ticket_lock.ticket = None
    _post_matchmaking_event_to_members(_get_player_party_members(player_id), "MatchmakingStopped")
    return ticket

def cancel_player_ticket(player_id, ticket_id):
    with _LockedTicket(_get_player_ticket_key(player_id)) as ticket_lock:
        if ticket_lock.ticket and ticket_id == ticket_lock.ticket["TicketId"]:
            return _cancel_locked_ticket(ticket_lock, player_id)
    if get_player_party(player_id): # TODO: Remove this block once client has been updated to not try to cancel the non-party ticket.
        with _LockedTicket(_make_player_ticket_key(player_id)) as ticket_lock:
            if ticket_lock.ticket:
                return _cancel_locked_ticket(ticket_lock, player_id)
    return None


def get_player_ticket(player_id):
    with _LockedTicket(_get_player_ticket_key(player_id)) as ticket_lock:
        log.info(f"get_player_ticket returning ticket for player {player_id}: {ticket_lock.ticket}")
        return ticket_lock.ticket

def update_player_acceptance(ticket_id, player_id, match_id, acceptance):
    with _LockedTicket(_get_player_ticket_key(player_id)) as ticket_lock:
        player_ticket = ticket_lock.ticket
        if player_ticket is None:
            log.warning(f"Request to update acceptance for player {player_id} who has no ticket. Ignoring")
            return
        if player_ticket["TicketId"] != ticket_id:
            log.warning(f"Cannot update acceptance on ticket {ticket_id} as it is not player {player_id}'s active ticket")
            return
        log.info(f"Updating acceptance state of ticket {ticket_id} for player {player_id}")
        if player_ticket["Status"] != "REQUIRES_ACCEPTANCE":
            log.error(f"Ticket {ticket_id} doesn't require acceptance! Ignoring.")
            return
        if player_ticket["MatchId"] != match_id:
            log.error(f"The matchId in ticket {ticket_id} doesn't match {match_id}! Ignoring.")
            return

        acceptance_type = 'ACCEPT' if acceptance else 'REJECT'
        log.info(f"Updating acceptance on ticket {player_ticket['TicketId']} for player {player_id} to {acceptance_type}")
        gamelift_client = GameLiftRegionClient(AWS_REGION, _get_tenant_name())
        try:
            gamelift_client.accept_match(TicketId=ticket_id, PlayerIds=[str(player_id)], AcceptanceType=acceptance_type)
        except ClientError as e:
            raise GameliftClientException(f"Failed to update acceptance for player {player_id}, ticket {ticket_id}", str(e))


def get_valid_regions():
    return _get_tenant_config_value("valid_regions")

def handle_party_event(queue_name, event_data):
    log.debug("handle_party_event", event_data)
    if queue_name == "parties" and event_data["event"] == "player_joined":
        player_id = event_data["player_id"]
        party_id = event_data["party_id"]
        with _LockedTicket(_make_player_ticket_key(player_id)) as ticket_lock:
            if ticket_lock.ticket:
                log.info(f"handle_party_event:player_joined: Cancelling ticket {ticket_lock.ticket['TicketId']} for player {player_id} since he has now joined party {party_id}")
                _cancel_locked_ticket(ticket_lock, player_id)

def process_flexmatch_event(flexmatch_event):
    event = _get_event_details(flexmatch_event)
    event_type = event.get("type", None)
    if event_type is None:
        raise RuntimeError("No event type found")
    if len(event.get("tickets", 0)) == 0:
        raise RuntimeError("No tickets!")

    log.info(f"Incoming '{event_type}' flexmatch event: {event}")
    if event_type == "MatchmakingSearching":
        return _process_searching_event(event)
    if event_type == "PotentialMatchCreated":
        return _process_potential_match_event(event)
    if event_type == "MatchmakingSucceeded":
        return _process_matchmaking_succeeded_event(event)
    if event_type == "MatchmakingCancelled":
        return _process_matchmaking_cancelled_event(event)
    if event_type == "AcceptMatch":
        return _process_accept_match_event(event)
    if event_type == "AcceptMatchCompleted":
        return _process_accept_match_completed_event(event)
    if event_type == "MatchmakingTimedOut":
        return _process_matchmaking_timeout_event(event)
    if event_type == "MatchmakingFailed":
        return _process_matchmaking_failed_event(event)

    raise RuntimeError(f"Unknown event '{event_type}'")

def start_game_session_placement(**kwargs):
    gamelift_client = GameLiftRegionClient(AWS_REGION, _get_tenant_name())
    try:
        return gamelift_client.start_game_session_placement(**kwargs)
    except ParamValidationError as e:
        raise GameliftClientException("Invalid parameters to request", str(e))
    except ClientError as e:
        raise GameliftClientException("Failed to start game session placement", str(e))

def stop_game_session_placement(placement_id: str):
    gamelift_client = GameLiftRegionClient(AWS_REGION, _get_tenant_name())
    try:
        return gamelift_client.stop_game_session_placement(PlacementId=placement_id)
    except ParamValidationError as e:
        raise GameliftClientException("Invalid parameters to request", str(e))
    except ClientError as e:
        raise GameliftClientException("Failed to stop game session placement", str(e))

def describe_game_sessions(**kwargs):
    gamelift_client = GameLiftRegionClient(AWS_REGION, _get_tenant_name())
    try:
        return gamelift_client.describe_game_sessions(**kwargs)
    except ParamValidationError as e:
        raise GameliftClientException("Invalid parameters to request", str(e))
    except ClientError as e:
        raise GameliftClientException("Failed to describe game sessions", str(e))

def describe_player_sessions(**kwargs):
    gamelift_client = GameLiftRegionClient(AWS_REGION, _get_tenant_name())
    try:
        return gamelift_client.describe_player_sessions(**kwargs)
    except ParamValidationError as e:
        raise GameliftClientException("Invalid parameters to request", str(e))
    except ClientError as e:
        raise GameliftClientException("Failed to describe player sessions", str(e))

def create_player_session(**kwargs):
    gamelift_client = GameLiftRegionClient(AWS_REGION, _get_tenant_name())
    try:
        return gamelift_client.create_player_session(**kwargs)
    except ParamValidationError as e:
        raise GameliftClientException("Invalid parameters to request", str(e))
    except ClientError as e:
        raise GameliftClientException("Failed to create player session", str(e))

# Helpers

def _get_player_regions(player_id):
    """ Return a list of regions for whom 'player_id' has reported latency values. """
    regions_key = _make_player_regions_key(player_id)
    if g.redis.conn.exists(regions_key):
        return g.redis.conn.smembers(_make_player_regions_key(player_id))
    return set()

def _make_player_latency_key(player_id):
    return g.redis.make_key(f"player:{player_id}:latencies:")

def _make_player_regions_key(player_id):
    return g.redis.make_key(f"player:{player_id}:regions:")

def _make_player_ticket_key(player_id):
    return g.redis.make_key(f"player:{player_id}:flexmatch:")

def _make_party_ticket_key(party_id):
    return g.redis.make_key(f"party:{party_id}:flexmatch:")

def _get_player_ticket_key(player_id):
    player_party_id = get_player_party(player_id)
    if player_party_id is not None:
        return _make_party_ticket_key(player_party_id)
    return _make_player_ticket_key(player_id)

def _get_player_party_members(player_id):
    """ Return the full list of players who share a party with 'player_id', including 'player_id'. If 'player_id' isn't
    a party member, the returned list will contain only 'player_id'"""
    party_id = get_player_party(player_id)
    if party_id:
        return get_party_members(party_id)
    return [player_id]

def _get_player_attributes(player_id, extra_player_data):
    ret = extra_player_data.get(player_id, {})
    if "Skill" not in ret:
        # Always include the skill for consistency across game modes and rulesets.  Shouldn't be needed though...
        ret["Skill"] = {"N": 100.0}
    return ret

def _get_tenant_config_value(config_key):
    default_value = TIER_DEFAULTS.get(config_key, None)
    tenant = g.conf.tenant
    if tenant:
        return g.conf.tenant.get("flexmatch", {}).get(config_key, default_value)
    return default_value

def _get_tenant_name():
    return g.conf.tenant.get('tenant_name')

def _post_matchmaking_event_to_members(receiving_player_ids, event, event_data=None, expiry=30):
    """ Insert a event into the 'matchmaking' queue of the 'players' exchange. """
    log.info(f"Posting '{event}' to players {receiving_player_ids} with event_data {event_data}")
    if not receiving_player_ids:
        log.warning(f"Empty receiver in matchmaking event {event} message")
        return
    if not isinstance(receiving_player_ids, (set, list)):
        receiving_player_ids = [receiving_player_ids]
    payload = {
        "event": event,
        "data": event_data or {}
    }
    for receiver_id in receiving_player_ids:
        post_message("players", int(receiver_id), "matchmaking", payload, expiry, sender_system=True)


def _get_event_details(event):
    if event.get("detail-type", None) != "GameLift Matchmaking Event":
        raise RuntimeError("Event is not a GameLift Matchmaking Event!")
    details = event.get("detail", None)
    if details is None:
        raise RuntimeError("Event is missing details!")
    return details

def _is_backfill_ticket(ticket_id):
    res = re.match(_get_tenant_config_value("backfill_ticket_pattern"), ticket_id)
    return res is not None

def _process_searching_event(event):
    updated_tickets = set()
    for ticket_id, player in _ticket_players(event):
        player_id = int(player["playerId"])
        if _is_backfill_ticket(ticket_id):
            log.info(f"Ignoring backfill ticket {ticket_id} containing player {player_id}")
            continue
        ticket_key = _get_player_ticket_key(player_id)
        with _LockedTicket(ticket_key) as ticket_lock:
            player_ticket = ticket_lock.ticket
            if player_ticket is None:  # Might be an event for an already deleted ticket.
                log.warning(f"Ignoring 'SEARCHING' event on ticket {ticket_id} containing player {player_id} as this player has no ticket in our store.")
                continue
            if ticket_id != player_ticket["TicketId"]:
                log.warning(f"'SEARCHING' event has player {player_id} on ticket {ticket_id}, which doesn't match his current ticket {player_ticket['TicketId']}. Ignoring this player/ticket combo update")
                continue
            if ticket_key in updated_tickets:
                log.info(f"Skipping update on ticket for player {player_id} as it resolves to previously updated ticket key {ticket_key}")
                continue
            if player_ticket.get("GameSessionConnectionInfo", None) is not None:
                # If we've recorded a session, then the player is in a match already and this is either a backfill ticket or a very much out-of-order ticket
                log.info(f"Existing session for player {player_id} found. Not updating {player_ticket['TicketId']}")
                continue
            if player_ticket["Status"] == "SEARCHING":
                continue  # Save on redis calls
            if player_ticket["Status"] not in ("QUEUED", "REQUIRES_ACCEPTANCE"):
                log.info(f"MatchmakingSearching event for ticket {player_ticket['TicketId']} in state {player_ticket['Status']} doesn't make sense.  Probably out of order delivery; ignoring.")
                continue
            log.info(f"Updating ticket {player_ticket['TicketId']} from {player_ticket['Status']} to SEARCHING")
            player_ticket["Status"] = "SEARCHING"
            updated_tickets.add(ticket_key)
            _post_matchmaking_event_to_members([player_id], "MatchmakingSearching")

def _process_potential_match_event(event):
    playerids_by_teamid = defaultdict(set)
    playerids_by_ticketid = defaultdict(set)  # For sanity checking
    for event_ticket_id, player in _ticket_players(event):
        player_id = int(player["playerId"])
        playerids_by_ticketid[event_ticket_id].add(player_id)
        playerids_by_teamid[player["team"]].add(player_id)
    team_data = {team: list(players) for team, players in playerids_by_teamid.items()}

    match_id = event["matchId"]
    acceptance_required = event["acceptanceRequired"]
    acceptance_timeout = event.get("acceptanceTimeout", None)
    new_state = "REQUIRES_ACCEPTANCE" if acceptance_required else "PLACING"
    game_session_info = event["gameSessionInfo"]
    for player in game_session_info["players"]:
        player_id = int(player["playerId"])
        ticket_key = _get_player_ticket_key(player_id)
        with _LockedTicket(ticket_key) as ticket_lock:
            player_ticket = ticket_lock.ticket
            if player_ticket is None:  # This has to be a back fill ticket, i.e. not issued by us.
                log.error(f"PotentialMatchCreated event received for a player who has no ticket.")
                continue
            if player_ticket.get("GameSessionConnectionInfo", None) is not None:
                # If we've recorded a session, then the player has been placed in a match already
                log.info(f"Player {player_id} has a session already. Not updating {player_ticket['TicketId']}")
                continue
            if player_ticket["Status"] not in ("QUEUED", "SEARCHING", "REQUIRES_ACCEPTANCE", "PLACING"):
                log.info(f"PotentialMatchCreated event for ticket {player_ticket['TicketId']} in state {player_ticket['Status']} doesn't make sense.  Probably out of order delivery; ignoring.")
                continue
            # sanity check
            if player_id not in playerids_by_ticketid.get(player_ticket["TicketId"], []):
                for ticketid, playerids in playerids_by_ticketid.items():
                    if player_id in playerids:
                        log.warning(f"Weird, player {player_id} is registered to ticket {player_ticket['TicketId']} but this update pegs him on ticket {ticketid}")
                        break

            if player_ticket["Status"] != new_state:
                log.info(f"Updating ticket {player_ticket['TicketId']} for player key {ticket_key} from {player_ticket['Status']} to {new_state}")
                player_ticket["Status"] = new_state
                player_ticket["MatchId"] = match_id
            else:
                log.info(f"Party ticket {player_ticket['TicketId']} for player key {ticket_key} already updated.")

            message_data = {
                "teams": team_data,
                "acceptance_required": acceptance_required,
                "match_id":  match_id,
                "acceptance_timeout": acceptance_timeout
            }
            _post_matchmaking_event_to_members(player_id, "PotentialMatchCreated", event_data=message_data)

def _process_matchmaking_succeeded_event(event):
    game_session_info = event["gameSessionInfo"]
    ip_address = game_session_info["ipAddress"]
    port = int(game_session_info["port"])
    connection_string = f"{ip_address}:{port}"
    connection_info_by_player_id = {}
    players_by_ticket = defaultdict(set)  # For sanity checking
    for ticket_id, player in _ticket_players(event):
        player_id = int(player["playerId"])
        players_by_ticket[ticket_id].add(player_id)
        if "playerSessionId" not in player:
            log.warning(f"player {player_id} has no playerSessionId in a MatchmakingSucceeded event. Dumping event for analysis:")
            log.warning(event)
            continue
        connection_info_by_player_id[player_id] = f"PlayerSessionId={player['playerSessionId']}?PlayerId={player_id}"

    for player in game_session_info["players"]:
        player_id = int(player["playerId"])
        ticket_key = _get_player_ticket_key(player_id)
        with _LockedTicket(ticket_key) as ticket_lock:
            player_ticket = ticket_lock.ticket
            if player_ticket is None:  # This has to be a backfill ticket, i.e. not issued by us.
                log.info(f"MatchmakingSucceeded event received for a player who has no ticket. Probably backfill.")
                continue
            if player_ticket.get("GameSessionConnectionInfo", None) is not None:
                # If we've recorded a session, then the player has been placed in a match already, or there are multiple players in the ticket.
                # either way, we don't want/need to update it.
                log.info(f"Player {player_id} has a session on his ticket already. Not updating {player_ticket['TicketId']}")
                continue
            # sanity check
            if player_id not in players_by_ticket.get(player_ticket["TicketId"], []):
                for ticket, players in players_by_ticket.items():
                    if player_id in players:
                        log.warning(f"Weird, player {player_id} is registered to ticket {player_ticket['TicketId']} but this update pegs him on ticket {ticket}")
                        break
            log.info(f"Updating ticket {player_ticket['TicketId']} for player key {ticket_key} from {player_ticket['Status']} to 'COMPLETED'")
            player_ticket["Status"] = "COMPLETED"
            player_ticket["MatchId"] = event["matchId"]
            player_ticket["GameSessionConnectionInfo"] = copy.copy(game_session_info)
            player_ticket["GameSessionConnectionInfo"].update({
                "ConnectionString": connection_string,
                "ConnectionOptions": connection_info_by_player_id[player_id]
            })
            for ticket_player in player_ticket["Players"]:
                receiver_id = int(ticket_player["PlayerId"])
                event_data = {
                    "connection_string": connection_string,
                    "options": connection_info_by_player_id[receiver_id]
                }
                _post_matchmaking_event_to_members([receiver_id], "MatchmakingSuccess", event_data=event_data)

def _process_matchmaking_cancelled_event(event):
    for ticket_id, player in _ticket_players(event):
        player_id = player["playerId"]
        ticket_key = _get_player_ticket_key(player_id)
        with _LockedTicket(ticket_key) as ticket_lock:
            player_ticket = ticket_lock.ticket
            if player_ticket is None:
                continue  # Normal, player cancelled the ticket and we've already cleared it from the cache
            if ticket_id != player_ticket["TicketId"]:
                # This block is a hack (heuristics); we should mark MATCH_COMPLETE via an explicit event.
                # MATCH_COMPLETE is not a flexmatch status, but I want to differentiate between statuses arising from the
                # cancelling of backfill tickets and other states
                if _is_backfill_ticket(ticket_id):
                    log.info(f"Backfill ticket {ticket_id} being cancelled.")
                    if player_ticket["Status"] == "COMPLETED":
                        log.info(f"Found active player {player_id} in backfill ticket. Setting his actual tickets {player_ticket['TicketId']} to state 'MATCH_COMPLETE'")
                        player_ticket["Status"] = "MATCH_COMPLETE"
                else:
                    log.info(f"'CANCELLED' event has player {player_id} on ticket {ticket_id} when his active ticket " +
                             f"{player_ticket['TicketId']} is in state {player_ticket['Status']}." +
                             f"Ignoring this player/ticket combo update.")
                continue
            player_ticket["Status"] = "CANCELLED"
            _post_matchmaking_event_to_members([player_id], "MatchmakingCancelled")

def _process_accept_match_event(event):
    game_session_info = event["gameSessionInfo"]
    acceptance_by_player_id = {}
    for player in game_session_info["players"]:
        player_id = player["playerId"]
        acceptance = player.get("accepted", None)
        acceptance_by_player_id[player_id] = acceptance
        if acceptance is not None:
            with _LockedTicket(_get_player_ticket_key(int(player_id))) as ticket_lock:
                player_ticket = ticket_lock.ticket
                if player_ticket is None:
                    log.error(f"Received acceptance event for player {player_id} who has no ticket.")
                    return
                if player_ticket["Status"] != "REQUIRES_ACCEPTANCE":
                    log.error(f"Received acceptance event for player {player_id} who has a ticket in invalid state {player_ticket['Status']}.")
                    return
                for ticket_player in player_ticket["Players"]:
                    if ticket_player['PlayerId'] == player_id:
                        ticket_player["Accepted"] = acceptance
                        break
    if acceptance_by_player_id:
        _post_matchmaking_event_to_members(list(acceptance_by_player_id), "AcceptMatch", acceptance_by_player_id)

def _process_accept_match_completed_event(event):
    # This may be totally pointless as there should be a followup event, and in case of rejection, multiple events.
    # In case the potential match was rejected, those who did accept should get a new searching event for their tickets,
    # but those who rejected will get a failed event on theirs.
    # If the match did get accepted, the success event will update all tickets in a single event
    acceptance_result = event.get("acceptance", "").upper()
    game_session_info = event["gameSessionInfo"]
    for player in game_session_info["players"]:
        player_id = player["playerId"]
        with _LockedTicket(_get_player_ticket_key(int(player_id))) as ticket_lock:
            player_ticket = ticket_lock.ticket
            if player_ticket is None:
                log.error(f"Received acceptance event for player {player_id} who has no ticket.")
                return
            if player_ticket["Status"] != "REQUIRES_ACCEPTANCE":
                log.error(f"Received acceptance event for player {player_id} who has a ticket in invalid state {player_ticket['Status']}.")
                return
            player_ticket["MatchStatus"] = acceptance_result

def _process_matchmaking_timeout_event(event):
    players_to_notify = set()
    for ticket_id, player in _ticket_players(event):
        player_id = int(player["playerId"])
        if _is_backfill_ticket(ticket_id):
            log.info(f"Ignoring TimeOut on backfill ticket {ticket_id}")
            continue
        ticket_key = _get_player_ticket_key(player_id)
        with _LockedTicket(ticket_key) as ticket_lock:
            player_ticket = ticket_lock.ticket
            if player_ticket is None:
                log.warning(f"Timeout event for ticket {ticket_id} includes player {player_id} who has no ticket.")
                continue
            if ticket_id != player_ticket["TicketId"]:
                log.warning(f"Timeout event for ticket {ticket_id} includes player {player_id} who has ticket {player_ticket['TicketId']}.")
                continue
            if player_ticket.get("GameSessionConnectionInfo", None) is not None:
                # If we've recorded a session, then the player has been placed in a match already
                log.info(f"Player {player_id} has a session attached to his ticket.  Timeout is nonsensical here. Ignoring.")
                continue
            player_ticket["Status"] = "TIMED_OUT"
            players_to_notify.add(player_id)
    if players_to_notify:
        _post_matchmaking_event_to_members(players_to_notify, "MatchmakingFailed", event_data={"reason": "TimeOut"})

def _process_matchmaking_failed_event(event):
    # FIXME: This is pretty much the same as a timeout; refactor
    players_to_notify = set()
    for ticket_id, player in _ticket_players(event):
        player_id = int(player["playerId"])
        if _is_backfill_ticket(ticket_id):
            log.info(f"Ignoring 'FAILED' event for backfill ticket {ticket_id}.")
            continue
        ticket_key = _get_player_ticket_key(player_id)
        with _LockedTicket(ticket_key) as ticket_lock:
            player_ticket = ticket_lock.ticket
            if player_ticket is None:
                log.warning(f"Failed event for ticket {ticket_id} includes player {player_id} who has no ticket.")
                continue
            if ticket_id != player_ticket["TicketId"]:
                log.warning(f"Failed event for ticket {ticket_id} includes player {player_id} who has ticket {player_ticket['TicketId']}.")
                continue
            if player_ticket.get("GameSessionConnectionInfo", None) is not None:
                # If we've recorded a session, then the player has been placed in a match already
                log.info(f"Player {player_id} has a session attached to his ticket.  Failure is nonsensical here. Ignoring.")
                continue
            player_ticket["Status"] = "FAILED"
            players_to_notify.add(player_id)
    if players_to_notify:
        _post_matchmaking_event_to_members(players_to_notify, "MatchmakingFailed", event_data={"reason": event["reason"]})

def _ticket_players(event):
    """ Generator function for players in tickets """
    for ticket in event["tickets"]:
        for player in ticket["players"]:
            yield ticket["ticketId"], player

class GameLiftRegionClient(object):
    __gamelift_clients_by_region = {}
    __gamelift_sessions_by_region = {}

    def __init__(self, region, tenant):
        self.region = region
        self.tenant = tenant
        client = self.__class__.__gamelift_clients_by_region.get((region, tenant))
        if client is None:
            session = self.__class__.__gamelift_sessions_by_region.get((region, tenant))
            if session is None:
                session = boto3.Session(region_name=self.region)
                role_to_assume = _get_tenant_config_value("aws_gamelift_role")
                if role_to_assume:
                    session = assume_role(session, role_to_assume)
                self.__class__.__gamelift_sessions_by_region[(region, tenant)] = session
            client = session.client("gamelift")
            self.__class__.__gamelift_clients_by_region[(region, tenant)] = client

    def __getattr__(self, item):
        return getattr(self.__class__.__gamelift_clients_by_region[(self.region, self.tenant)], item)


class _LockedTicket(object):
    """
    Context manager for synchronizing creation and modification of matchmaking tickets.
    """
    MAX_LOCK_WAIT_TIME_SECONDS = 30
    TICKET_TTL_SECONDS = 10 * 60
    MAX_REJOIN_TIME = None

    def __init__(self, key):
        self._key = key
        self._redis = g.redis
        self._ticket = None
        self._ticket_id = None
        self._entry_ticket_str = None
        self._lock = g.redis.conn.lock(self._key + "LOCK", timeout=self.MAX_LOCK_WAIT_TIME_SECONDS)
        if self.MAX_REJOIN_TIME is None:  # deferred initialization of class variable as we're not in app context at import time.
            self.__class__.MAX_REJOIN_TIME = _get_tenant_config_value("max_rejoin_time_seconds")

    @property
    def ticket(self):
        return self._ticket

    @ticket.setter
    def ticket(self, new_ticket):
        self._ticket = new_ticket

    def __enter__(self):
        self._lock.acquire(blocking=True)
        ticket_key = self._redis.conn.get(self._key)
        if ticket_key:
            self._ticket_id = ticket_key.split(":")[-1]
        if self._ticket_id is not None:
            ticket = json.loads(self._redis.conn.get(self._make_ticket_key()))
            self._entry_ticket_str = str(ticket)
            if ticket["Status"] == "COMPLETED":
                ttl = self._redis.conn.ttl(self._key)
                if self.TICKET_TTL_SECONDS - ttl >= self.MAX_REJOIN_TIME:
                    ticket["Status"] = "MATCH_COMPLETE"
            self._ticket = ticket
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._lock.owned():  # If we don't own the lock at this point, we don't want to update anything
            with self._redis.conn.pipeline() as pipe:
                if self._entry_ticket_str != str(self._ticket) and exc_type in (None, GameliftClientException):
                    if self._ticket_id:
                        pipe.delete(self._make_ticket_key())  # Always update the ticket wholesale, i.e. don't leave stale fields behind.
                    if self._ticket is None:
                        pipe.delete(self._key)
                    else:
                        self._ticket_id = self._ticket["TicketId"]
                        ticket_key = self._make_ticket_key()
                        pipe.set(self._key, ticket_key, ex=self.TICKET_TTL_SECONDS)
                        pipe.set(ticket_key, self._jsonify_ticket(), ex=self.TICKET_TTL_SECONDS)
                pipe.execute()
            self._lock.release()

    def _make_ticket_key(self):
        if self._ticket_id is None:
            raise RuntimeError("Cannot make ticket key when there's no TicketId")
        return self._redis.make_key(f"flexmatch_tickets:{self._ticket_id}")

    def _jsonify_ticket(self):
        for datefield in ("StartTime", "EndTime"):
            if datefield in self._ticket:
                self._ticket[datefield] = str(self._ticket[datefield])
        return json.dumps(self._ticket)


class GameliftClientException(Exception):
    def __init__(self, user_message, debug_info):
        super().__init__(user_message, debug_info)
        self.msg = user_message
        self.debugs = debug_info

