import logging

import marshmallow as ma
from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints
from drift.utils import Url
from flask import url_for, g
from flask.views import MethodView
from flask_smorest import Blueprint, abort, utils
from redis import WatchError
from six.moves import http_client

from driftbase.api.messages import _add_message

log = logging.getLogger(__name__)

bp = Blueprint("parties", __name__, url_prefix='/parties')
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


class PartyGetRequestSchema(ma.Schema):
    secret = ma.fields.String(description="Shared secret for this group")


class PartyPostRequestSchema(ma.Schema):
    player_ids = ma.fields.List(ma.fields.Integer(), required=False)


class PartyPlayerSchema(ma.Schema):
    player_id = ma.fields.Integer()
    player_url = Url('players.entry', player_id='<player_id>', doc='Player resource')
    player_name = ma.fields.String()
    identity_name = ma.fields.String()


class PartyResponseSchema(ma.Schema):
    url = ma.fields.Url()
    invites_url = ma.fields.Url()
    players_url = ma.fields.Url()


class PartyInvitePostRequestSchema(ma.Schema):
    player_id = ma.fields.Integer()


class PartyInviteResponseSchema(ma.Schema):
    url = ma.fields.Url()


class PartyPlayerPostRequestSchema(ma.Schema):
    player_id = ma.fields.Integer()


class PartyPlayerResponseSchema(ma.Schema):
    url = ma.fields.Url()


class PartyPlayerSchema(ma.Schema):
    player_id = ma.fields.Integer()


def create_party():
    party_id = g.redis.incr("party:id:")
    return party_id


def get_party_members(party_id):
    scoped_party_players_key = g.redis.make_key("party:{}:players:".format(party_id))
    return [int(member) for member in g.redis.conn.smembers(scoped_party_players_key)]


def set_player_party(player_id, party_id):
    # Create tenant scoped keys as the pipeline won't do it for us
    scoped_player_party_key = g.redis.make_key("player:{}:party:".format(player_id))
    scoped_party_key = g.redis.make_key("party:{}:players:".format(party_id))

    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_party_key, scoped_player_party_key)
            current_party = pipe.get(scoped_player_party_key)
            if current_party == party_id:
                return

            if pipe.sismember(scoped_party_key, player_id):
                return

            pipe.multi()
            pipe.smembers(scoped_party_key)
            pipe.set(scoped_player_party_key, party_id)
            pipe.sadd(scoped_party_key, player_id)
            result = pipe.execute()
            log.warning(result)
            return result[0]
    except WatchError:
        abort(http_client.CONFLICT)


def leave_player_party(player_id, party_id):
    # Create tenant scoped keys as the pipeline won't do it for us
    scoped_player_party_key = g.redis.make_key("player:{}:party:".format(player_id))
    scoped_party_key = g.redis.make_key("party:{}:players:".format(party_id))

    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_party_key, scoped_player_party_key)
            current_party = pipe.get(scoped_player_party_key)
            if current_party != party_id:
                return

            if not pipe.sismember(scoped_party_key, player_id):
                return

            pipe.multi()
            pipe.srem(scoped_party_key, player_id)
            pipe.rem(scoped_player_party_key)
            result = pipe.execute()
            return result
    except WatchError:
        abort(http_client.CONFLICT)


def create_party_invite(party_id, inviter_id, invited_id):
    scoped_party_key = g.redis.make_key("party:{}:players:".format(party_id))
    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_party_key)
            # You can't invite someone to a party you're not memeber of
            if not pipe.sismember(scoped_party_key, inviter_id):
                abort(http_client.FORBIDDEN)
            # If the player is already a member, just return
            if pipe.sismember(scoped_party_key, invited_id):
                return
            invite_id = pipe.incr("party:{}:invite:id:")
            scoped_party_invite_key = g.redis.make_key("party:{}:invites:{}:".format(party_id, invite_id))
            pipe.hset(scoped_party_invite_key, { "inviter": inviter_id, "invited": invited_id })
            pipe.execute()
            return invite_id
    except WatchError:
        abort(http_client.CONFLICT)


def accept_party_invite(party_id, invite_id, player_id):
    scoped_party_key = g.redis.make_key("party:{}:players:".format(party_id))
    scoped_player_party_key = g.redis.make_key("player:{}:party:".format(player_id))
    scoped_party_invite_key = g.redis.make_key("party:{}:invites:{}:".format(party_id, invite_id))
    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_party_key)
    except WatchError:
        abort(http_client.CONFLICT)


@bp.route("/<int:party_id>/players/", endpoint="players")
class PartyPlayersAPI(MethodView):
    """
    Manage players in a party
    """
    @bp.response(PartyPlayerSchema(many=True))
    def get(self, party_id):
        player_id = current_user['player_id']
        members = get_party_members(party_id)

        if members is None:
            abort(http_client.NOT_FOUND, message="The party no longer exists")

        if player_id not in members:
            abort(http_client.FORBIDDEN)

        players = []
        for member in members:
            players.append({ "player_id": member })
        return players

    @bp.arguments(PartyPlayerPostRequestSchema, location='json')
    @bp.response(PartyPlayerResponseSchema)
    def post(self, args, party_id):
        player_id = current_user['player_id']
        _add_message("players", player_id, "party_notification",
                     {
                         "event":"created",
                         "party_id":party_id
                     })
        resource_uri = url_for("parties.player", party_id=party_id, player_id=player_id, _external=True)
        response_header = {"Location": resource_uri}
        log.info("Added player {} to party {}".format(player_id, party_id))
        utils.get_appcontext().setdefault('headers', {}).update(response_header)
        return { "url": resource_uri }


@bp.route("/<int:party_id>/players/<int:player_id>", endpoint="player")
class PartyPlayerAPI(MethodView):
    """
    Manage a player in a party
    """
    def delete(self, party_id, player_id):
        if player_id != current_user['player_id']:
            abort(http_client.FORBIDDEN)

        if leave_player_party(player_id, party_id) is None:
            abort(http_client.NOT_FOUND)

        members = get_party_members(party_id)
        for member in members:
            _add_message("players", player_id, "party_notification",
                         {
                             "event": "player_left",
                             "party_url": url_for("parties.entry", party_id=party_id, _external=True),
                             "player_url": url_for("players.entry", player_id=member, _external=True)
                         })
        return http_client.OK


@bp.route("/<int:party_id>/invites/", endpoint="invites")
class PartyInvitesAPI(MethodView):
    """
    Manage invites for a party
    """

    @bp.arguments(PartyInvitePostRequestSchema, location='json')
    @bp.response(PartyInviteResponseSchema)
    def post(self, args, party_id):
        my_player_id = current_user['player_id']
        player_id = args.get("player_id")
        invite_id = 0
        _add_message("players", player_id, "party_notification",
                     {
                         "event": "invite",
                         "party_url": url_for("parties.entry", party_id=party_id, _external=True),
                         "invite_url": url_for("parties.invite", party_id=party_id, invite_id=invite_id, _external=True),
                         "inviting_player_id": my_player_id,
                         "inviting_player_url": url_for("players.entry", player_id=player_id, _external=True)
                     })
        resource_uri = url_for("parties.invite", party_id=party_id, invite_id=invite_id, _external=True)
        response_header = {"Location": resource_uri}
        log.info("Added player {} to party {}".format(player_id, party_id))
        utils.get_appcontext().setdefault('headers', {}).update(response_header)
        return { "url": resource_uri }, http_client.CREATED


@bp.route("/<int:party_id>/invites/<int:invite_id>", endpoint="invite")
class PartyInviteAPI(MethodView):
    def get(self, party_id, invite_id):
        return {}


@bp.route("/", endpoint="list")
class PartiesAPI(MethodView):
    """
    Manage player parties.
    """

    @bp.arguments(PartyPostRequestSchema, location='json')
    @bp.response(PartyResponseSchema)
    def post(self, args):
        """
        Create a player group

        Creates a new party for the player. Can only be called by the
        player. If the player is already in a party, he will leave the old party.
        """
        player_id = current_user['player_id']
        party_id = create_party()
        if party_id is None:
            log.error("Failed to create party for player {}".format(player_id))
            abort(http_client.INTERNAL_SERVER_ERROR)
        party_players = set_player_party(player_id, party_id)
        if party_players is None:
            log.error("Failed to add player {} to new party {}".format(player_id, party_id))
            abort(http_client.INTERNAL_SERVER_ERROR)
        resource_uri = url_for("parties.entry", party_id=party_id, _external=True)
        invites_uri = url_for("parties.invites", party_id=party_id, _external=True)
        players_uri = url_for("parties.players", party_id=party_id, _external=True)
        response_header = {"Location": resource_uri}
        log.info("Created party {} with player {}".format(party_id, player_id))
        utils.get_appcontext().setdefault('headers', {}).update(response_header)
        response = {
            "url": resource_uri,
            "invites_url": invites_uri,
            "players_url": players_uri
        }
        _add_message("players", player_id, "party_notification",
                     {
                         "event":"created",
                         "party_id":party_id
                     })
        return response, http_client.CREATED


@bp.route("/<int:party_id>/", endpoint="entry")
class PartyAPI(MethodView):
    """
    Manage party of players.
    """
    def get(self, party_id):
        pass


@endpoints.register
def endpoint_info(*args):
    ret = {"parties": url_for("parties.list", _external=True)}
    return ret
