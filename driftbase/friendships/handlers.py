# -*- coding: utf-8 -*-

import httplib
import logging
import uuid
import datetime

from flask import Blueprint, request, g, abort, url_for
from flask_restful import Api, Resource

from drift.urlregistry import register_endpoints
from drift.auth.jwtchecker import current_user
from drift.core.extensions.schemachecker import simple_schema_request

from driftbase.db.models import Friendship, CorePlayer
from driftbase.players import log_event, can_edit_player

log = logging.getLogger(__name__)
bp = Blueprint("friendships", __name__)
api = Api(bp)


def get_player(player_id):
    player = g.db.query(CorePlayer).get(player_id)
    return player


class FriendshipsAPI(Resource):

    def get(self):
        """
        List my friends
        """
        player_id = current_user["player_id"]

        left = g.db.query(Friendship.id, Friendship.player1_id, Friendship.player2_id).filter_by(player1_id=player_id)
        right = g.db.query(Friendship.id, Friendship.player2_id, Friendship.player1_id).filter_by(player2_id=player_id)
        friend_rows = left.union_all(right)
        friends = []
        for row in friend_rows:
            friend_id = row[2]
            friend = {
                "friend_id": friend_id,
                "is_online": False,
                "url": url_for("friendships.friendship", friend_id=friend_id, _external=True),
                "messagequeue_url": url_for("messages.exchange", exchange="players", exchange_id=friend_id, _external=True) + "/{queue}",
            }
            friends.append(friend)

        ret = friends
        return ret

    @simple_schema_request({
        "token": {"type": "string", },
        "friend_id": {"type": "number", },
    }, required=["token", "friend_id"])
    def post(self):
        """
        New friend
        """
        player_id = current_user["player_id"]
        if not can_edit_player(player_id):
            abort(httplib.METHOD_NOT_ALLOWED, description="That is not your player!")

        if not get_player(player_id):
            abort(httplib.NOT_FOUND)

        args = request.json
        friend_id = args.get("friend_id")

        redis_key = g.redis.make_key("friendship-token:%s" % (args.get("token")))
        token_friend_id = g.redis.conn.get(redis_key)
        if token_friend_id is None:
            abort(httplib.NOT_FOUND, description="Token not found!")
        if int(token_friend_id) != friend_id:
            abort(httplib.NOT_FOUND, description="Token doesn't match the friend you're adding!")

        left_id = player_id
        right_id = friend_id

        if left_id == right_id:
            abort(httplib.METHOD_NOT_ALLOWED, description="You cannot befriend yourself!")

        if left_id > right_id:
            left_id, right_id = right_id, left_id
        ret = []

        existing_friendship = g.db.query(Friendship).filter(
            Friendship.player1_id == left_id,
            Friendship.player2_id == right_id
        ).first()
        if existing_friendship is not None:
            return ret

        if g.db.query(CorePlayer).filter(CorePlayer.player_id == friend_id).first() is None:
            abort(httplib.METHOD_NOT_ALLOWED, description="No active player with that ID!")

        friendship = Friendship(player1_id=left_id, player2_id=right_id)
        g.db.add(friendship)
        g.db.commit()

        ret = {
            "friend_id": friend_id,
            "is_online": False,
            "url": url_for("friendships.friendship", friend_id=friend_id, _external=True),
            "messagequeue_url": url_for("messages.exchange", exchange="players", exchange_id=friend_id,
                                        _external=True) + "/{queue}",
        }

        return ret, httplib.CREATED


class FriendshipAPI(Resource):
    def delete(self, friend_id):
        """
        Remove a friend
        """
        player_id = current_user["player_id"]
        if not can_edit_player(player_id):
            abort(httplib.METHOD_NOT_ALLOWED, description="That is not your player!")

        if not get_player(player_id):
            abort(httplib.NOT_FOUND)

        left_id = player_id
        right_id = friend_id

        if left_id == right_id:
            abort(httplib.METHOD_NOT_ALLOWED, description="You cannot unfriend yourself!")

        if left_id > right_id:
            left_id, right_id = right_id, left_id

        friendship = g.db.query(Friendship).filter(Friendship.player1_id == left_id, Friendship.player2_id == right_id).first()
        if friendship:
            g.db.delete(friendship)
            g.db.commit()

        return {}, httplib.NO_CONTENT


class FriendshipTokensAPI(Resource):

    def post(self):
        """
        New Friend token
        """
        player_id = current_user["player_id"]
        if not can_edit_player(player_id):
            abort(httplib.METHOD_NOT_ALLOWED, description="That is not your player!")

        if not get_player(player_id):
            abort(httplib.NOT_FOUND)

        token = str(uuid.uuid4())
        redis_key = g.redis.make_key("friendship-token:%s" % (token))
        expires_seconds = 60 * 60 * 24
        expires = datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_seconds)
        g.redis.conn.set(redis_key, player_id)
        g.redis.conn.expire(redis_key, expires_seconds)

        ret = {
                  "token":token,
                  "expires":expires,
                  "url":url_for("friendships.friendshiptoken", token=token)
              }, httplib.CREATED
        return ret


class FriendshipTokenAPI(Resource):

    def delete(self, token):
        """
        Delete a friend token
        """
        player_id = current_user["player_id"]
        if not can_edit_player(player_id):
            abort(httplib.METHOD_NOT_ALLOWED, description="That is not your player!")

        if not get_player(player_id):
            abort(httplib.NOT_FOUND)

        redis_key = g.redis.make_key("friendship-token:%s" % (token))
        result = g.redis.conn.delete(redis_key)
        return {}, httplib.NO_CONTENT if result == 1 else httplib.NOT_FOUND


api.add_resource(FriendshipsAPI, "/friendships", endpoint="friendships")
api.add_resource(FriendshipAPI, "/friendships/<int:friend_id>", endpoint="friendship")
api.add_resource(FriendshipTokensAPI, "/friendshiptokens", endpoint="friendshiptokens")
api.add_resource(FriendshipTokenAPI, "/friendshiptokens/<string:token>", endpoint="friendshiptoken")


@register_endpoints
def endpoint_info(current_user):
    ret = {}
    ret["my_friendships"] = None
    ret["friendship_tokens"] = url_for("friendships.friendshiptokens", _external=True)
    if current_user:
        ret["my_friendships"] = url_for("friendships.friendships", _external=True)
    return ret
