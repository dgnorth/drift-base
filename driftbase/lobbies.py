import copy
import logging
import boto3
import json
import typing
import random
import string
import datetime
import enum
from botocore.exceptions import ClientError, ParamValidationError
from flask import g
from aws_assume_role_lib import assume_role
from driftbase.parties import get_player_party
from driftbase.models.db import CorePlayer
from driftbase.messages import post_message
from driftbase import flexmatch

from driftbase.resources.lobbies import TIER_DEFAULTS

# FIXME: Figure out how to do multi-region matchmaking; afaik, the configuration isn't region based, but both queues and
#  events are. The queues themselves can have destination fleets in multiple regions.
AWS_REGION = "eu-west-1"

log = logging.getLogger(__name__)

def get_player_lobby(player_id: int):
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        with _LockedLobby(_get_lobby_key(player_lobby_lock.value)) as lobby_lock:
            log.info(f"Returning lobby {player_lobby_lock.value} for player {player_id}")

            # Sanity check that the player is a member of the lobby
            if lobby_lock.lobby and not next((member for member in lobby_lock.lobby["members"] if member["player_id"] == player_id), None):
                log.error(f"Player {player_id} is supposed to be in lobby {player_lobby_lock.value} but isn't a member of the lobby")

            return lobby_lock.lobby

def create_lobby(player_id: int, team_capacity: int, team_names: list[str], lobby_name: typing.Optional[str], map_name: typing.Optional[str]):
    if get_player_party(player_id) is not None:
        raise InvalidRequestException(f"Failed to create lobby for player {player_id} due to player being in a party")

    matchmaking_ticket = flexmatch.get_player_ticket(player_id)
    if matchmaking_ticket and matchmaking_ticket["Status"] not in ("MATCH_COMPLETED", "FAILED", "TIMED_OUT", "", None):
        raise InvalidRequestException(f"Failed to create lobby for player {player_id} due to player having an active matchmaking ticket")

    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        # Leave/delete existing lobby if any
        if player_lobby_lock.value:
            log.info(f"Player {player_id} is creating a lobby while being a member of lobby {player_lobby_lock.value}")
            _internal_delete_or_leave_lobby(player_id, player_lobby_lock.value)
            player_lobby_lock.value = None

        player_name: str = g.db.query(CorePlayer.player_name).filter(CorePlayer.player_id == player_id).first().player_name

        while True:
            lobby_id = _generate_lobby_id()

            with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
                if lobby_lock.lobby is not None:
                    log.info(f"Generated an existing lobby id. That's very unlucky (or lucky). Retrying...")
                else:
                    log.info(f"Creating lobby {lobby_id} for player {player_id}")

                    new_lobby = {
                        "lobby_id": lobby_id,
                        "lobby_name": lobby_name if lobby_name is not None else _get_tenant_config_value("default_lobby_name"),
                        "map_name": map_name,
                        "team_capacity": team_capacity,
                        "team_names": team_names,
                        "create_date": str(datetime.datetime.utcnow()),
                        "start_date": None,
                        "status": "idle",
                        "members": [
                            {
                                "player_id": player_id,
                                "player_name": player_name,
                                "team": None,
                                "ready": False,
                                "host": True,
                            }
                        ],
                    }

                    player_lobby_lock.value = lobby_id
                    lobby_lock.lobby = new_lobby
                    return new_lobby

def update_lobby(player_id: int, team_capacity: typing.Optional[int], team_names: list[str], lobby_name: typing.Optional[str], map_name: typing.Optional[str]):
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        lobby_id = player_lobby_lock.value

        if not lobby_id:
            raise NotFoundException(f"Player {player_id} attempted to update a lobby without being a member of any lobby")

        with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
            lobby = lobby_lock.lobby

            if not lobby:
                raise RuntimeError(f"Player {player_id} attempted to update lobby {lobby_id} which doesn't exist")

            host_player_id = _get_lobby_host_player_id(lobby)

            if host_player_id != player_id:
                raise InvalidRequestException(f"Player {player_id} attempted to update a lobby without being the lobby host")

            lobby_updated = False

            if team_capacity is not None:
                old_team_capacity = lobby["team_capacity"]

                if old_team_capacity != team_capacity:
                    lobby_updated = True
                    log.info(f"Host player {player_id} changed team capacity from {old_team_capacity} to {team_capacity} for lobby {lobby_id}")
                    lobby["team_capacity"] = team_capacity

                    # Go over members and enforce new team capacity
                    team_counts = {}
                    for member in lobby["members"]:
                        team_name = member["team"]
                        if team_name is not None:
                            if team_name not in team_counts:
                                team_counts[team_name] = 0

                            current_team_count = team_counts[team_name]

                            if current_team_count < team_capacity:
                                team_counts[team_name] += 1
                            else:
                                log.info(f"Player {player_id} removed from team {team_name} due to team being over capacity in lobby {lobby_id}")
                                member["team"] = None

            if team_names:
                old_team_names= lobby["team_names"]

                if old_team_names != team_names:
                    lobby_updated = True
                    log.info(f"Host player {player_id} changed team names from {old_team_names} to {team_names} for lobby {lobby_id}")
                    lobby["team_names"] = team_names

                    # Go over members and enforce new team names
                    for member in lobby["members"]:
                        team_name = member["team"]
                        if team_name and team_name not in team_names:
                            log.info(f"Player {player_id} removed from team {team_name} due to now being an invalid team in lobby {lobby_id}")
                            member["team"] = None

            if lobby_name:
                old_lobby_name = lobby["lobby_name"]

                if old_lobby_name != lobby_name:
                    lobby_updated = True
                    log.info(f"Host player {player_id} changed lobby name from {old_lobby_name} to {lobby_name} for lobby {lobby_id}")
                    lobby["lobby_name"] = lobby_name

            if map_name:
                old_map_name = lobby["map_name"]

                if old_map_name != map_name:
                    lobby_updated = True
                    log.info(f"Host player {player_id} changed map name from {old_map_name} to {map_name} for lobby {lobby_id}")
                    lobby["map_name"] = map_name

            if lobby_updated:
                lobby_lock.lobby = lobby

                # Notify members
                receiving_player_ids = _get_lobby_member_player_ids(lobby)
                _post_lobby_event_to_members(receiving_player_ids, "LobbyUpdated", lobby)

def delete_or_leave_lobby(player_id: int):
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        lobby_id = player_lobby_lock.value

        if not lobby_id:
            log.info(f"Player {player_id} attempted to leave a lobby without being a member of any lobby")
            return

        _internal_delete_or_leave_lobby(player_id, lobby_id)

        player_lobby_lock.value = None

def join_lobby(player_id: int, lobby_id: str):
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        # Already a part of another lobby
        if player_lobby_lock.value and player_lobby_lock.value != lobby_id:
            log.info(f"Player {player_id} is joining lobby {lobby_id} while being a member of lobby {player_lobby_lock.value}")
            _internal_delete_or_leave_lobby(player_id, lobby_id)
            player_lobby_lock.value = None

        lobby = _internal_join_lobby(player_id, lobby_id)

        player_lobby_lock.value = lobby_id

        return lobby

def update_lobby_member(player_id: int, member_id: int, lobby_id: str, team: typing.Optional[str], ready: typing.Optional[bool]):
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        player_lobby_id = player_lobby_lock.value

        with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
            lobby = lobby_lock.lobby

            if player_id != member_id:
                host_player_id = _get_lobby_host_player_id(lobby_id)

                if player_id != host_player_id:
                    raise InvalidRequestException(f"Player {player_id} attempted to update member {member_id} in lobby {lobby_id} without being a the lobby host")

                # TODO: Support updating other member's info as the host
                raise InvalidRequestException(f"The host updating other member's info not supported")

            member_updated = False

            for member in lobby["members"]:
                if member["player_id"] != member_id:
                    continue

                current_team = member["team"]

                if team and team not in lobby["team_names"]:
                    raise InvalidRequestException(f"Player {player_id} attempted to join invalid team {team}")

                if current_team and team != current_team:
                    member_updated = True
                    log.info(f"Player {player_id} in lobby {lobby_id} left team {current_team}")

                if team and team != current_team and _can_join_team(lobby, team):
                    member_updated = True
                    log.info(f"Player {player_id} in lobby {lobby_id} joined team {team}")

                member["team"] = team

                if ready != member["ready"]:
                    member_updated = True
                    log.info(f"Player {player_id} in lobby {lobby_id} updated ready status to {ready}")

                member["ready"] = ready
                break

            if member_updated:
                lobby_lock.lobby = lobby

                # Notify members
                receiving_player_ids = _get_lobby_member_player_ids(lobby)
                _post_lobby_event_to_members(receiving_player_ids, "LobbyMemberUpdated", {"lobby_id": lobby_id, "members": lobby["members"]})

def kick_member(player_id: int, member_id: int, lobby_id: str):
    with _GenericLock(_get_player_lobby_key(player_id)) as player_lobby_lock:
        player_lobby_id = player_lobby_lock.value

        if player_id == member_id:
            if lobby_id == player_lobby_id:
                log.info(f"Player {player_id} is kicking themselves from the lobby {lobby_id}")
                _internal_delete_or_leave_lobby(player_id, lobby_id)
                return
            else:
                raise InvalidRequestException(f"Player {player_id} attempted to kick themselves from lobby {lobby_id} without being a member of the lobby")

        with _GenericLock(_get_player_lobby_key(member_id)) as member_lobby_lock:
            member_lobby_id = member_lobby_lock.value

            with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
                lobby = lobby_lock.lobby

                if not lobby:
                    raise NotFoundException(f"Player {player_id} attempted to kick player {member_id} from lobby {lobby_id} which doesn't exist")

                host_player_id = _get_lobby_host_player_id(lobby)

                if player_id != host_player_id:
                    raise InvalidRequestException(f"Player {player_id} attempted to kick member {member_id} from lobby {lobby_id} without being a the lobby host")

                if player_lobby_id != lobby_id:
                    log.warning(f"Player {player_id} is supposed to be the host of lobby {lobby_id}, but is in lobby {player_lobby_id}")

                current_length = len(lobby["members"])

                # Remove player from members list
                lobby["members"] = [member for member in lobby["members"] if member["player_id"] != member_id]

                kicked = len(lobby["members"]) != current_length

                if kicked:
                    log.info(f"Host player {player_id} kicked member player {member_id} from lobby {lobby_id}")

                    member_lobby_lock.value = None
                    lobby_lock.lobby = lobby

                    if member_lobby_id != lobby_id:
                        log.warning(f"Player {member_id} was kicked from lobby {lobby_id}, but was supposed to be in lobby {member_lobby_id}")

                    # Notify members
                    receiving_player_ids = _get_lobby_member_player_ids(lobby)
                    _post_lobby_event_to_members(receiving_player_ids, "LobbyMemberKicked", {"lobby_id": lobby_id, "members": lobby["members"]})
                else:
                    log.warning(f"Host player {player_id} tried to kick member player {member_id} from lobby {lobby_id}, but {member_id} wasn't a member of the lobby")

                    if member_lobby_id == lobby_id:
                        log.warning(f"Player {member_id} is supposed to be in lobby {lobby_id} but isn't a member of the lobby")
                        member_lobby_lock.value = None

def start_lobby_match(player_id: int, lobby_id: str):
    raise InvalidRequestException(f"Starting a lobby match not yet implemented")

# Helpers

def _internal_join_lobby(player_id: int, lobby_id: str):
    player_name: str = g.db.query(CorePlayer.player_name).filter(CorePlayer.player_id == player_id).first().player_name

    with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
        lobby = lobby_lock.lobby

        if not lobby:
            raise NotFoundException(f"Player {player_id} attempted to join lobby {lobby_id} which doesn't exist")

        if not next((member for member in lobby["members"] if member["player_id"] == player_id), None):
            lobby["members"].append(
                {
                    "player_id": player_id,
                    "player_name": player_name,
                    "team": None,
                    "ready": False,
                    "host": False,
                }
            )

            lobby_lock.lobby = lobby

            log.info(f"Player {player_id} joined lobby {lobby_id}")

            # Notify members
            receiving_player_ids = _get_lobby_member_player_ids(lobby, [player_id])
            _post_lobby_event_to_members(receiving_player_ids, "LobbyMemberJoined", {"lobby_id": lobby_id, "members": lobby["members"]})
        else:
            log.info(f"Player {player_id} attempted to join lobby {lobby_id} while already being a member")

        return lobby_lock.lobby

def _internal_delete_or_leave_lobby(player_id: int, lobby_id: str):
    """
    Caller is responsible for handling the player lobby id lock value
    """
    with _LockedLobby(_get_lobby_key(lobby_id)) as lobby_lock:
        lobby = lobby_lock.lobby

        if lobby:
            host_player_id = _get_lobby_host_player_id(lobby)

            if host_player_id == player_id:
                # Host is deleting the lobby

                log.info(f"Lobby host player {player_id} deleted lobby {lobby_id}")

                for member in lobby["members"]:
                    if not member["host"]:
                        with _GenericLock(_get_player_lobby_key(member["player_id"])) as member_lobby_id_lock:
                            member_lobby_id_lock.value = None

                # Delete the lobby
                lobby_lock.lobby = None

                # Notify members
                receiving_player_ids = _get_lobby_member_player_ids(lobby)
                _post_lobby_event_to_members(receiving_player_ids, "LobbyDeleted")
            else:
                # Member is leaving the lobby

                current_length = len(lobby["members"])

                # Remove player from members list
                lobby["members"] = [member for member in lobby["members"] if member["player_id"] != player_id]

                left = len(lobby["members"]) != current_length

                if left:
                    log.info(f"Lobby member player {player_id} left lobby {lobby_id}")

                    lobby_lock.lobby = lobby

                    # Notify remaining members
                    receiving_player_ids = _get_lobby_member_player_ids(lobby)
                    _post_lobby_event_to_members(receiving_player_ids, "LobbyMemberLeft", {"lobby_id": lobby_id, "members": lobby["members"]})
                else:
                    log.error(f"Lobby member player {player_id} attempted to leave lobby {lobby_id} without being a member")
        else:
            log.info(f"Player {player_id} attempted to leave lobby {lobby_id} which doesn't exist")

def _can_join_team(lobby: dict, team: str) -> bool:
    team_count = 0
    team_capacity = lobby["team_capacity"]
    for member in lobby["members"]:
        team_name = member["team"]
        if team_name == team:
            team_count += 1

    return team_count < team_capacity

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

def _get_lobby_member_player_ids(lobby: dict, exclude_player_ids: list[int]) -> list[int]:
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
    log.info(f"Posting '{event}' to players {receiving_player_ids} with event_data {event_data}")

    if not receiving_player_ids:
        log.warning(f"Empty receiver in lobby event {event} message")
        return

    payload = {
        "event": event,
        "data": event_data or {}
    }

    for receiver_id in receiving_player_ids:
        post_message("players", int(receiver_id), "lobby", payload, expiry, sender_system=True)

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
                        pipe.set(self._key, json.dumps(self._lobby), ex=self.TTL_SECONDS)
                pipe.execute()
            self._lock.release()

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
    def value(self, new_lobby):
        self._value = new_lobby
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


class InvalidRequestException(Exception):
    def __init__(self, user_message):
        super().__init__(user_message)
        self.msg = user_message

class NotFoundException(Exception):
    def __init__(self, user_message):
        super().__init__(user_message)
        self.msg = user_message

class GameliftClientException(Exception):
    def __init__(self, user_message, debug_info):
        super().__init__(user_message, debug_info)
        self.msg = user_message
        self.debugs = debug_info
