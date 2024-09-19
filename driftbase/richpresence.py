from __future__ import annotations
from marshmallow import Schema, fields
from marshmallow.decorators import post_load
from driftbase.messages import post_message
from driftbase.utils.exceptions import NotFoundException, ForbiddenException
from driftbase.models.db import Friendship, CorePlayer
from sqlalchemy.orm import Session
from drift.core.resources.redis import RedisCache
import logging

log = logging.getLogger(__name__)

class PlayerRichPresence:
    """
    Rich presence information for a particular player.
    @see PlayerRichPresenceSchema
    """

    def __init__(self, player_id: int, is_online: bool = False, is_in_game: bool = False, game_mode: str = "", map_name: str = ""):
        self.player_id = player_id
        self.is_online = is_online
        self.is_in_game = is_in_game
        self.game_mode = game_mode
        self.map_name = map_name

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            result = self.__dict__ == other.__dict__
            return result
        else:
            return False
    
class RichPresenceSchema(Schema):
    player_id = fields.Int()
    is_online = fields.Bool()
    is_in_game = fields.Bool()
    game_mode = fields.Str()
    map_name = fields.Str()

    @post_load
    def make_rich_presence(self, data, **kwargs):
        return PlayerRichPresence(**data)

class RichPresenceService():
    def __init__(self, db_session: Session, redis: RedisCache, local_user : dict) -> None:
        self.db_session = db_session
        self.redis = redis
        self.local_user = local_user

    def _get_friends(self, player_id) -> list[int]:
        """
        Returns an array of player_ids, matching your friends list.
        # FIXME: This could be refactored to directly use the Friendships API.
        """

        left = self.db_session.query(Friendship.id, Friendship.player1_id, Friendship.player2_id).filter_by(player1_id=player_id, status="active")
        right = self.db_session.query(Friendship.id, Friendship.player2_id, Friendship.player1_id).filter_by(player2_id=player_id, status="active")
        friend_rows = left.union_all(right)

        return [row[2] for row in friend_rows]

    def _get_redis_key(self, player_id) -> str:
        return self.redis.make_key(f"rich_presence:{player_id}")
    
    def _notify_rich_presence_changed(self, player_id):
        presence = self.get_richpresence(player_id)
        presence_json = RichPresenceSchema(many=False).dump(presence)

        for receiver_id in self._get_friends(player_id):
            post_message("players", int(receiver_id), "richpresence", presence_json, sender_system=True)

    def get_richpresence(self, player_id : int) -> PlayerRichPresence:
        """
        Fetches the rich presence information for the specified player.
        """
        local_player = self.local_user['player_id']

        player = self.db_session.query(CorePlayer).get(player_id)
        if not player:
            log.warning("get_richpresence: Player does not exist.")
            raise NotFoundException("Player does not exist.")
        
        if player_id != local_player and player_id not in self._get_friends(local_player):
            log.warning("get_richpresence: No access to player.")
            raise ForbiddenException("No access to player.")
        
        key = self._get_redis_key(player_id)
        presence_dict = self.redis.conn.hgetall(key)

        presence_dict['is_in_game'] = presence_dict.get('map_name', "") != "" or presence_dict.get('game_mode', "") != ""
        presence_dict['player_id'] = player_id

        if presence_dict:
            return RichPresenceSchema(many=False).load(presence_dict)
        else:
            return PlayerRichPresence()

    def set_online_status(self, player_id: int, is_online: bool, send_notification=True) -> bool:
        """
        Sets the players online status, and updates rich-presence
        """

        key = self._get_redis_key(player_id)
        old_online = self.redis.conn.hget(key, "is_online")
        self.redis.conn.hset(key, "is_online", int(is_online))

        if old_online != is_online:
            if send_notification:
                self._notify_rich_presence_changed(player_id)
            return True
        return False

    def set_match_status(self, player_id: int, map_name: str, game_mode: str, send_notification=True) -> bool:
        """
        Sets the players match status, and updates rich-presence
        """

        key = self._get_redis_key(player_id)
        old_game_mode = self.redis.conn.hget(key, "game_mode")
        old_map_name = self.redis.conn.hget(key, "map_name")

        self.redis.conn.hset(key, "game_mode", game_mode)
        self.redis.conn.hset(key, "map_name", map_name)

        if old_game_mode != game_mode or old_map_name != map_name:
            if send_notification:
                self._notify_rich_presence_changed(player_id)
            return True
        return False


    def clear_match_status(self, player_id : int) -> None:
        """
        Returns a players match status back to the default values
        """
        self.set_match_status(player_id, "", "")

    def set_richpresence(self, player_id : int, presence : PlayerRichPresence) -> None:
        """
        Sets the rich presence information for a player. Will queue messages for consumption by interested
        clients.
        """

        match_status_changed = self.set_match_status(player_id, presence.map_name, presence.game_mode, False)
        online_status_changed = self.set_online_status(player_id, presence.is_online, False)

        if match_status_changed or online_status_changed:
            self._notify_rich_presence_changed(player_id)
