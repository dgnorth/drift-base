# -*- coding: utf-8 -*-

import httplib
import logging
import uuid
import datetime

from flask import Blueprint, request, g, abort, url_for
from flask_restful import Api, Resource, reqparse

from drift.urlregistry import register_endpoints
from drift.auth.jwtchecker import current_user
from drift.core.extensions.schemachecker import simple_schema_request

from driftbase.db.models import Friendship, FriendInvite, CorePlayer


DEFAULT_INVITE_EXPIRATION_TIME_SECONDS = 60 * 60 * 1


log = logging.getLogger(__name__)
bp = Blueprint("friendships", __name__)
api = Api(bp)


def get_player(player_id):
    player = g.db.query(CorePlayer).get(player_id)
    return player


class FriendshipsAPI(Resource):

    def get(self, player_id):
        """
        List my friends
        """
        if player_id != current_user["player_id"]:
            abort(httplib.FORBIDDEN, description="That is not your player!")

        left = g.db.query(Friendship.id, Friendship.player1_id, Friendship.player2_id).filter_by(player1_id=player_id, status="active")
        right = g.db.query(Friendship.id, Friendship.player2_id, Friendship.player1_id).filter_by(player2_id=player_id, status="active")
        friend_rows = left.union_all(right)
        friends = []
        for row in friend_rows:
            friendship_id = row[0]
            friend_id = row[2]
            friend = {
                "friend_id": friend_id,
                "player_url": url_for("players.player", player_id=friend_id, _external=True),
                "friendship_url": url_for("friendships.friendship", friendship_id=friendship_id, _external=True)
            }
            friends.append(friend)

        ret = friends
        return ret

    @simple_schema_request({
        "token": {"type": "string", },
    }, required=["token"])
    def post(self, player_id):
        """
        New friend
        """
        if player_id != current_user["player_id"]:
            abort(httplib.FORBIDDEN, description="That is not your player!")

        args = request.json
        invite_token=args.get("token")

        invite = g.db.query(FriendInvite).filter_by(token=invite_token).first()
        if invite is None:
            abort(httplib.NOT_FOUND, description="The invite was not found!")

        if invite.expiry_date < datetime.datetime.utcnow():
            abort(httplib.FORBIDDEN, description="The invite has expired!")

        if invite.deleted:
            abort(httplib.FORBIDDEN, description="The invite has been deleted!")

        friend_id = invite.issued_by_player_id
        left_id = player_id
        right_id = friend_id

        if left_id == right_id:
            abort(httplib.FORBIDDEN, description="You cannot befriend yourself!")

        if left_id > right_id:
            left_id, right_id = right_id, left_id

        existing_friendship = g.db.query(Friendship).filter(
            Friendship.player1_id == left_id,
            Friendship.player2_id == right_id
        ).first()
        if existing_friendship is not None:
            friendship = existing_friendship
            if friendship.status == "deleted":
                friendship.status = "active"
            else:
                return {}, httplib.OK
        else:
            friendship = Friendship(player1_id=left_id, player2_id=right_id)
            g.db.add(friendship)
        g.db.commit()

        ret = {
            "friend_id": friend_id,
            "url": url_for("friendships.friendship", friendship_id=friendship.id, _external=True),
            "messagequeue_url": url_for("messages.exchange", exchange="players", exchange_id=friend_id,
                                        _external=True) + "/{queue}",
        }

        return ret, httplib.CREATED


class FriendshipAPI(Resource):

    def delete(self, friendship_id):
        """
        Remove a friend
        """
        player_id = current_user["player_id"]

        friendship = g.db.query(Friendship).filter_by(id=friendship_id).first()
        if friendship is None:
            abort(httplib.NOT_FOUND)
        elif friendship.player1_id != player_id and friendship.player2_id != player_id:
            abort(httplib.FORBIDDEN)
        elif friendship.status == "deleted":
            return {}, httplib.GONE

        if friendship:
            friendship.status = "deleted"
            g.db.commit()

        return {}, httplib.NO_CONTENT


class FriendInvitesAPI(Resource):

    def post(self):
        """
        New Friend token
        """
        player_id = current_user["player_id"]

        token = str(uuid.uuid4())
        expires_seconds = DEFAULT_INVITE_EXPIRATION_TIME_SECONDS
        config = g.conf.tenant.get('friends')
        if config:
            expires_seconds = config['invite_expiration_seconds']
        expires_seconds = expires_seconds
        expires = datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_seconds)

        invite = FriendInvite(
            token=token,
            issued_by_player_id=player_id,
            expiry_date=expires
        )

        g.db.add(invite)
        g.db.commit()

        ret = {
            "token":token,
            "expires":expires,
            "url":url_for("friendships.friendinvite", invite_id=invite.id, _external=True)
        }, httplib.CREATED
        return ret


class FriendInviteAPI(Resource):

    def delete(self, invite_id):
        """
        Delete a friend token
        """
        player_id = current_user["player_id"]

        invite = g.db.query(FriendInvite).filter_by(id=invite_id).first()
        if not invite:
            abort(httplib.NOT_FOUND)
        elif invite.issued_by_player_id != player_id:
            abort(httplib.FORBIDDEN)
        elif invite.deleted:
            return {}, httplib.GONE

        invite.deleted = True
        g.db.commit()
        return {}, httplib.NO_CONTENT


api.add_resource(FriendshipsAPI, "/friendships/players/<int:player_id>", endpoint="friendships")
api.add_resource(FriendshipAPI, "/friendships/<int:friendship_id>", endpoint="friendship")
api.add_resource(FriendInvitesAPI, "/friendships/invites", endpoint="friendinvites")
api.add_resource(FriendInviteAPI, "/friendships/invites/<int:invite_id>", endpoint="friendinvite")


@register_endpoints
def endpoint_info(current_user):
    ret = {}
    ret["my_friends"] = None
    ret["friend_invites"] = url_for("friendships.friendinvites", _external=True)
    if current_user:
        ret["my_friends"] = url_for("friendships.friendships", player_id=current_user["player_id"], _external=True)
    return ret
