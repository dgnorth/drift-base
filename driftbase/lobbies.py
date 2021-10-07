import logging
import json
import typing
import random
import string
import datetime
import copy
from collections import defaultdict
from flask import g
from driftbase.models.db import CorePlayer
from driftbase.messages import post_message
from driftbase import flexmatch, parties

from driftbase.resources.lobbies import TIER_DEFAULTS

log = logging.getLogger(__name__)

# TODO: Prevent deadlocks via key sorting and locking

MAX_LOBBY_ID_GENERATION_RETRIES = 100

def get_player_lobby(player_id: int, expected_lobby_id: typing.Optional[str] = None):
    lobby = None
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        lobby_id = player_lobby_lock.value

        if not lobby_id:
            log.info(f"Player '{player_id}' attempted to fetch a lobby without being a member of any lobby")
            message = f"Lobby {expected_lobby_id} not found" if expected_lobby_id else "No lobby found"
            raise NotFoundException(message)

        if expected_lobby_id and expected_lobby_id != lobby_id:
            log.warning(f"Player '{player_id}' attempted to fetch lobby '{expected_lobby_id}', but isn't a member of that lobby. Player is in lobby '{lobby_id}'")
            raise UnauthorizedException(f"You don't have permission to access lobby {expected_lobby_id}")

        with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
            lobby = lobby_lock.lobby

            if not lobby:
                log.warning(f"Player '{player_id}' is assigned to lobby '{lobby_id}' but the lobby doesn't exist")
                player_lobby_lock.value = None
                # Not raising NotFoundException so that the _GenericLock writes to Redis
            else:
                log.info(f"Returning lobby '{lobby_id}' for player '{player_id}'")

                # Sanity check that the player is a member of the lobby
                if not _get_lobby_member(lobby, player_id):
                    log.error(f"Player '{player_id}' is supposed to be in lobby '{lobby_id}' but isn't a member of the lobby")
                    player_lobby_lock.value = None
                    lobby = None
                else:
                    lobby = _get_personalized_lobby(lobby, player_id)

    if not lobby:
        raise NotFoundException("No lobby found")

    return lobby

def create_lobby(player_id: int, team_capacity: int, team_names: list[str], lobby_name: typing.Optional[str], map_name: typing.Optional[str], custom_data: typing.Optional[str]):
    if parties.get_player_party(player_id) is not None:
        log.warning(f"Failed to create lobby for player '{player_id}' due to player being in a party")
        raise InvalidRequestException(f"Cannot create a lobby while in a party")

    matchmaking_ticket = flexmatch.get_player_ticket(player_id)
    if matchmaking_ticket and matchmaking_ticket["Status"] not in ("MATCH_COMPLETE", "FAILED", "TIMED_OUT", "", None):
        log.warning(f"Failed to create lobby for player '{player_id}' due to player having an active matchmaking ticket")
        raise InvalidRequestException(f"Cannot create a lobby while matchmaking")

    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        # Leave/delete existing lobby if any
        if player_lobby_lock.value:
            log.info(f"Player '{player_id}' is creating a lobby while being a member of lobby {player_lobby_lock.value}")
            try:
                _internal_leave_lobby(player_id, player_lobby_lock.value)
            except NotFoundException:
                pass

        player_name: str = g.db.query(CorePlayer.player_name).filter(CorePlayer.player_id == player_id).first().player_name

        for _ in range(MAX_LOBBY_ID_GENERATION_RETRIES):
            lobby_id = _generate_lobby_id()

            with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
                if lobby_lock.lobby is not None:
                    log.info(f"Generated an existing lobby id. That's very unlucky (or lucky). Retrying...")
                    continue

                log.info(f"Creating lobby '{lobby_id}' for player '{player_id}'")

                new_lobby = {
                    "lobby_id": lobby_id,
                    "lobby_name": lobby_name or _get_tenant_config_value("default_lobby_name"),
                    "map_name": map_name,
                    "team_capacity": team_capacity,
                    "team_names": team_names,
                    "create_date": datetime.datetime.utcnow().isoformat(),
                    "start_date": None,
                    "placement_date": None,
                    "status": "idle",
                    "custom_data": custom_data,
                    "members": [
                        {
                            "player_id": player_id,
                            "player_name": player_name,
                            "team_name": None,
                            "ready": False,
                            "host": True,
                            "join_date": datetime.datetime.utcnow().isoformat(),
                        }
                    ],
                }

                player_lobby_lock.value = lobby_id
                lobby_lock.lobby = new_lobby
                return new_lobby

        raise RuntimeError(f"Failed to generate unique lobby id for player '{player_id}'. Retried '{MAX_LOBBY_ID_GENERATION_RETRIES}' times")

def update_lobby(player_id: int, expected_lobby_id: str, team_capacity: typing.Optional[int], team_names: list[str], lobby_name: typing.Optional[str], map_name: typing.Optional[str], custom_data: typing.Optional[str]):
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        lobby_id = player_lobby_lock.value

        if expected_lobby_id != lobby_id:
            log.warning(f"Player '{player_id}' attempted to update lobby '{expected_lobby_id}', but isn't a member of that lobby. Player is in lobby '{lobby_id}'")
            raise UnauthorizedException(f"You don't have permission to access lobby {expected_lobby_id}")

        with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
            lobby = lobby_lock.lobby

            if not lobby:
                log.warning(f"Player '{player_id}' attempted to update assigned lobby '{lobby_id}' but the lobby doesn't exist")
                player_lobby_lock.value = None
                raise NotFoundException(f"Lobby {lobby_id} not found")

            host_player_id = _get_lobby_host_player_id(lobby)

            if host_player_id != player_id:
                log.warning(f"Player '{player_id}' attempted to update a lobby without being the lobby host")
                raise InvalidRequestException(f"You aren't the host of lobby {lobby_id}. Only the lobby host can update the lobby")

            # Prevent updating the lobby if the match has been initiated
            if _lobby_match_initiated(lobby):
                log.warning(f"Player '{player_id}' attempted to update lobby '{lobby_id}' which has initiated the lobby match")
                raise InvalidRequestException(f"Cannot update the lobby after the lobby match has been initiated")

            lobby_updated = False

            if team_capacity is not None:
                old_team_capacity = lobby["team_capacity"]

                if old_team_capacity != team_capacity:
                    lobby_updated = True
                    log.info(f"Host player '{player_id}' changed team capacity from '{old_team_capacity}' to '{team_capacity}' for lobby '{lobby_id}'")
                    lobby["team_capacity"] = team_capacity

                    # Go over members and enforce new team capacity
                    team_counts = defaultdict(int)
                    for member in lobby["members"]:
                        team_name = member["team_name"]
                        if team_name is not None:
                            current_team_count = team_counts[team_name]

                            if current_team_count < team_capacity:
                                team_counts[team_name] += 1
                            else:
                                log.info(f"Player '{player_id}' removed from team '{team_name}' due to team being over capacity in lobby '{lobby_id}'")
                                member["team_name"] = None

            if team_names:
                old_team_names = lobby["team_names"]

                if old_team_names != team_names:
                    lobby_updated = True
                    log.info(f"Host player '{player_id}' changed team names from '{old_team_names}' to '{team_names}' for lobby '{lobby_id}'")
                    lobby["team_names"] = team_names

                    # Go over members and enforce new team names
                    for member in lobby["members"]:
                        team_name = member["team_name"]
                        if team_name and team_name not in team_names:
                            log.info(f"Player '{player_id}' removed from team '{team_name}' due to now being an invalid team in lobby '{lobby_id}'")
                            member["team_name"] = None

            if lobby_name:
                old_lobby_name = lobby["lobby_name"]

                if old_lobby_name != lobby_name:
                    lobby_updated = True
                    log.info(f"Host player '{player_id}' changed lobby name from '{old_lobby_name}' to '{lobby_name}' for lobby '{lobby_id}'")
                    lobby["lobby_name"] = lobby_name

            if map_name:
                old_map_name = lobby["map_name"]

                if old_map_name != map_name:
                    lobby_updated = True
                    log.info(f"Host player '{player_id}' changed map name from '{old_map_name}' to '{map_name}' for lobby '{lobby_id}'")
                    lobby["map_name"] = map_name

            if custom_data:
                old_custom_data = lobby["custom_data"]

                if old_custom_data != custom_data:
                    lobby_updated = True
                    log.info(f"Host player '{player_id}' changed custom data from '{old_custom_data}' to '{custom_data}' for lobby '{lobby_id}'")
                    lobby["custom_data"] = custom_data

            if lobby_updated:
                lobby_lock.lobby = lobby

                # Notify members
                receiving_player_ids = _get_lobby_member_player_ids(lobby)
                _post_lobby_event_to_members(receiving_player_ids, "LobbyUpdated", lobby)

def delete_lobby(player_id: int, expected_lobby_id: str):
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        lobby_id = player_lobby_lock.value

        if not lobby_id:
            log.info(f"Player '{player_id}' attempted to delete a lobby without being a member of any lobby")
            raise UnauthorizedException(f"You don't have permission to access lobby {expected_lobby_id}")

        if expected_lobby_id != lobby_id:
            log.warning(f"Player '{player_id}' attempted to delete lobby '{expected_lobby_id}', but isn't a member of that lobby. Player is in lobby '{lobby_id}'")
            raise UnauthorizedException(f"You don't have permission to access lobby {expected_lobby_id}")

        _internal_delete_lobby(player_id, lobby_id)

        player_lobby_lock.value = None

def leave_lobby(player_id: int, expected_lobby_id: str):
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        lobby_id = player_lobby_lock.value

        if not lobby_id:
            log.info(f"Player '{player_id}' attempted to leave a lobby without being a member of any lobby")
            raise UnauthorizedException(f"You don't have permission to access lobby {expected_lobby_id}")

        if expected_lobby_id != lobby_id:
            log.warning(f"Player '{player_id}' attempted to leave lobby '{expected_lobby_id}', but isn't a member of that lobby. Player is in lobby '{lobby_id}'")
            raise UnauthorizedException(f"You don't have permission to access lobby {expected_lobby_id}")

        _internal_leave_lobby(player_id, lobby_id)

        player_lobby_lock.value = None

def join_lobby(player_id: int, lobby_id: str):
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        player_lobby_id = player_lobby_lock.value

        # Already a part of another lobby
        if player_lobby_id and player_lobby_id != lobby_id:
            log.info(f"Player '{player_id}' is joining lobby '{lobby_id}' while being a member of lobby '{player_lobby_id}'")
            try:
                _internal_leave_lobby(player_id, player_lobby_id)
            except NotFoundException:
                pass

        lobby = _internal_join_lobby(player_id, lobby_id)

        player_lobby_lock.value = lobby_id

        return lobby

def update_lobby_member(player_id: int, member_id: int, lobby_id: str, team_name: typing.Optional[str], ready: typing.Optional[bool]):
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        player_lobby_id = player_lobby_lock.value

        if player_lobby_id != lobby_id:
            log.warning(f"Player '{player_id}' attempted to update member '{member_id}' in lobby '{lobby_id}' without being in the lobby")
            raise UnauthorizedException(f"You don't have permission to access lobby {lobby_id}")

        with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
            lobby = lobby_lock.lobby

            if player_id != member_id:
                host_player_id = _get_lobby_host_player_id(lobby)

                if player_id != host_player_id:
                    log.warning(f"Player '{player_id}' attempted to update member '{member_id}' in lobby '{lobby_id}' without being a the lobby host")
                    raise InvalidRequestException(f"You aren't the host of lobby {lobby_id}. Only the lobby host can update other members")

                log.info(f"Host player '{player_id}' is updating member '{member_id}' in lobby '{lobby_id}'")

            # Prevent updating lobby member if the lobby match has been initiated
            if _lobby_match_initiated(lobby):
                log.warning(f"Player '{player_id}' attempted to update member '{member_id}' in lobby '{lobby_id}' which has initiated the lobby match")
                raise InvalidRequestException(f"Cannot update lobby after the lobby match has been initialized")

            member_updated = False

            for member in lobby["members"]:
                if member["player_id"] != member_id:
                    continue

                current_team = member["team_name"]

                if team_name and team_name not in lobby["team_names"]:
                    log.warning(f"Player '{player_id}' attempted to update member '{member_id}' in lobby '{lobby_id}' with invalid team name '{team_name}'")
                    raise InvalidRequestException(f"Team name '{team_name}' is invalid")

                if current_team and team_name != current_team:
                    log.info(f"Player '{player_id}' in lobby '{lobby_id}' left team '{current_team}'")
                    member_updated = True
                    ready = False

                if team_name and team_name != current_team and _can_join_team(lobby, team_name):
                    log.info(f"Player '{player_id}' in lobby '{lobby_id}' joined team '{team_name}'")
                    member_updated = True
                    ready = False

                if not team_name:
                    ready = False

                member["team_name"] = team_name

                if ready != member["ready"]:
                    member_updated = True
                    log.info(f"Player '{player_id}' in lobby '{lobby_id}' updated ready status to '{ready}'")

                member["ready"] = bool(ready)
                break

            if member_updated:
                lobby_lock.lobby = lobby

                # Notify members
                receiving_player_ids = _get_lobby_member_player_ids(lobby)
                _post_lobby_event_to_members(receiving_player_ids, "LobbyMemberUpdated", {"lobby_id": lobby_id, "members": lobby["members"]})

def kick_member(player_id: int, member_id: int, lobby_id: str):
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        player_lobby_id = player_lobby_lock.value

        if player_lobby_id != lobby_id:
            log.warning(f"Player '{player_id}' attempted to kick member '{member_id}' in lobby '{lobby_id}' without being in the lobby")
            raise UnauthorizedException(f"You don't have permission to access lobby {lobby_id}")

        if player_id == member_id:
            log.info(f"Player '{player_id}' is kicking themselves from the lobby '{lobby_id}'")
            try:
                _internal_leave_lobby(player_id, lobby_id)
            except NotFoundException:
                pass
            player_lobby_lock.value = None
            return

        with _GenericLock(_get_player_lobby_key(member_id)) as member_lobby_lock:
            member_lobby_id = member_lobby_lock.value

            if member_lobby_id != player_lobby_id:
                log.warning(f"Player '{player_id}' attempted to kick player '{member_id}' from lobby '{lobby_id}', but they aren't in the same lobby")
                raise InvalidRequestException(f"You and player {member_id} aren't in the same lobby")

            with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
                lobby = lobby_lock.lobby

                if not lobby:
                    raise RuntimeError(f"Player '{player_id}' attempted to kick player '{member_id}' from lobby '{lobby_id}' which doesn't exist")

                host_player_id = _get_lobby_host_player_id(lobby)

                if player_id != host_player_id:
                    log.warning(f"Player '{player_id}' attempted to kick member '{member_id}' from lobby '{lobby_id}' without being the lobby host")
                    raise InvalidRequestException(f"You aren't the host of lobby {lobby_id}. Only the lobby host can kick other members")

                current_length = len(lobby["members"])

                # Populate receiving player ids for message before kicking the player
                receiving_player_ids = _get_lobby_member_player_ids(lobby)

                # Remove player from members list
                lobby["members"] = [member for member in lobby["members"] if member["player_id"] != member_id]

                kicked = len(lobby["members"]) != current_length

                if kicked:
                    log.info(f"Host player '{player_id}' kicked member player '{member_id}' from lobby '{lobby_id}'")

                    member_lobby_lock.value = None
                    lobby_lock.lobby = lobby

                    # Notify members and kicked player
                    _post_lobby_event_to_members(receiving_player_ids, "LobbyMemberKicked", {"lobby_id": lobby_id, "kicked_player_id": member_id, "members": lobby["members"]})
                else:
                    log.warning(f"Host player '{player_id}' tried to kick member player '{member_id}' from lobby '{lobby_id}', but '{member_id}' wasn't a member of the lobby")

                    if member_lobby_id == lobby_id:
                        log.warning(f"Player '{member_id}' is supposed to be in lobby '{lobby_id}' but isn't a member of the lobby")
                        member_lobby_lock.value = None

# Helpers

def _internal_join_lobby(player_id: int, lobby_id: str) -> dict:
    player_name: str = g.db.query(CorePlayer.player_name).filter(CorePlayer.player_id == player_id).first().player_name

    with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
        lobby = lobby_lock.lobby

        if not lobby:
            log.warning(f"Player '{player_id}' attempted to join lobby '{lobby_id}' which doesn't exist")
            raise NotFoundException(f"Lobby {lobby_id} doesn't exist")

        if not _get_lobby_member(lobby, player_id):
            lobby["members"].append({
                "player_id": player_id,
                "player_name": player_name,
                "team_name": None,
                "ready": False,
                "host": False,
                "join_date": datetime.datetime.utcnow().isoformat(),
            })

            lobby_lock.lobby = lobby

            log.info(f"Player '{player_id}' joined lobby '{lobby_id}'")

            # Notify members
            receiving_player_ids = _get_lobby_member_player_ids(lobby, [player_id])
            _post_lobby_event_to_members(receiving_player_ids, "LobbyMemberJoined", {"lobby_id": lobby_id, "members": lobby["members"]})
        else:
            log.info(f"Player '{player_id}' attempted to join lobby '{lobby_id}' while already being a member")

        return _get_personalized_lobby(lobby, player_id)

def _get_personalized_lobby(lobby: dict, player_id: int) -> dict:
    # Add personalized connection options if the match has started
    if _lobby_match_initiated(lobby) and lobby.get("connection_string", None):
        # TODO: Think about where this code should reside since it's match and GameLift specific

        player_lobby = copy.deepcopy(lobby)

        # Default to spectator
        connection_options = "SpectatorOnly=1"

        member = _get_lobby_member(lobby, player_id)

        if member["team_name"]:
            # Player is a part of a team. Ensure the player has a player session
            player_session_id = _ensure_player_session(lobby, player_id, member)
            if player_session_id:
                connection_options = f"PlayerSessionId={player_session_id}?PlayerId={player_id}"

        player_lobby["connection_options"] = connection_options
        return player_lobby

    return lobby

def _ensure_player_session(lobby: dict, player_id: int, member: dict) -> typing.Optional[str]:
    from driftbase import match_placements

    lobby_id = lobby["lobby_id"]
    placement_id = lobby.get("placement_id", None)

    if not placement_id:
        raise RuntimeError(f"Failed to ensure player session for player '{player_id}' in lobby '{lobby_id}'. Lobby has no placement id")

    with match_placements._JsonLock(match_placements._get_match_placement_key(placement_id)) as match_placement_lock:
        placement = match_placement_lock.value

        if not placement:
            raise RuntimeError(f"Failed to ensure player session for player '{player_id}' in lobby '{lobby_id}'. No placement exists for placement id '{placement_id}'")

        game_session_arn = placement.get("game_session_arn", None)

        if not game_session_arn:
            raise RuntimeError(f"Failed to ensure player session for player '{player_id}' in lobby '{lobby_id}'. No game session arn exists for placement id '{placement_id}'")

        # Check if the game session is still valid
        game_sessions = flexmatch.describe_game_sessions(GameSessionId=game_session_arn)
        if len(game_sessions["GameSessions"]) == 0:
            log.warning(f"Unable to ensure a player session for player '{player_id}' in lobby '{lobby_id}'. Game session '{game_session_arn}' not found. Assuming the game session has been deleted/cleaned up")
            return None

        game_session = game_sessions["GameSessions"][0]
        game_session_status = game_session["Status"]
        if game_session_status not in ("ACTIVE", "ACTIVATING"):
            log.warning(f"Unable to ensure a player session for player '{player_id}' in lobby '{lobby_id}'. Game session '{game_session_arn}' is in status '{game_session_status}'")
            return None

        # Check if player has a valid player session
        player_sessions = flexmatch.describe_player_sessions(GameSessionId=game_session_arn)
        for player_session in player_sessions["PlayerSessions"]:
            if player_session["PlayerId"] == str(player_id) and player_session["Status"] in ("RESERVED", "ACTIVE"):
                return player_session["PlayerSessionId"]

        # Create new player session since no valid one was found
        response = flexmatch.create_player_session(
            GameSessionId=game_session_arn,
            PlayerId=str(player_id),
            PlayerData=json.dumps({
                "player_name": member["player_name"],
                "team_name": member["team_name"],
                "host": member["host"],
            }),
        )

        return response["PlayerSession"]["PlayerSessionId"]

def _internal_leave_lobby(player_id: int, lobby_id: str):
    """
    Caller is responsible for handling the player lobby id lock value
    """
    with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
        lobby = lobby_lock.lobby

        if not lobby:
            log.warning(f"Player '{player_id}' attempted to leave lobby '{lobby_id}' which doesn't exist")
            raise NotFoundException(f"Lobby {lobby_id} doesn't exist")

        if lobby["status"] == "starting":
            placement_date = datetime.datetime.fromisoformat(lobby["placement_date"])
            now = datetime.datetime.utcnow()

            duration = (now - placement_date).total_seconds()
            leave_lock_duration = _get_tenant_config_value("lobby_match_starting_leave_lock_duration_seconds")

            if duration > leave_lock_duration:
                log.warning(f"Player '{player_id}' is leaving lobby '{lobby_id}' which has been starting the lobby match for '{duration}' seconds. Configured leave lock duration is '{leave_lock_duration}'. Allowing the player to leave. Lobby may be borked")
            else:
                log.warning(f"Player '{player_id}' attempted to leave lobby '{lobby_id}' while the lobby match is starting")
                raise InvalidRequestException(f"Cannot leave the lobby while the lobby match is starting. You can leave after {leave_lock_duration - duration} seconds")

        current_length = len(lobby["members"])
        host_player_id = _get_lobby_host_player_id(lobby)

        # Populate receiving player ids before removing player
        receiving_player_ids = _get_lobby_member_player_ids(lobby)

        # Remove player from members list
        lobby["members"] = [member for member in lobby["members"] if member["player_id"] != player_id]

        left = len(lobby["members"]) != current_length

        if left:
            log.info(f"Lobby member player '{player_id}' left lobby '{lobby_id}'")

            if lobby["members"]:
                # Promote new host if the host left

                if host_player_id == player_id:
                    # Host left the lobby, select the oldest member as host

                    sorted_members = sorted(lobby["members"], key=lambda m: datetime.datetime.fromisoformat(m["join_date"]))
                    sorted_members[0]["host"] = True

                    new_host_player_id = sorted_members[0]["player_id"]

                    log.info(f"Player {new_host_player_id} promoted to lobby host for lobby '{lobby_id}'")

                    lobby["members"] = sorted_members

                lobby_lock.lobby = lobby

                # Notify remaining members
                _post_lobby_event_to_members(receiving_player_ids, "LobbyMemberLeft", {"lobby_id": lobby_id, "left_player_id": player_id, "members": lobby["members"]})
            else:
                # No one left in the lobby, delete the lobby

                log.info(f"No one left in lobby '{lobby_id}'. Lobby deleted.")

                lobby_lock.lobby = None
        else:
            log.error(f"Lobby member player '{player_id}' attempted to leave lobby '{lobby_id}' without being a member")

def _internal_delete_lobby(player_id: int, lobby_id: str):
    """
    Caller is responsible for handling the player lobby id lock value
    """
    with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
        lobby = lobby_lock.lobby

        if not lobby:
            log.warning(f"Player '{player_id}' attempted to delete lobby '{lobby_id}' which doesn't exist")
            return

        host_player_id = _get_lobby_host_player_id(lobby)

        if host_player_id != player_id:
            log.warning(f"Player '{player_id}' attempted to delete lobby '{lobby_id}' without being the host")
            raise InvalidRequestException(f"You aren't the host of lobby {lobby_id}. Only the lobby host can delete the lobby")

        log.info(f"Lobby host player '{player_id}' deleted lobby '{lobby_id}'")

        for member in lobby["members"]:
            if not member["host"]:
                with _GenericLock(_get_player_lobby_key(member["player_id"])) as member_lobby_id_lock:
                    member_lobby_id_lock.value = None

        # Delete the lobby
        lobby_lock.lobby = None

        # Notify members
        receiving_player_ids = _get_lobby_member_player_ids(lobby, [player_id])
        if receiving_player_ids: # Potentially empty if the host is alone in the lobby
            _post_lobby_event_to_members(receiving_player_ids, "LobbyDeleted", {"lobby_id": lobby_id})

def _lobby_match_initiated(lobby: dict) -> bool:
    return lobby["status"] in ("starting", "started")

def _can_join_team(lobby: dict, team: str) -> bool:
    team_count = 0
    team_capacity = lobby["team_capacity"]
    for member in lobby["members"]:
        team_name = member["team_name"]
        if team_name == team:
            team_count += 1

    return team_count < team_capacity

def _get_lobby_member(lobby: dict, player_id: int) -> typing.Optional[dict]:
    return next((member for member in lobby["members"] if member["player_id"] == player_id), None)

def _generate_lobby_id() -> str:
    lobby_id_length = _get_tenant_config_value("lobby_id_length")
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=lobby_id_length))

def _get_lobby_key(lobby_id: str) -> str:
    return g.redis.make_key(f"lobby:{lobby_id}:")

def _get_player_lobby_key(player_id: int) -> str:
    return g.redis.make_key(f"player:{player_id}:lobby:")

def _get_lobby_host_player_id(lobby: dict) -> int:
    for member in lobby["members"]:
        if member["host"]:
            return member["player_id"]

    return 0

def _get_lobby_member_player_ids(lobby: dict, exclude_player_ids: list[int] = []) -> list[int]:
    return [member["player_id"] for member in lobby["members"] if member["player_id"] not in exclude_player_ids]

def _get_tenant_config_value(config_key):
    default_value = TIER_DEFAULTS.get(config_key, None)
    tenant = g.conf.tenant
    if tenant:
        return g.conf.tenant.get("lobbies", {}).get(config_key, default_value)
    return default_value

def _get_tenant_name():
    return g.conf.tenant.get('tenant_name')

def _post_lobby_event_to_members(receiving_player_ids: list[int], event: str, event_data: typing.Optional[dict] = None, expiry: typing.Optional[int] = None):
    """ Insert an event into the 'lobby' queue of the 'players' exchange. """
    log.info(f"Posting '{event}' to players '{receiving_player_ids}' with event_data '{event_data}'")

    if not receiving_player_ids:
        log.warning(f"Empty receiver in lobby event '{event}' message")
        return

    payload = {
        "event": event,
        "data": event_data or {}
    }

    for receiver_id in receiving_player_ids:
        post_message("players", int(receiver_id), "lobby", payload, expiry, sender_system=True)

# TODO: Figure out if _GenericLock is redundant and just use with g.redis.conn.lock(key) directly
class _GenericLock(object):
    """
    Context manager for synchronizing creation and modification of a redis value.
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
        self._value = self._redis.conn.get(self._key)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._lock.owned():  # If we don't own the lock at this point, we don't want to update anything
            with self._redis.conn.pipeline() as pipe:
                if self._modified is True and exc_type is None:
                    pipe.delete(self._key)  # Always update the lobby wholesale, i.e. don't leave stale fields behind.
                    if self._value:
                        pipe.set(self._key, str(self._value), ex=self.TTL_SECONDS)
                pipe.execute()
            self._lock.release()

class _LockedLobby(object):
    """
    Context manager for synchronizing creation and modification of lobbies.
    """
    MAX_LOCK_WAIT_TIME_SECONDS = 30
    TTL_SECONDS = 60 * 60 * 24

    def __init__(self, key):
        self._key = key
        self._redis = g.redis
        self._modified = False
        self._lobby = None
        self._lock = g.redis.conn.lock(self._key + "LOCK", timeout=self.MAX_LOCK_WAIT_TIME_SECONDS)

    @property
    def lobby(self):
        return self._lobby

    @lobby.setter
    def lobby(self, new_lobby):
        self._lobby = new_lobby
        self._modified = True

    def __enter__(self):
        self._lock.acquire(blocking=True)
        lobby = self._redis.conn.get(self._key)
        if lobby is not None:
            lobby = json.loads(lobby)
            self._lobby = lobby
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._lock.owned():  # If we don't own the lock at this point, we don't want to update anything
            with self._redis.conn.pipeline() as pipe:
                if self._modified is True and exc_type is None:
                    pipe.delete(self._key)  # Always update the lobby wholesale, i.e. don't leave stale fields behind.
                    if self._lobby:
                        pipe.set(self._key, json.dumps(self._lobby, default=self._json_serial), ex=self.TTL_SECONDS)
                pipe.execute()
            self._lock.release()

    @staticmethod
    def _json_serial(obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()

        raise TypeError(f"Type {type(obj)} not serializable")

class InvalidRequestException(Exception):
    def __init__(self, user_message):
        super().__init__(user_message)
        self.msg = user_message

class NotFoundException(Exception):
    def __init__(self, user_message):
        super().__init__(user_message)
        self.msg = user_message

class UnauthorizedException(Exception):
    def __init__(self, user_message):
        super().__init__(user_message)
        self.msg = user_message
