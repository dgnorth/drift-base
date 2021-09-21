import logging
import json
import datetime
import typing
import uuid
from flask import g
from driftbase.models.db import Match
from driftbase import flexmatch, lobbies
from driftbase.lobbies import InvalidRequestException, NotFoundException, UnauthorizedException, _post_lobby_event_to_members, _get_lobby_member_player_ids, _get_lobby_key, _get_lobby_host_player_id, _get_player_lobby_key, _GenericLock, _LockedLobby

from driftbase.resources.match_placements import TIER_DEFAULTS

"""
Only lobby matches with GameLift provider supported at the time of writing!!!
"""

# TODO: Not use protected/private functions in lobbies module

log = logging.getLogger(__name__)

def get_player_match_placement(player_id: int, expected_match_placement_id: typing.Optional[str] = None) -> dict:
    placement = None
    with _GenericLock(_get_player_match_placement_key(player_id)) as player_match_placement_lock:
        placement_id = player_match_placement_lock.value

        if not placement_id:
            log.info(f"Player '{player_id}' attempted to fetch a match placement without having a match placement")
            raise NotFoundException("No match placement found")

        if expected_match_placement_id and expected_match_placement_id != placement_id:
            log.warning(f"Player '{player_id}' attempted to fetch match placement '{expected_match_placement_id}', but the player didn't issue the match placement")
            raise UnauthorizedException(f"You don't have permission to access match placement {expected_match_placement_id}")

        with _JsonLock(_get_match_placement_key(placement_id)) as match_placement_lock:
            placement = match_placement_lock.value

            if not placement:
                log.warning(f"Player '{player_id}' is assigned to match placement '{placement_id}' but the match placement doesn't exist")
                player_match_placement_lock.value = None
            else:
                log.info(f"Returning match placement '{placement_id}' for player '{player_id}'")

    if not placement:
        raise NotFoundException("No match placement found")

    return placement

def start_lobby_match_placement(player_id: int, lobby_id: str) -> dict:
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:

        # Verify data integrity
        player_lobby_id = player_lobby_lock.value
        if player_lobby_id != lobby_id:
            log.warning(f"Player '{player_id}' is attempting to start match for lobby '{lobby_id}', but is supposed to be in lobby '{player_lobby_id}'")
            raise UnauthorizedException(f"You don't have permission to access lobby {lobby_id}")

        with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
            lobby = lobby_lock.lobby

            if not lobby:
                raise RuntimeError(f"Player '{player_id}' is attempting to start match for nonexistent lobby '{lobby_id}'. Player is supposed to be in said lobby")

            # Verify host
            host_player_id = _get_lobby_host_player_id(lobby)
            if player_id != host_player_id:
                log.warning(f"Player '{player_id}' attempted to start the match for lobby '{lobby_id}' without being the lobby host")
                raise InvalidRequestException(f"You aren't the host of lobby {lobby_id}. Only the lobby host can start the lobby match")

            # Prevent issuing another placement request
            if lobby["status"] == "starting":
                log.warning(f"Player '{player_id}' attempted to start the match for lobby '{lobby_id}' while the match is starting")
                raise InvalidRequestException(f"An active match placement is already in progress for the lobby")
            
            # Select match provider
            match_provider = _get_tenant_config_value("default_match_provider")
            if match_provider != "gamelift":
                raise RuntimeError(f"Invalid match provider configured, '{match_provider}'. Only the GameLift match provider is supported at this time")

            # Request a game server
            lobby_name = lobby["lobby_name"]
            placement_id = str(uuid.uuid4())
            max_player_session_count = lobby["team_capacity"] * len(lobby["team_names"])
            game_session_name = f"Lobby-{lobby_id}-{lobby_name}"
            custom_data = lobby["custom_data"]

            lobby["placement_id"] = placement_id

            player_latencies = []
            for member in lobby["members"]:
                for region, latency in flexmatch.get_player_latency_averages(member["player_id"]).items():
                    player_latencies.append({
                        "PlayerId": str(member["player_id"]),
                        "RegionIdentifier": region,
                        "LatencyInMilliseconds": latency
                    })

            log.info(f"Host player '{player_id}' is starting lobby match for lobby '{lobby_id}'. GameLift placement id: '{placement_id}'")
            response = flexmatch.start_game_session_placement(
                PlacementId=placement_id,
                GameSessionQueueName=lobbies._get_tenant_config_value("lobby_game_session_queue"),
                MaximumPlayerSessionCount=max_player_session_count,
                GameSessionName=game_session_name,
                GameProperties=[
                    {
                        "Key": "lobby",
                        "Value": "true",
                    },
                ],
                PlayerLatencies=player_latencies,
                DesiredPlayerSessions=[
                    {
                        "PlayerId": str(member["player_id"]),
                        "PlayerData": json.dumps({
                            "player_name": member["player_name"],
                            "team_name": member["team_name"],
                            "host": member["host"],
                        }),
                    }
                    for member in lobby["members"] if member["team_name"]
                ],
                GameSessionData=json.dumps({
                    "lobby_id": lobby_id,
                    "lobby_name": lobby_name,
                    "lobby_map": lobby["map_name"],
                    "lobby_members": [
                        {
                            "player_id": str(member["player_id"]),
                            "player_name": member["player_name"],
                            "team_name": member["team_name"],
                            "host": member["host"],
                        }
                        for member in lobby["members"]
                    ],
                    "lobby_custom_data": custom_data,
                }),
            )

            log.debug(f"match_placements::start_lobby_match_placement() start_game_session_placement response: '{_jsonify(response)}'")

            match_placement = {
                "placement_id": placement_id,
                "player_id": player_id,
                "match_provider": match_provider,
                "lobby_id": lobby_id,
                "status": "pending",
                "create_date": datetime.datetime.utcnow().isoformat(),
            }

            with _JsonLock(_get_match_placement_key(placement_id)) as match_placement_lock:
                match_placement_lock.value = match_placement

            with _GenericLock(_get_player_match_placement_key(player_id)) as player_match_placement_lock:
                player_match_placement_lock.value = placement_id

            lobby["status"] = "starting"
            lobby["placement_date"] = datetime.datetime.utcnow().isoformat()

            lobby_lock.lobby = lobby

            log.info(f"GameLift game session placement issued for lobby '{lobby_id}' by host player '{player_id}'")

            # Notify members
            receiving_player_ids = _get_lobby_member_player_ids(lobby, [player_id])
            _post_lobby_event_to_members(receiving_player_ids, "LobbyMatchStarting", {"lobby_id": lobby_id, "status": lobby["status"]})

            return match_placement

def stop_player_match_placement(player_id: int, expected_match_placement_id: str):
    with _GenericLock(_get_player_match_placement_key(player_id)) as player_match_placement_lock:
        placement_id = player_match_placement_lock.value

        if expected_match_placement_id != placement_id:
            log.warning(f"Player '{player_id}' attempted to stop match placement '{expected_match_placement_id}', but the player didn't issue the match placement")
            raise UnauthorizedException(f"You don't have permission to access match placement {expected_match_placement_id}")

        with _JsonLock(_get_match_placement_key(placement_id)) as match_placement_lock:
            placement = match_placement_lock.value

            if placement:
                lobby_id = placement.get("lobby_id", None)
                if not lobby_id:
                    raise RuntimeError(f"Match placement '{placement_id}' doesn't contain a 'lobby_id' field. Only lobby match placements are supported at this time")

                match_provider = placement["match_provider"]
                if match_provider != "gamelift":
                    raise RuntimeError(f"Invalid match provider configured, '{match_provider}'. Only the GameLift match provider is supported at this time")

                placement_status = placement["status"]
                if placement_status != "pending":
                    log.warning(f"Player '{player_id}' attempted to stop match placement '{expected_match_placement_id}', but the placement is in status '{placement_status}'")
                    raise InvalidRequestException(f"Cannot stop a match placement in status {placement_status}")

                response = flexmatch.stop_game_session_placement(placement_id)

                log.debug(f"match_placements::stop_player_match_placement() stop_game_session_placement response: '{_jsonify(response)}'")

                log.info(f"Player '{player_id}' stopped match placement '{placement_id}'")

                match_placement_lock.value = None

        player_match_placement_lock.value = None

def process_gamelift_queue_event(queue_name: str, message: dict):
    log.debug(f"match-placements::process_gamelift_queue_event() received event in queue '{queue_name}': '{message}'")

    event_details = _get_event_details(message)
    event_type = event_details.get("type", None)
    if event_type is None:
        raise RuntimeError(f"No event type found. Message: '{message}'")

    log.info(f"Incoming '{event_type}' queue event: '{event_details}'")

    if event_type == "PlacementFulfilled":
        return _process_fulfilled_queue_event(event_details)
    if event_type == "PlacementCancelled":
        return _process_cancelled_queue_event(event_details)
    if event_type == "PlacementTimedOut":
        return _process_timed_out_queue_event(event_details)
    if event_type == "PlacementFailed":
        return _process_failed_queue_event(event_details)

    raise RuntimeError(f"Unknown event '{event_type}'")

def process_match_message(queue_name: str, message: dict):
    log.debug(f"match-placements::process_match_message() received event in queue '{queue_name}': '{message}'")

    event = message["event"]
    if event == "match_status_changed":
        match_id = message.get("match_id", None)
        if match_id is None:
            log.error(f"Malformed '{event}' event; 'match_id' is missing. Message: '{message}'")
            return

        match_status = message.get("match_status", None)
        if match_status is None:
            log.error(f"Malformed '{event}' event; 'match_status' is missing. Message: '{message}'")
            return

        if match_status == "ended":
            return _process_match_ended(match_id)
    else:
        log.error(f"Unexpected event '{event}' published.")

# Helpers

def _get_match_placement_key(placement_id: str) -> str:
    return g.redis.make_key(f"match-placement:{placement_id}:")

def _get_player_match_placement_key(player_id: int) -> str:
    return g.redis.make_key(f"player:{player_id}:match-placement:")

def _get_tenant_config_value(config_key):
    default_value = TIER_DEFAULTS.get(config_key, None)
    tenant = g.conf.tenant
    if tenant:
        return g.conf.tenant.get("match-placements", {}).get(config_key, default_value)
    return default_value

def _get_tenant_name():
    return g.conf.tenant.get('tenant_name')

def _get_event_details(event: dict):
    if event.get("detail-type", None) != "GameLift Queue Placement Event":
        raise RuntimeError("Event is not a GameLift Queue Placement Event!")
    details = event.get("detail", None)
    if details is None:
        raise RuntimeError("Event is missing details!")
    return details

def _get_placement_duration(event_details: dict) -> float:
    start_time = datetime.datetime.fromisoformat(event_details["startTime"].removesuffix("Z"))
    end_time = datetime.datetime.fromisoformat(event_details["endTime"].removesuffix("Z"))

    delta = end_time - start_time
    return delta.total_seconds()

def _validate_gamelift_placement_for_queue_event(placement_id: str, placement: dict) -> bool:
    if not placement:
        log.info(f"GameLift placement '{placement_id}' not found in match placements. Ignoring.")
        return False

    lobby_id = placement.get("lobby_id", None)
    if not lobby_id:
        raise RuntimeError(f"Malformed match placement. Match placement '{placement_id}' doesn't have a lobby id")

    # No longer an active placement
    with _GenericLock(_get_player_match_placement_key(placement["player_id"])) as player_match_placement_lock:
        player_match_placement_lock.value = None

    return True

def _process_fulfilled_queue_event(event_details: dict):
    placement_id = event_details["placementId"]
    duration = _get_placement_duration(event_details)

    with _JsonLock(_get_match_placement_key(placement_id)) as match_placement_lock:
        placement = match_placement_lock.value

        if not _validate_gamelift_placement_for_queue_event(placement_id, placement):
            return

        lobby_id = placement["lobby_id"]
        placement["status"] = "completed"

        log.info(f"Placement '{placement_id}' completed. Duration: '{duration}s'")

        with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
            lobby = lobby_lock.lobby

            ip_address: str = event_details["ipAddress"]
            port = int(event_details["port"])

            connection_string = f"{ip_address}:{port}"

            lobby["connection_string"] = connection_string
            lobby["status"] = "started"
            lobby["start_date"] = datetime.datetime.utcnow().isoformat()

            log.info(f"Lobby match for lobby '{lobby_id}' has started.")

            lobby_lock.lobby = lobby

            # Notify members

            # Gather connection info for each player
            connection_options_by_player_id = {}
            for player in event_details["placedPlayerSessions"]:
                player_id: int = int(player["playerId"])
                player_session_id: str = player["playerSessionId"]

                connection_options_by_player_id[player_id] = f"PlayerSessionId={player_session_id}?PlayerId={player_id}"

            # Post events to players one-by-one for unique connection info
            for member in lobby["members"]:
                member_player_id: int = member["player_id"]

                # Spectator only connection options for non-team lobby members
                connection_options = connection_options_by_player_id.get(member_player_id, "SpectatorOnly=1")

                # Sanity check that if the player is assigned to a team, the player MUST have received a player session
                member_team_name = member["team_name"]
                if member_team_name and member_player_id not in connection_options_by_player_id:
                    log.error(f"Player '{member_player_id}' in team '{member_team_name}' didn't receive a player session. Event details: '{event_details}'")
                    continue

                event_data = {
                    "lobby_id": lobby_id,
                    "status": lobby["status"],
                    "connection_string": connection_string,
                    "connection_options": connection_options,
                }
                _post_lobby_event_to_members([member_player_id], "LobbyMatchStarted", event_data)

def _process_cancelled_queue_event(event_details: dict):
    placement_id = event_details["placementId"]
    duration = _get_placement_duration(event_details)

    with _JsonLock(_get_match_placement_key(placement_id)) as match_placement_lock:
        placement = match_placement_lock.value

        if not _validate_gamelift_placement_for_queue_event(placement_id, placement):
            return

        lobby_id = placement["lobby_id"]
        placement["status"] = "cancelled"

        log.info(f"Placement '{placement_id}' cancelled. Duration: '{duration}s'")

        with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
            lobby = lobby_lock.lobby

            lobby["status"] = "cancelled"

            log.info(f"Lobby match placement for lobby '{lobby_id}' cancelled.")

            lobby_lock.lobby = lobby

            # Notify members
            receiving_player_ids = _get_lobby_member_player_ids(lobby)
            _post_lobby_event_to_members(receiving_player_ids, "LobbyMatchCancelled", {"lobby_id": lobby_id, "status": lobby["status"]})


def _process_timed_out_queue_event(event_details: dict):
    placement_id = event_details["placementId"]
    duration = _get_placement_duration(event_details)

    with _JsonLock(_get_match_placement_key(placement_id)) as match_placement_lock:
        placement = match_placement_lock.value

        if not _validate_gamelift_placement_for_queue_event(placement_id, placement):
            return

        lobby_id = placement["lobby_id"]
        placement["status"] = "timed_out"

        log.info(f"Placement '{placement_id}' timed out. Duration: '{duration}s'")

        with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
            lobby = lobby_lock.lobby

            lobby["status"] = "timed_out"

            log.info(f"Lobby match placement for lobby '{lobby_id}' timed_out.")

            lobby_lock.lobby = lobby

            # Notify members
            receiving_player_ids = _get_lobby_member_player_ids(lobby)
            _post_lobby_event_to_members(receiving_player_ids, "LobbyMatchTimedOut", {"lobby_id": lobby_id, "status": lobby["status"]})

def _process_failed_queue_event(event_details: dict):
    placement_id = event_details["placementId"]
    duration = _get_placement_duration(event_details)

    with _JsonLock(_get_match_placement_key(placement_id)) as match_placement_lock:
        placement = match_placement_lock.value

        if not _validate_gamelift_placement_for_queue_event(placement_id, placement):
            return

        lobby_id = placement["lobby_id"]
        placement["status"] = "failed"

        log.info(f"Placement '{placement_id}' failed. Duration: '{duration}s'")

        with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
            lobby = lobby_lock.lobby

            lobby["status"] = "failed"

            log.info(f"Lobby match placement for lobby '{lobby_id}' failed.")

            lobby_lock.lobby = lobby

            # Notify members
            receiving_player_ids = _get_lobby_member_player_ids(lobby)
            _post_lobby_event_to_members(receiving_player_ids, "LobbyMatchFailed", {"lobby_id": lobby_id, "status": lobby["status"]})

def _process_match_ended(match_id: int):
    match = g.db.query(Match).get(match_id)
    if not match:
        log.error(f"Match '{match_id}' not found")
        return

    details = match.details
    if details is None:
        log.info(f"Ended match '{match.match_id}' has no details. Unable to determine if the match is a lobby match.")
        return

    log.debug(f"event details: {details}")
    lobby_id = details.get("lobby_id", None)
    if lobby_id is None:
        log.info(f"Match '{match.match_id}' isn't a lobby match.")
        return

    with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
        lobby = lobby_lock.lobby

        if not lobby:
            log.error(f"Lobby '{lobby_id}' not found for match '{match.match_id}'. Match details: '{details}'")
            return

        log.info(f"Match ended for lobby '{lobby_id}'. Deleting lobby.")

        for member in lobby["members"]:
            with _GenericLock(_get_player_lobby_key(member["player_id"])) as member_lobby_id_lock:
                member_lobby_id_lock.value = None

        # Delete the lobby
        lobby_lock.lobby = None

        log.info(f"Lobby '{lobby_id}' deleted.")

        # Notify members
        receiving_player_ids = _get_lobby_member_player_ids(lobby)
        _post_lobby_event_to_members(receiving_player_ids, "LobbyDeleted", {"lobby_id": lobby_id})

def _jsonify(d: dict) -> str:
    def _json_serial(obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()

        return str(obj)

    return json.dumps(d, default=_json_serial)

class _JsonLock(object):
    """
    Context manager for synchronizing creation and modification of a json redis value.
    """
    MAX_LOCK_WAIT_TIME_SECONDS = 30
    TTL_SECONDS = 60 * 60 * 24

    def __init__(self, key):
        self._key = key
        self._redis = g.redis
        self._modified = False
        self._value = None
        self._lock = g.redis.conn.lock(self._key + "LOCK", timeout=self.MAX_LOCK_WAIT_TIME_SECONDS)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, new_value):
        self._value = new_value
        self._modified = True

    def __enter__(self):
        self._lock.acquire(blocking=True)
        value = self._redis.conn.get(self._key)
        if value is not None:
            value = json.loads(value)
            self._value = value
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._lock.owned():  # If we don't own the lock at this point, we don't want to update anything
            with self._redis.conn.pipeline() as pipe:
                if self._modified is True and exc_type is None:
                    pipe.delete(self._key)  # Always update the lobby wholesale, i.e. don't leave stale fields behind.
                    if self._value:
                        pipe.set(self._key, json.dumps(self._value, default=self._json_serial), ex=self.TTL_SECONDS)
                pipe.execute()
            self._lock.release()

    @staticmethod
    def _json_serial(obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()

        raise TypeError(f"Type {type(obj)} not serializable")
