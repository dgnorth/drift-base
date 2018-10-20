import logging
import uuid
import datetime

from six.moves import http_client

from flask import request, g, abort, url_for
from flask_restplus import Namespace, Resource, reqparse
from drift.core.extensions.urlregistry import Endpoints

from drift.core.extensions.jwt import current_user
from drift.core.extensions.schemachecker import simple_schema_request

from driftbase.models.db import Friendship, FriendInvite, CorePlayer


DEFAULT_INVITE_EXPIRATION_TIME_SECONDS = 60 * 60 * 1


log = logging.getLogger(__name__)


namespace = Namespace("friendships", "Player to player relationships")
endpoints = Endpoints()


def on_message(queue_name, message):
    if queue_name == 'clients' and message['event'] == 'created':
        log.info("Friendship is forevur! This one just connected: %s", message['payload'])


def drift_init_extension(app, api, **kwargs):
    api.add_namespace(namespace)
    endpoints.init_app(app)
    app.messagebus.register_consumer(on_message, 'clients')


def get_player(player_id):
    player = g.db.query(CorePlayer).get(player_id)
    return player


@namespace.route('/players/<int:player_id>', endpoint='friendships')
class FriendshipsAPI(Resource):

    def get(self, player_id):
        """
        List my friends
        """
        if player_id != current_user["player_id"]:
            abort(http_client.FORBIDDEN, description="That is not your player!")

        left = g.db.query(Friendship.id, Friendship.player1_id, Friendship.player2_id).filter_by(player1_id=player_id, status="active")
        right = g.db.query(Friendship.id, Friendship.player2_id, Friendship.player1_id).filter_by(player2_id=player_id, status="active")
        friend_rows = left.union_all(right)
        friends = []
        for row in friend_rows:
            friendship_id = row[0]
            friend_id = row[2]
            friend = {
                "friend_id": friend_id,
                "player_url": url_for("player", player_id=friend_id, _external=True),
                "friendship_url": url_for("friendship", friendship_id=friendship_id, _external=True)
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
            abort(http_client.FORBIDDEN, description="That is not your player!")

        args = request.json
        invite_token=args.get("token")

        invite = g.db.query(FriendInvite).filter_by(token=invite_token).first()
        if invite is None:
            abort(http_client.NOT_FOUND, description="The invite was not found!")

        if invite.expiry_date < datetime.datetime.utcnow():
            abort(http_client.FORBIDDEN, description="The invite has expired!")

        if invite.deleted:
            abort(http_client.FORBIDDEN, description="The invite has been deleted!")

        friend_id = invite.issued_by_player_id
        left_id = player_id
        right_id = friend_id

        if left_id == right_id:
            abort(http_client.FORBIDDEN, description="You cannot befriend yourself!")

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
                return {}, http_client.OK
        else:
            friendship = Friendship(player1_id=left_id, player2_id=right_id)
            g.db.add(friendship)
        g.db.commit()

        ret = {
            "friend_id": friend_id,
            "url": url_for("friendship", friendship_id=friendship.id, _external=True),
            "messagequeue_url": url_for("messages_exchange", exchange="players", exchange_id=friend_id,
                                        _external=True) + "/{queue}",
        }

        return ret, http_client.CREATED


@namespace.route('/<int:friendship_id>', endpoint='friendship')
class FriendshipAPI(Resource):

    def delete(self, friendship_id):
        """
        Remove a friend
        """
        player_id = current_user["player_id"]

        friendship = g.db.query(Friendship).filter_by(id=friendship_id).first()
        if friendship is None:
            abort(http_client.NOT_FOUND)
        elif friendship.player1_id != player_id and friendship.player2_id != player_id:
            abort(http_client.FORBIDDEN)
        elif friendship.status == "deleted":
            return {}, http_client.GONE

        if friendship:
            friendship.status = "deleted"
            g.db.commit()

        return {}, http_client.NO_CONTENT


@namespace.route('/invites', endpoint='friendinvites')
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
            "token": token,
            "expires": expires,
            "url": url_for("friendinvite", invite_id=invite.id, _external=True)
        }, http_client.CREATED
        return ret


@namespace.route('/invites/<int:invite_id>', endpoint='friendinvite')
class FriendInviteAPI(Resource):

    def delete(self, invite_id):
        """
        Delete a friend token
        """
        player_id = current_user["player_id"]

        invite = g.db.query(FriendInvite).filter_by(id=invite_id).first()
        if not invite:
            abort(http_client.NOT_FOUND)
        elif invite.issued_by_player_id != player_id:
            abort(http_client.FORBIDDEN)
        elif invite.deleted:
            return {}, http_client.GONE

        invite.deleted = True
        g.db.commit()
        return {}, http_client.NO_CONTENT


@endpoints.register
def endpoint_info(*args):
    ret = {}
    ret["my_friends"] = None
    ret["friend_invites"] = url_for("friendinvites", _external=True)
    if current_user:
        ret["my_friends"] = url_for("friendships", player_id=current_user["player_id"], _external=True)
    return ret
