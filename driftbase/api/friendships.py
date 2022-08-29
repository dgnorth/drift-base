import datetime
import logging
import uuid

import marshmallow as ma
from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints
from flask import request, g, abort, url_for, jsonify
from flask.views import MethodView
from drift.blueprint import Blueprint
import http.client as http_client
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from driftbase.models.db import Friendship, FriendInvite, CorePlayer
from driftbase.schemas.friendships import InviteSchema, FriendRequestSchema
from driftbase.messages import post_message
from driftbase.utils import wordlist

from driftbase.resources.friends import TIER_DEFAULTS

MAX_INVITE_TOKEN_GENERATION_RETRIES = 100
MAX_INVITE_EXPIRATION_SECONDS = 60 * 60 * 24 * 30 # Maximum invite expiration time is 30 days
MIN_WORDLIST_NUMBER_OF_WORDS = 2

log = logging.getLogger(__name__)

bp = Blueprint("friendships", __name__, url_prefix="/friendships")
endpoints = Endpoints()


def on_message(queue_name, message):
    if queue_name == 'clients' and message['event'] == 'created':
        log.info("Friendship is forevur! This one just connected: %s", message['payload'])


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)
    app.messagebus.register_consumer(on_message, "client")


def get_player(player_id):
    player = g.db.query(CorePlayer).get(player_id)
    return player


class FriendshipsPostRequestSchema(ma.Schema):
    token = ma.fields.Str()


class FriendshipsResponseSchema(ma.Schema):
    friend_id = ma.fields.Integer()
    url = ma.fields.Url()
    messagequeue_url = ma.fields.Url()


@bp.route('/players/<int:player_id>', endpoint='list')
class FriendshipsAPI(MethodView):

    def get(self, player_id):
        """
        List my friends
        """
        if player_id != current_user["player_id"]:
            abort(http_client.FORBIDDEN, description="That is not your player!")

        left = g.db.query(Friendship.id, Friendship.player1_id, Friendship.player2_id).filter_by(player1_id=player_id,
                                                                                                 status="active")
        right = g.db.query(Friendship.id, Friendship.player2_id, Friendship.player1_id).filter_by(player2_id=player_id,
                                                                                                  status="active")
        friend_rows = left.union_all(right)
        friends = []
        for row in friend_rows:
            friendship_id = row[0]
            friend_id = row[2]
            friend = {
                "friend_id": friend_id,
                "player_url": url_for("players.entry", player_id=friend_id, _external=True),
                "friendship_url": url_for("friendships.entry", friendship_id=friendship_id, _external=True)
            }
            friends.append(friend)

        ret = friends
        return jsonify(ret)

    @bp.arguments(FriendshipsPostRequestSchema)
    @bp.response(http_client.CREATED, FriendshipsResponseSchema)
    def post(self, args, player_id):
        """
        New friend
        """
        if player_id != current_user["player_id"]:
            abort(http_client.FORBIDDEN, description="That is not your player!")

        invite_token = args.get("token")

        # Get the first non-expired invite that matches the token
        invite = g.db.query(FriendInvite).filter(FriendInvite.token == invite_token, FriendInvite.expiry_date > datetime.datetime.utcnow()).first()
        if invite is None:
            abort(http_client.NOT_FOUND, description="The invite was not found!")

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
                return "{}", http_client.OK
        else:
            friendship = Friendship(player1_id=left_id, player2_id=right_id)
            g.db.add(friendship)

        if invite.issued_to_player_id is not None:
            invite.deleted = True

        g.db.commit()

        ret = {
            "friend_id": friend_id,
            "url": url_for("friendships.entry", friendship_id=friendship.id, _external=True),
            "messagequeue_url": url_for("messages.exchange", exchange="players", exchange_id=friend_id,
                                        _external=True) + "/{queue}",
        }

        return ret, http_client.CREATED


@bp.route('/<int:friendship_id>', endpoint='entry')
class FriendshipAPI(MethodView):

    def delete(self, friendship_id):
        """
        Remove a friend
        """
        player_id = current_user["player_id"]

        friendship = g.db.query(Friendship).filter_by(id=friendship_id).first()
        if friendship is None:
            abort(http_client.NOT_FOUND, description="Unknown friendship")
        elif friendship.player1_id != player_id and friendship.player2_id != player_id:
            abort(http_client.FORBIDDEN, description="You are not friends")
        elif friendship.status == "deleted":
            return jsonify("{}"), http_client.GONE

        if friendship:
            friendship.status = "deleted"
            g.db.commit()

        return jsonify("{}"), http_client.NO_CONTENT


@bp.route('/invites', endpoint='invites')
class FriendInvitesAPI(MethodView):
    class CreateInviteSchema(ma.Schema):
        player_id = ma.fields.Integer(required=False, metadata=dict(description="The receiving player of the invite. Optional."))
        expiration_time_seconds = ma.fields.Integer(required=False, metadata=dict(description="The expiration time of the invite in seconds."))
        token_format = ma.fields.String(required=False, metadata=dict(description="The format of the token. Supported values: 'uuid' and 'wordlist'."))
        worldlist_number_of_words = ma.fields.Integer(required=False, metadata=dict(description="How many words the token should be if the token format is 'wordlist'"))

    @bp.response(http_client.OK, InviteSchema(many=True))
    def get(self):
        """ List invites sent by current player """
        CorePlayer2 = aliased(CorePlayer)
        return g.db.query(FriendInvite, CorePlayer.player_name, CorePlayer2.player_name). \
            join(CorePlayer, CorePlayer.player_id == FriendInvite.issued_to_player_id, isouter=True). \
            join(CorePlayer2, CorePlayer2.player_id == FriendInvite.issued_by_player_id). \
            filter(FriendInvite.issued_by_player_id == int(current_user["player_id"]),
                   FriendInvite.expiry_date > datetime.datetime.utcnow(),
                   FriendInvite.deleted.is_(False))

    @bp.arguments(CreateInviteSchema)
    def post(self, args):
        """
        New Friend token
        """
        sending_player_id = int(current_user["player_id"])
        try:
            receiving_player_id = int(args.get("player_id"))
            self._validate_friend_request(receiving_player_id)
        except TypeError:
            receiving_player_id = None

        token_format = args.get("token_format") or _get_tenant_config_value("invite_token_format")
        if token_format == "uuid":
            token = str(uuid.uuid4())
        elif token_format == "wordlist":
            number_of_words = args.get("worldlist_number_of_words") or _get_tenant_config_value("invite_token_worldlist_number_of_words")
            number_of_words = max(number_of_words, MIN_WORDLIST_NUMBER_OF_WORDS)
            for _ in range(MAX_INVITE_TOKEN_GENERATION_RETRIES):
                token = wordlist.get_word_combination(number_of_words)

                existing_invite = g.db.query(FriendInvite).filter(FriendInvite.token == token).first()
                if existing_invite is None:
                    break

                valid_message = "no longer valid" if existing_invite.deleted or existing_invite.expiry_date <= datetime.datetime.utcnow() else "valid"
                log.info(f"Generated duplicate wordlist invite token '{token}'. Existing token is {valid_message}. Re-generating...")
            else:
                abort(http_client.INTERNAL_SERVER_ERROR, description="Could not generate invite token")
        else:
            abort(http_client.BAD_REQUEST, description="Invalid token format")

        expires_seconds = args.get("expiration_time_seconds") or _get_tenant_config_value("invite_expiration_seconds")
        expires_seconds = min(expires_seconds, MAX_INVITE_EXPIRATION_SECONDS)
        expires = datetime.datetime.utcnow() + datetime.timedelta(seconds=expires_seconds)

        try:
            invite = FriendInvite(
                token=token,
                issued_by_player_id=sending_player_id,
                issued_to_player_id=receiving_player_id,
                expiry_date=expires
            )

            g.db.add(invite)
            g.db.commit()
        except IntegrityError as e:
            abort(http_client.BAD_REQUEST, description="Invalid player IDs provided with request.")

        if receiving_player_id is not None:
            self._post_friend_request_message(sending_player_id, receiving_player_id, token, expires_seconds)

        ret = jsonify({
            "token": token,
            "expires": expires,
            "url": url_for("friendships.invite", invite_id=invite.id, _external=True)
        }), http_client.CREATED
        return ret

    @staticmethod
    def _validate_friend_request(receiving_player_id):
        sending_player_id = int(current_user["player_id"])
        if receiving_player_id == sending_player_id:
            abort(http_client.CONFLICT, description="Cannot send friend requests to yourself")

        player1_id, player2_id = min(sending_player_id, receiving_player_id), max(sending_player_id,
                                                                                  receiving_player_id)
        existing_friendship = g.db.query(Friendship).filter(
            Friendship.player1_id == player1_id,
            Friendship.player2_id == player2_id
        ).first()
        if existing_friendship and existing_friendship.status == "active":
            abort(http_client.CONFLICT, description="You are already friends")  # Already friends
        pending_invite = g.db.query(FriendInvite). \
            filter(FriendInvite.issued_by_player_id == sending_player_id,
                   FriendInvite.issued_to_player_id == receiving_player_id). \
            filter(FriendInvite.expiry_date > datetime.datetime.utcnow(), FriendInvite.deleted.is_(False)). \
            first()
        if pending_invite:
            abort(http_client.CONFLICT, description="Cannot issue multiple friend requests to the same receiver")
        reciprocal_invite = g.db.query(FriendInvite). \
            filter(FriendInvite.issued_by_player_id == receiving_player_id,
                   FriendInvite.issued_to_player_id == sending_player_id). \
            filter(FriendInvite.expiry_date > datetime.datetime.utcnow(), FriendInvite.deleted.is_(False)).first()
        if reciprocal_invite:
            abort(http_client.CONFLICT, description="The receiver has already sent you a friend request")

    @staticmethod
    def _post_friend_request_message(sender_player_id, receiving_player_id, token, expiry):
        """ Insert a 'friend_request' event into the 'friendevent' queue of the 'players' exchange. """
        if receiving_player_id is None:
            log.warning(
                "Not creating a friend_request event for a non-specific invite from player id %s" % sender_player_id)
            return
        payload = {"token": token, "event": "friend_request"}
        post_message("players", receiving_player_id, "friendevent", payload, expiry)


@bp.route('/invites/<int:invite_id>', endpoint='invite')
class FriendInviteAPI(MethodView):

    def delete(self, invite_id):
        """
        Delete a friend token
        """
        player_id = current_user["player_id"]

        invite = g.db.query(FriendInvite).filter_by(id=invite_id).first()
        if not invite:
            abort(http_client.NOT_FOUND, description="Invite not found")
        elif invite.issued_by_player_id != player_id and invite.issued_to_player_id != player_id:
            # You may only delete invites sent by you or directly to you.
            abort(http_client.FORBIDDEN, description="Not your invite")
        elif invite.deleted:
            return jsonify("{}"), http_client.GONE

        invite.deleted = True
        g.db.commit()
        return jsonify("{}"), http_client.NO_CONTENT


@bp.route('/requests/', endpoint='requests')
class FriendRequestsAPI(MethodView):
    @bp.response(http_client.OK, FriendRequestSchema(many=True))
    def get(self):
        """
        Return pending friend requests sent to current player
        """
        CorePlayer2 = aliased(CorePlayer)
        return g.db.query(FriendInvite, CorePlayer.player_name, CorePlayer2.player_name). \
            join(CorePlayer, CorePlayer.player_id == FriendInvite.issued_to_player_id). \
            join(CorePlayer2, CorePlayer2.player_id == FriendInvite.issued_by_player_id). \
            filter(FriendInvite.issued_to_player_id == int(current_user["player_id"]),
                   FriendInvite.expiry_date > datetime.datetime.utcnow(),
                   FriendInvite.deleted.is_(False))


@endpoints.register
def endpoint_info(*args):
    ret = {
        "my_friends": None,
        "friend_invites": url_for("friendships.invites", _external=True),
        "friend_requests": url_for("friendships.requests", _external=True)
    }
    if current_user:
        ret["my_friends"] = url_for("friendships.list", player_id=current_user["player_id"], _external=True)
    return ret

# Helpers

def _get_tenant_config_value(config_key):
    default_value = TIER_DEFAULTS.get(config_key, None)
    tenant = g.conf.tenant
    if tenant:
        return g.conf.tenant.get("friends", {}).get(config_key, default_value)
    return default_value
