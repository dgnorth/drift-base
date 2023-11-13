import logging
import time
import datetime
import json
import uuid
import http.client as http_client
import typing as t

from flask import g
from drift.blueprint import abort
from driftbase import flexmatch
from driftbase.models.db import Match, Server, CorePlayer
from driftbase.config import get_server_heartbeat_config
from driftbase.utils.redis_utils import JsonLock
from driftbase.messages import post_message

log = logging.getLogger(__name__)

PLACEMENT_TIMEOUT = 300  # This is the queue timeout, specified in terraform-nexus/dev/matchmaker/terragrunt.hcl
PLACEMENT_REDIS_TTL = 90
MAX_PLAYERS_PER_MATCH = 128
SANDBOX_MAP_NAME = "L_Play"

# FIXME: Return the game session arn instead of placement id

def _redis_placement_key(location_id: int) -> str:
    return g.redis.make_key(f"Sandbox-Experience-{location_id}")

def handle_player_session_request(location_id, player_id):
    """
    Handle a player session request for a sandbox placement.
    """
    log.info(f"Player session for player '{player_id}' on kratos location/experience '{location_id}'")
    # Check if there's an existing placement available in db
    game_session_arn = get_running_game_session(location_id)
    placement: t.Union[dict,None] = None
    if not game_session_arn:
        # Check/Wait for pending placements
        wait_time = 0
        while wait_time < PLACEMENT_TIMEOUT:
            with JsonLock(_redis_placement_key(location_id)) as placement_lock:
                placement = placement_lock.value
                if placement is None or placement["status"] != "pending":
                    break
            log.info(f"Placement is pending for location '{location_id}'. Waiting ({wait_time})...")
            time.sleep(0.5)
            wait_time += 1
        else:
            log.warning(f"Exceeded {wait_time} seconds for pending placement for location '{location_id}'. Giving up.")
            if placement:
                log.warning(f"Nuking sticky placement: {placement}")
                g.redis.delete(_redis_placement_key(location_id))
            abort(http_client.SERVICE_UNAVAILABLE, message="Timeout waiting for placement")

        if placement is None:
            log.info(f"No game session and no placement for location '{location_id}'. Creating it...")
            return _create_placement(location_id, player_id)
        elif placement["status"] == "completed": # recurse, we should now have a match entry with game_session_arn
            log.info(f"Placement completed while we waited. Recursing to add player session...")
            return handle_player_session_request(location_id, player_id)
        else:
            abort(http_client.SERVICE_UNAVAILABLE, message=f"Pending placement failed ({placement['status']}). Try again later.")

    log.info(f"Found existing placement '{game_session_arn}' for location '{location_id}'. Ensuring player session.")
    return _ensure_player_session(game_session_arn, player_id)

def _create_placement(location_id, player_id):
    game_session_name = _redis_placement_key(location_id)
    with JsonLock(game_session_name, ttl=PLACEMENT_TIMEOUT) as placement_lock:
        placement = placement_lock.value
        if placement is not None:  # Did we lose a race?
            return handle_player_session_request(location_id, player_id)
        placement_id = f"{uuid.uuid4().hex[:10]}-{game_session_name.split(':')[-1]}"
        player_name = g.db.query(CorePlayer.player_name). \
            filter(CorePlayer.player_id == player_id).first().player_name
        player = dict(
            PlayerId=str(player_id),
            PlayerData= json.dumps(dict(
                player_name=player_name
            ))
        )
        log.info(f"Player '{player_id}' ({player_name}) is starting server for experience '{location_id}'."
                 f" GameLift placement id: '{game_session_name}'.")
        response = flexmatch.start_game_session_placement(
            PlacementId=placement_id,
            GameSessionQueueName="default",
            MaximumPlayerSessionCount=MAX_PLAYERS_PER_MATCH,
            GameSessionName=game_session_name,
            GameProperties=[{
                "Key": "CustomMatch",
                "Value": "1",
            }],
            DesiredPlayerSessions=[player],
            GameSessionData=json.dumps({
                "map_name": SANDBOX_MAP_NAME,
                "players": [player],
                "custom_data": json.dumps(dict(KratosLocation=location_id)),
            }),
        )
        log.info(f"Placement start response for placement '{placement_id}': '{str(response)}'")
        match_placement = {
            "placement_id": placement_id,
            "status": "pending",
            "create_date": datetime.datetime.utcnow().isoformat(),
            "kratos_location": location_id,
            "game_session_arn": None,
            "player_ids": [player_id],
        }
        placement_lock.value = match_placement
        return placement_id

def get_running_game_session(location_id):
    """
    Returns a running match for a location if such a thing exists
    """
    _, heartbeat_timeout = get_server_heartbeat_config()
    matches = g.db.query(Match, Server) \
        .filter(Match.server_id == Server.server_id,
                Server.status == "ready",
                Match.status == "started",
                Match.game_mode == "Sandbox",
                Server.heartbeat_date >= datetime.datetime.utcnow() - datetime.timedelta(seconds=heartbeat_timeout)) \
        .all()

    # I should be able to put this in the filter above, but I get
    # "sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedFunction) operator does not exist: json = unknown"
    # when I do that. So a bit of manual filtering instead.
    detail = "{\"KratosLocation\": %d}" % location_id
    for match, server in matches:
        if match.details["custom_data"] == detail:
            log.info(f"Found a running match for '{location_id}'.")
            return match.details["game_session_arn"]

def _ensure_player_session(game_session_arn, player_id):
    game_sessions = flexmatch.describe_game_sessions(GameSessionId=game_session_arn)
    if len(game_sessions["GameSessions"]) == 0:
        log.warning(f"game session '{game_session_arn}' has become invalid.")
        abort(http_client.SERVICE_UNAVAILABLE, message="Game session is no longer valid")
    game_session = game_sessions["GameSessions"][0]
    game_session_status = game_session["Status"]
    if game_session_status not in ("ACTIVE", "ACTIVATING"):
        log.warning(f"Game session '{game_session_arn}' is in status '{game_session_status}'. "
                    f"Can't manage player sessions for game sessions in that state")
        abort(http_client.SERVICE_UNAVAILABLE, message=f"Game session '{game_session_arn}' is not in an active state")
    # Check if player has a valid player session
    player_sessions = flexmatch.describe_player_sessions(GameSessionId=game_session_arn)
    for player_session in player_sessions["PlayerSessions"]:
        if player_session["PlayerId"] == str(player_id) and player_session["Status"] in ("RESERVED", "ACTIVE"):
            log.info(f"found existing player session '{player_session}'.")
            break
    else:  # Create new player session since no valid one was found
        player_session = flexmatch.create_player_session(
            GameSessionId=game_session_arn,
            PlayerId=str(player_id)
        )
    connection_info = f"{game_session['IpAddress']}:{game_session['Port']}?PlayerSessionId={player_session['PlayerSessionId']}?PlayerId={player_session['PlayerId']}"
    _post_connection_info(player_id, game_session_arn, connection_info)
    return game_session["GameSessionId"]


def process_placement_event(queue_name, message: dict):
    log.info(f"sandbox::process_placement_event received event in queue '{queue_name}': '{message}'")
    if message.get("detail-type", None) != "GameLift Queue Placement Event":
        log.error("Event is not a GameLift Queue Placement Event. Ignoring")
        return
    details = message.get("detail", None)
    if details is None:
        log.error("Event is missing details! Ignoring event.")
        return
    event_type = details.get("type", None)
    if event_type is None:
        log.error(f"No event type found. Message: '{message}'. Ignoring event.")
        return

    log.info(f"Got '{event_type}' queue event: '{details}'")

    if event_type == "PlacementFulfilled":
        log.info(f"Placement {details['placementId']}. Updating cache.")
        return _process_fulfilled_event(details)
    elif event_type in ("PlacementCancelled", "PlacementTimedOut", "PlacementFailed"):
        log.warning(f"Placement failed: '{event_type}'. Nuking placement cache")
        return _process_placement_failure(details["placementId"], event_type)

    raise RuntimeError(f"Unknown event '{event_type}'")

def _process_placement_failure(placement_id, failure):
    location_id = placement_id.split('-')[-1]
    with JsonLock(_redis_placement_key(location_id), PLACEMENT_REDIS_TTL) as placement_lock:
        placement = placement_lock.value
        if placement is None:
            log.error(f"_process_placement_failure: Placement '{placement_id}' not found in redis. Ignoring event.")
            return
        placement_lock.value = None
    _post_failure(placement["player_ids"][0], placement_id, failure)

def _process_fulfilled_event(details: dict):
    placement_id = details["placementId"]
    location_id = placement_id.split('-')[-1]
    with JsonLock(_redis_placement_key(location_id), PLACEMENT_REDIS_TTL) as placement_lock:
        placement = placement_lock.value
        if placement is None:
            log.error(f"_process_fulfilled_queue_event: Placement '{placement_id}' not found in redis. Ignoring event.")
            return
        ip_address = details["ipAddress"]
        port = int(details["port"])

        connection_string = f"{ip_address}:{port}"
        placement["status"] = "completed"
        placement["game_session_arn"] = details["gameSessionArn"]
        placement["connection_string"] = connection_string
        placement_lock.value = placement
        log.info(f"_process_fulfilled_queue_event: Placement '{placement_id}' - Updating cache to {placement}.")

        players = details["placedPlayerSessions"]
        if len(players) != 1:
            log.warning(f"_process_fulfilled_queue_event: Placement '{placement_id}' has {len(players)} players. Expected 1. Still sending notification.")

        for player in players:
            player_connection_info = f"{connection_string}?PlayerSessionId={player['playerSessionId']}?PlayerId={player['playerId']}"
            _post_connection_info(int(player["playerId"]), placement["game_session_arn"], player_connection_info)

def _post_connection_info(player_id, game_session_arn, connection_string):
    payload = {
        "event": "PlayerSessionReserved",
        "data": {
            "game_session": game_session_arn,
            "connection_info": connection_string,
        }
    }
    log.info(f"posting '{payload}' to player '{player_id}'")
    post_message("players", player_id, "sandbox", payload, sender_system=True)

def _post_failure(player_id, placement_id, error):
    payload = {
        "event": "SessionCreationFailed",
        "data": {
            "placement_id": placement_id,  # for debug
            "error": error,
        }
    }
    log.info(f"posting '{payload}' to player '{player_id}'")
    post_message("players", player_id, "sandbox", payload, sender_system=True)
