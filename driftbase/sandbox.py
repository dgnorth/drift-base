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
MAX_RECURSION_LEVEL = 20

# FIXME: Return the game session arn instead of placement id

def _redis_placement_key(location_id: int, queue: str) -> str:
    return g.redis.make_key(f"{queue}-SB-Experience-{location_id}")

def handle_player_session_request(location_id: int, player_id: int, queue=t.Union[str,None], recursionlevel=0) -> str:
    """
    Handle a player session request for a sandbox placement.
    """

    if queue is None:
        queue = "default"
    log.info(f"Player session for player '{player_id}' on kratos location/experience '{location_id}' in queue '{queue}'")
    # Check if there's an existing placement available in db
    game_session_arn: str = get_running_game_session(location_id, queue)
    placement: t.Union[dict,None] = None
    if not game_session_arn:
        # Check/Wait for pending placements
        wait_time = 0
        sleep_time = 0.5
        while wait_time < PLACEMENT_TIMEOUT:
            with JsonLock(_redis_placement_key(location_id, queue)) as placement_lock:
                placement: dict = placement_lock.value
                if placement is None or placement["status"] != "pending":
                    break
            log.info(f"Placement is pending for location '{location_id}'. Waiting ({wait_time}/{PLACEMENT_TIMEOUT})...")
            time.sleep(sleep_time)
            wait_time += sleep_time
        else:
            log.warning(f"Exceeded {PLACEMENT_TIMEOUT} seconds for pending placement for location '{location_id}'. Giving up.")
            if placement:
                log.warning(f"Nuking sticky placement: {placement}")
                g.redis.delete(_redis_placement_key(location_id, queue))
            abort(http_client.SERVICE_UNAVAILABLE, message="Timeout waiting for placement")

        if placement is None:
            log.info(f"No game session and no placement for location '{location_id}'. Creating it...")
            return _create_placement(location_id, player_id, queue)
        elif placement["status"] == "completed": # recurse, we should now have a match entry with game_session_arn
            log.info(f"Placement completed while we waited. Recursing in 1 second to add player session...")
            sleep_time = 0.5
            time.sleep(sleep_time)
            if recursionlevel > MAX_RECURSION_LEVEL:
                log.error(f"Server hasn't registered a match on this experience yet. "
                          f"It's been {sleep_time*MAX_RECURSION_LEVEL} seconds since it reported ready to gamelift. "
                          f"Check placement {placement['placement_id']} I Giving up")
                abort(http_client.SERVICE_UNAVAILABLE, message="Too many recursions. Giving up.")
            return handle_player_session_request(location_id, player_id, queue, recursionlevel+1)
        else:
            abort(http_client.SERVICE_UNAVAILABLE, message=f"Pending placement failed ({placement['status']}). Try again later.")

    log.info(f"Found existing placement '{game_session_arn}' for location '{location_id}'. Ensuring player session.")
    return _ensure_player_session(game_session_arn, player_id)

def _create_placement(location_id: int, player_id: int, queue: str) -> str:
    # FIXME: It's probably a good idea to disassociate the game_session_name and the placement_id completely
    # and just store a 'pointer' from the placement_id to the redis key so we can look it up from the placement id.
    # For context, placement_id must be unique and can't be re-used, but since it's really useful to be able to look up
    # cached placements knowing only the location_id (and queue), we want the redis key to be deterministic.
    # So, in summary, redis key should be deterministic, but the placement_id needs have a random element and we need to
    # be able to map from placement_id to key.  We're currently relying on the format of the placement_id to do this
    # but it's ugly and fragile.
    game_session_name = _redis_placement_key(location_id, queue)
    with JsonLock(game_session_name, ttl=PLACEMENT_TIMEOUT) as placement_lock:
        placement: dict = placement_lock.value
        if placement is not None:  # Did we lose a race?
            return handle_player_session_request(location_id, player_id)
        placement_id = f"{uuid.uuid4().hex[:10]}-{game_session_name.split(':')[-1]}"
        player_name: t.Union[str,None] = g.db.query(CorePlayer.player_name). \
            filter(CorePlayer.player_id == player_id).first().player_name
        player = dict(
            PlayerId=str(player_id),
            PlayerData= json.dumps(dict(
                player_name=player_name
            ))
        )
        log.info(f"Player '{player_id}' ({player_name}) is starting server for experience '{location_id}'."
                 f" Session name/Redis key: '{game_session_name}' - Placement Id: {placement_id}.")
        response: dict = flexmatch.start_game_session_placement(
            PlacementId=placement_id,
            GameSessionQueueName=queue,
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
                "custom_data": json.dumps(dict(
                    KratosLocation=location_id,
                    Queue=queue,
                )),
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
            "queue": queue,
        }
        placement_lock.value = match_placement
        return placement_id

def get_running_game_session(location_id: int, queue: str) -> t.Union[str,None]:
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

    # FIXME: Do the json field filtering on details in the query
    for match, server in matches:
        match_queue = match.details.get("queue")
        kratos_location_id = match.details.get("kratos_location_id")
        if match_queue == queue and kratos_location_id == location_id:
            log.info(f"Found a running match for '{location_id}' in queue '{queue}'.")
            return match.details["game_session_arn"]

    return None

def _ensure_player_session(game_session_arn: str, player_id: int) -> str:
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
        )['PlayerSession']
        log.info(f"Created new player session '{player_session}'.")
    connection_info = f"{game_session['IpAddress']}:{game_session['Port']}?PlayerSessionId={player_session['PlayerSessionId']}?PlayerId={player_session['PlayerId']}"
    _post_connection_info(player_id, game_session_arn, connection_info)
    return game_session["GameSessionId"]


def process_placement_event(queue_name: str, message: dict) -> None:
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

    fleet_queue_arn = message.get("resources", [""])[0]
    fleet_queue = "default" if not fleet_queue_arn else fleet_queue_arn.split('/')[-1]

    if event_type == "PlacementFulfilled":
        log.info(f"Placement {details['placementId']}. Updating cache.")
        return _process_fulfilled_event(details, fleet_queue)
    elif event_type in ("PlacementCancelled", "PlacementTimedOut", "PlacementFailed"):
        log.warning(f"Placement failed: '{event_type}'. Nuking placement cache")
        return _process_placement_failure(details["placementId"], fleet_queue, event_type)

    raise RuntimeError(f"Unknown event '{event_type}'")

def _process_placement_failure(placement_id: str, queue: str, failure: str) -> None:
    location_id = placement_id.split('-')[-1]
    with JsonLock(_redis_placement_key(int(location_id), queue), PLACEMENT_REDIS_TTL) as placement_lock:
        placement = placement_lock.value
        if placement is None:
            log.error(f"_process_placement_failure: Placement '{placement_id}' not found in redis. Ignoring event.")
            return
        placement_lock.value = None
    _post_failure(placement["player_ids"][0], placement_id, failure)

def _process_fulfilled_event(details: dict, queue: str) -> None:
    placement_id = details["placementId"]
    location_id = placement_id.split('-')[-1]
    with JsonLock(_redis_placement_key(location_id, queue), PLACEMENT_REDIS_TTL) as placement_lock:
        placement = placement_lock.value
        if placement is None:
            log.info(f"_process_fulfilled_event: Placement '{placement_id}' not found in redis. Ignoring event.")
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
