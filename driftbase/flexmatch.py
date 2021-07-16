import copy
import logging
import boto3
import json
from collections import defaultdict
from botocore.exceptions import ClientError, ParamValidationError
from flask import g
from aws_assume_role_lib import assume_role
from driftbase.parties import get_player_party, get_party_members
from driftbase.api.messages import post_message

from driftbase.resources.flexmatch import TIER_DEFAULTS

NUM_VALUES_FOR_LATENCY_AVERAGE = 3
REDIS_TTL = 1800

# FIXME: Figure out how to do multi-region matchmaking; afaik, the configuration isn't region based, but both queues and
#  events are. The queues themselves can have destination fleets in multiple regions.
AWS_REGION = "eu-west-1"

log = logging.getLogger(__name__)

# Latency reporting

def update_player_latency(player_id, region, latency_ms):
    region_key = _get_player_latency_key(player_id) + region
    with g.redis.conn.pipeline() as pipe:
        pipe.lpush(region_key, latency_ms)
        pipe.ltrim(region_key, 0, NUM_VALUES_FOR_LATENCY_AVERAGE-1)
        pipe.execute()

def get_player_latency_averages(player_id):
    player_latency_key = _get_player_latency_key(player_id)
    regions = _get_player_regions(player_id)
    with g.redis.conn.pipeline() as pipe:
        for region in regions:
            pipe.lrange(player_latency_key + region, 0, NUM_VALUES_FOR_LATENCY_AVERAGE)
        results = pipe.execute()
    return {
        region: int(sum(float(latency) for latency in latencies) / min(NUM_VALUES_FOR_LATENCY_AVERAGE, len(latencies)))  # FIXME: return default values if no values have been reported?
        for region, latencies in zip(regions, results)
    }


#  Matchmaking

def upsert_flexmatch_ticket(player_id, matchmaking_configuration):
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

        gamelift_client = GameLiftRegionClient(AWS_REGION)
        try:
            log.info(f"Issuing a new matchmaking ticket for playerIds {member_ids} on behalf of calling player {player_id}")
            response = gamelift_client.start_matchmaking(
                ConfigurationName=matchmaking_configuration,
                Players=[
                    {
                        "PlayerId": str(member_id),
                        "PlayerAttributes": _get_player_attributes(member_id),
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

        _post_matchmaking_event_to_members(member_ids, "MatchmakingStarted")
        return ticket_lock.ticket

def cancel_player_ticket(player_id):
    with _LockedTicket(_get_player_ticket_key(player_id)) as ticket_lock:
        ticket = ticket_lock.ticket
        if not ticket:
            log.info(f"Not cancelling non-existent ticket for player {player_id}")
            return
        if ticket["Status"] in ("COMPLETED", "PLACING", "REQUIRES_ACCEPTANCE"):
            log.info(f"Not cancelling ticket for player {player_id} as he has crossed the Rubicon on ticket {ticket['TicketId']}")
            return ticket["Status"]  # Don't allow cancelling if we've already put you in a match or we're in the process of doing so
        log.info(f"Cancelling ticket for player {player_id}, currently in state {ticket['Status']}")
        gamelift_client = GameLiftRegionClient(AWS_REGION)
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

def get_player_ticket(player_id):
    with _LockedTicket(_get_player_ticket_key(player_id)) as ticket_lock:
        log.info(f"Returning ticket for player {player_id}: {ticket_lock.ticket}")
        return ticket_lock.ticket

def update_player_acceptance(player_id, match_id, acceptance):
    with _LockedTicket(_get_player_ticket_key(player_id)) as ticket_lock:
        player_ticket = ticket_lock.ticket
        if player_ticket is None:
            log.warning(f"Request to update acceptance for player {player_id} who has no ticket. Ignoring")
            return
        ticket_id = player_ticket["TicketId"]
        log.info(f"Updating acceptance state of ticket {ticket_id} for player {player_id}")
        if player_ticket["Status"] != "REQUIRES_ACCEPTANCE":
            log.error(f"Ticket {ticket_id} doesn't require acceptance! Ignoring.")
            return
        if player_ticket["MatchId"] != match_id:
            log.error(f"The matchId in ticket {ticket_id} doesn't match {match_id}! Ignoring.")
            return

        acceptance_type = 'ACCEPT' if acceptance else 'REJECT'
        log.info(f"Updating acceptance on ticket {player_ticket['TicketId']} for player {player_id} to {acceptance_type}")
        gamelift_client = GameLiftRegionClient(AWS_REGION)
        try:
            gamelift_client.accept_match(TicketId=ticket_id, PlayerIds=[str(player_id)], AcceptanceType=acceptance_type)
        except ClientError as e:
            raise GameliftClientException(f"Failed to update acceptance for player {player_id}, ticket {ticket_id}", str(e))

def get_valid_regions():
    tenant = g.conf.tenant
    default_regions = TIER_DEFAULTS["valid_regions"]
    if tenant:
        return g.conf.tenant.get("gamelift", {}).get("valid_regions", default_regions)
    return default_regions

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



# Helpers

def _get_player_regions(player_id):
    """ Return a list of regions for whom 'player_id' has reported latency values. """
    # FIXME: Using KEYS is fairly slow; consider adding a set keyd on the player holding all regions he reports
    return [e.decode("ascii").split(':')[-1] for e in g.redis.conn.keys(_get_player_latency_key(player_id) + '*')]

def _get_player_latency_key(player_id):
    return g.redis.make_key(f"player:{player_id}:latencies:")

def _get_player_ticket_key(player_id):
    player_party_id = get_player_party(player_id)
    if player_party_id is not None:
        return g.redis.make_key(f"party:{player_party_id}:flexmatch:")
    return g.redis.make_key(f"player:{player_id}:flexmatch:")

def _get_player_party_members(player_id):
    """ Return the full list of players who share a party with 'player_id', including 'player_id'. If 'player_id' isn't
    in a party, the returned list will contain only 'player_id'"""
    party_id = get_player_party(player_id)
    if party_id:
        return get_party_members(int(party_id))
    return [player_id]

def _get_player_attributes(player_id):
    # FIXME: Placeholder for extra matchmaking attribute gathering per player
    return {"skill": {"N": 50}}

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
        post_message("players", receiver_id, "matchmaking", payload, expiry, sender_system=True)

def _get_gamelift_role():
    default_role = TIER_DEFAULTS["aws_gamelift_role"]
    if g.conf.tenant:
        return g.conf.tenant.get("gamelift", {}).get("assume_role", default_role)
    return default_role

def _get_event_details(event):
    if event.get("detail-type", None) != "GameLift Matchmaking Event":
        raise RuntimeError("Event is not a GameLift Matchmaking Event!")
    details = event.get("detail", None)
    if details is None:
        raise RuntimeError("Event is missing details!")
    return details

def _process_searching_event(event):
    # This block is probably useless, but it sanity checks...
    players_by_ticket = defaultdict(set)
    for ticket in event["tickets"]:
        ticket_id = ticket["ticketId"]
        for player in ticket["players"]:
            players_by_ticket[ticket_id].add(int(player["playerId"]))

    updated_tickets = set()
    player_ids_to_notify = set()
    game_session_info = event["gameSessionInfo"]
    for player in game_session_info["players"]:
        player_id = int(player["playerId"])
        ticket_key = _get_player_ticket_key(player_id)
        with _LockedTicket(ticket_key) as ticket_lock:
            player_ticket = ticket_lock.ticket
            if player_ticket is None:  # This has to be a back fill ticket, i.e. not issued by us.
                log.info(f"Ignoring back-fill ticket with player {player_id} in it as current player.")
                continue
            if ticket_key in updated_tickets:
                log.info(f"Skipping update on ticket for player {player_id} as it resolves to previously updated ticket key {ticket_key}")
                continue
            if player_ticket.get("GameSessionConnectionInfo", None) is not None:
                # If we've recorded a session, then the player is in a match already and this is either a backfill ticket or a very much out of order ticket
                log.info(f"Player {player_id} has a session already. Not updating {player_ticket['TicketId']}")
                continue
            if player_ticket["Status"] == "SEARCHING":
                continue  # Save on redis calls
            if player_ticket["Status"] not in ("QUEUED", "REQUIRES_ACCEPTANCE"):
                log.info(f"MatchmakingSearching event for ticket {player_ticket['TicketId']} in state {player_ticket['Status']} doesn't make sense.  Probably out of order delivery; ignoring.")
                continue
            # sanity check
            if player_id not in players_by_ticket.get(player_ticket["TicketId"], []):
                for ticket, players in players_by_ticket.items():
                    if player_id in players:
                        log.warning(f"Weird, player {player_id} is registered to ticket {player_ticket['TicketId']} but this update pegs him on ticket {ticket}")
                        break
            log.info(f"Updating ticket {player_ticket['TicketId']} from {player_ticket['Status']} to SEARCHING")
            player_ticket["Status"] = "SEARCHING"
            ticket_lock.ticket = player_ticket
            updated_tickets.add(ticket_key)
            player_ids_to_notify.add(player_id)
    _post_matchmaking_event_to_members(player_ids_to_notify, "MatchmakingSearching")

def _process_potential_match_event(event):
    player_ids_to_notify = set()
    players_by_team = defaultdict(set)
    players_by_ticket = defaultdict(set)  # For sanity checking
    for ticket in event["tickets"]:
        ticket_id = ticket["ticketId"]
        for player in ticket["players"]:
            player_id = int(player["playerId"])
            players_by_ticket[ticket_id].add(player_id)
            players_by_team[player["team"]].add(player_id)

    acceptance_required = event["acceptanceRequired"]
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
            if player_id not in players_by_ticket.get(player_ticket["TicketId"], []):
                for ticket, players in players_by_ticket.items():
                    if player_id in players:
                        log.warning(f"Weird, player {player_id} is registered to ticket {player_ticket['TicketId']} but this update pegs him on ticket {ticket}")
                        break
            log.info(f"Updating ticket {ticket['ticketId']} for player key {ticket_key} from {player_ticket['Status']} to {new_state}")
            player_ticket["Status"] = new_state
            player_ticket["MatchId"] = event["matchId"]
            player_ids_to_notify.add(player_id)
            ticket_lock.ticket = player_ticket

    message_data = {team: list(players) for team, players in players_by_team.items()}
    message_data["acceptance_required"] = event["acceptanceRequired"]
    message_data["match_id"] = event["matchId"];
    message_data["acceptance_timeout"] = event.get("acceptanceTimeout", None)
    _post_matchmaking_event_to_members(player_ids_to_notify, "PotentialMatchCreated", event_data=message_data)

def _process_matchmaking_succeeded_event(event):
    game_session_info = event["gameSessionInfo"]
    ip_address = game_session_info["ipAddress"]
    port = int(game_session_info["port"])
    connection_string = f"{ip_address}:{port}"
    connection_info_by_player_id = {}
    players_by_ticket = defaultdict(set)  # For sanity checking
    players_to_notify = set()
    for ticket in event["tickets"]:
        ticket_id = ticket["ticketId"]
        for player in ticket["players"]:
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
            if player_ticket is None:  # This has to be a back fill ticket, i.e. not issued by us.
                log.info(f"MatchmakingSucceeded event received for a player who has no ticket. Probably backfill.")
                continue
            if player_ticket.get("GameSessionConnectionInfo", None) is not None:
                # If we've recorded a session, then the player has been placed in a match already, or there are multiple players in the ticket.
                # either way, we dont want/need to update it.
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
                "ConnectionString": f"{ip_address}:{port}",
                "ConnectionOptions": connection_info_by_player_id[player_id]
            })
            ticket_lock.ticket = player_ticket
            for ticket_player in player_ticket["Players"]:
                players_to_notify.add(int(ticket_player["PlayerId"]))

    for player_id in players_to_notify:
        event_data = {
            "connection_string": connection_string,
            "options": connection_info_by_player_id[player_id]
        }
        _post_matchmaking_event_to_members([player_id], "MatchmakingSuccess", event_data=event_data)

def _process_matchmaking_cancelled_event(event):
    for ticket in event["tickets"]:
        ticket_id = ticket["ticketId"]
        for player in ticket["players"]:
            player_id = player["playerId"]
            ticket_key = _get_player_ticket_key(player_id)
            with _LockedTicket(ticket_key) as ticket_lock:
                player_ticket = ticket_lock.ticket
                if player_ticket is None:
                    continue  # Normal, player cancelled the ticket and we've already cleared it from the cache
                if player_ticket["Status"] == "COMPLETED" and ticket_id != player_ticket["TicketId"]:
                    # This is not a flexmatch status, but I want to differentiate between statuses arising from the
                    # cancelling of backfill tickets and other states
                    player_ticket["Status"] = "MATCH_COMPLETE"
                else:
                    player_ticket["Status"] = "CANCELLED"
                    _post_matchmaking_event_to_members([player_id], "MatchmakingCancelled")
                ticket_lock.ticket = player_ticket

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
                        ticket_lock.ticket = player_ticket
                        break
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
            ticket_lock.ticket = player_ticket

def _process_matchmaking_timeout_event(event):
    players_to_notify = set()
    for ticket in event["tickets"]:
        ticket_id = ticket["ticketId"]
        for player in ticket["players"]:
            player_id = int(player["playerId"])
            ticket_key = _get_player_ticket_key(player_id)
            with _LockedTicket(ticket_key) as ticket_lock:
                player_ticket = ticket_lock.ticket
                if player_ticket is None:
                    log.warning(f"Timeout event for ticket {ticket_id} includes player {player_id} who has no ticket.")
                    continue
                if ticket_id != player_ticket["TicketId"]:
                    # Maybe a timeout on a backfill ticket?
                    log.warning(f"Timeout event for ticket {ticket_id} includes player {player_id} who has ticket {player_ticket['TicketId']}.")
                    continue
                if player_ticket.get("GameSessionConnectionInfo", None) is not None:
                    # If we've recorded a session, then the player has been placed in a match already
                    log.info(f"Player {player_id} has a session attached to his ticket.  Timeout is nonsensical here. Ignoring.")
                    continue
                player_ticket["Status"] = "TIMED_OUT"
                ticket_lock.ticket = player_ticket
                players_to_notify.add(player_id)
    _post_matchmaking_event_to_members(players_to_notify, "MatchmakingFailed", event_data={"reason": "TimeOut"})

def _process_matchmaking_failed_event(event):
    # FIXME: This is pretty much the same as a timeout; refactor
    players_to_notify = set()
    for ticket in event["tickets"]:
        ticket_id = ticket["ticketId"]
        for player in ticket["players"]:
            player_id = int(player["playerId"])
            ticket_key = _get_player_ticket_key(player_id)
            with _LockedTicket(ticket_key) as ticket_lock:
                player_ticket = ticket_lock.ticket
                if player_ticket is None:
                    log.warning(f"Failed event for ticket {ticket_id} includes player {player_id} who has no ticket.")
                    continue
                if ticket_id != player_ticket["TicketId"]:
                    # Maybe a failure on a backfill ticket?
                    log.warning(f"Failed event for ticket {ticket_id} includes player {player_id} who has ticket {player_ticket['TicketId']}.")
                    continue
                if player_ticket.get("GameSessionConnectionInfo", None) is not None:
                    # If we've recorded a session, then the player has been placed in a match already
                    log.info(f"Player {player_id} has a session attached to his ticket.  Timeout is nonsensical here. Ignoring.")
                    continue
                player_ticket["Status"] = "FAILED"
                ticket_lock.ticket = player_ticket
                players_to_notify.add(player_id)
    _post_matchmaking_event_to_members(players_to_notify, "MatchmakingFailed", event_data={"reason": event["reason"]})


class GameLiftRegionClient(object):
    __gamelift_clients_by_region = {}
    __gamelift_sessions_by_region = {}

    def __init__(self, region):
        self.region = region
        client = self.__class__.__gamelift_clients_by_region.get(region)
        if client is None:
            session = self.__class__.__gamelift_sessions_by_region.get(region)
            if session is None:
                session = boto3.Session(region_name=self.region)
                role_to_assume = _get_gamelift_role()
                if role_to_assume:
                    session = assume_role(session, role_to_assume)
                self.__class__.__gamelift_sessions_by_region[region] = session
            client = session.client("gamelift")
            self.__class__.__gamelift_clients_by_region[region] = client

    def __getattr__(self, item):
        return getattr(self.__class__.__gamelift_clients_by_region[self.region], item)


class _LockedTicket(object):
    """
    Context manager for synchronizing creation and modification of matchmaking tickets.
    """
    MAX_LOCK_WAIT_TIME_SECONDS = 30
    TICKET_TTL_SECONDS = 10 * 60

    def __init__(self, key):
        self._key = key
        self._redis = g.redis
        self._modified = False
        self._ticket = None
        self._lock = g.redis.conn.lock(self._key + "LOCK", timeout=self.MAX_LOCK_WAIT_TIME_SECONDS)

    @property
    def ticket(self):
        return self._ticket

    @ticket.setter
    def ticket(self, new_ticket):
        self._ticket = new_ticket
        self._modified = True

    def __enter__(self):
        self._lock.acquire(blocking=True)
        ticket = self._redis.conn.get(self._key)
        if ticket is not None:
            self._ticket = json.loads(ticket)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._lock.owned():  # If we don't own the lock at this point, we don't want to update anything
            with self._redis.conn.pipeline() as pipe:
                if self._modified is True and exc_type in (None, GameliftClientException):
                    pipe.delete(self._key)  # Always update the ticket wholesale, i.e. don't leave stale fields behind.
                    if self._ticket:
                        pipe.set(self._key, self._jsonify_ticket(), ex=self.TICKET_TTL_SECONDS, keepttl=True)
                pipe.execute()
            self._lock.release()

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

