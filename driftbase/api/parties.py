import logging

import marshmallow as ma
from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints
from drift.utils import Url
from driftbase.models.db import CorePlayer
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
    players = ma.fields.List(ma.fields.Url, required=False)


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
    scoped_party_players_key = make_party_players_key(party_id)
    return [int(member) for member in g.redis.conn.smembers(scoped_party_players_key)]


def set_player_party(player_id, party_id):
    scoped_party_players_key = make_party_players_key(party_id)
    scoped_player_party_key = make_player_party_key(player_id)

    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_party_players_key, scoped_player_party_key)
            current_party = pipe.get(scoped_player_party_key)
            if current_party == party_id:
                return

            if pipe.sismember(scoped_party_players_key, player_id):
                return

            pipe.multi()
            pipe.smembers(scoped_party_players_key)
            pipe.set(scoped_player_party_key, party_id)
            pipe.sadd(scoped_party_players_key, player_id)
            result = pipe.execute()
            return result[0]
    except WatchError:
        abort(http_client.CONFLICT)


def leave_player_party(player_id, party_id):
    scoped_party_players_key = make_party_players_key(party_id)
    scoped_player_party_key = make_player_party_key(player_id)

    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_party_players_key, scoped_player_party_key)
            current_party = pipe.get(scoped_player_party_key)
            if current_party != party_id:
                abort(http_client.BAD_REQUEST, message="You're not a member of this party")

            if not pipe.sismember(scoped_party_players_key, player_id):
                return

            pipe.multi()
            pipe.srem(scoped_party_players_key, player_id)
            pipe.rem(scoped_player_party_key)
            result = pipe.execute()
            return result
    except WatchError:
        abort(http_client.CONFLICT)


def create_party_invite(party_id, inviter_id, invited_id):
    scoped_party_players_key = make_party_players_key(party_id)

    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_party_players_key)
            # You can't invite someone to a party you're not member of
            if not pipe.sismember(scoped_party_players_key, inviter_id):
                abort(http_client.FORBIDDEN, message="The inviting player has left the party")
            # If the player is already a member, just return
            if pipe.sismember(scoped_party_players_key, invited_id):
                log.debug("Player {} is already a member of party {}".format(invited_id, party_id))
                return
            invite_id = pipe.incr("party:{}:invite:id:")
            scoped_party_invite_key = g.redis.make_key("party:{}:invite:{}:".format(party_id, invite_id))
            r = pipe.hset(scoped_party_invite_key, mapping={ b"inviter": inviter_id, b"invited": invited_id })
            pipe.execute()
            return invite_id
    except WatchError:
        abort(http_client.CONFLICT)


def get_party_invite(party_id, invite_id):
    scoped_party_invite_key = make_party_invite_key(invite_id, party_id)
    return g.redis.conn.hgetall(scoped_party_invite_key)


def accept_party_invite(party_id, invite_id, player_id):
    scoped_party_players_key = make_party_players_key(party_id)
    scoped_player_party_key = make_player_party_key(player_id)
    scoped_party_invite_key = make_party_invite_key(invite_id, party_id)

    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_party_players_key, scoped_player_party_key)
            invite = pipe.hgetall(scoped_party_invite_key)
            inviter = invite.get(b"inviter")
            if not inviter:
                pipe.delete(scoped_party_invite_key)
                pipe.execute()
                log.debug("Invite {} for party {} contains no inviting player".format(invite_id, party_id))
                abort(http_client.FORBIDDEN, message="Inviting player doesn't match the invite")

            if not pipe.sismember(scoped_party_players_key, inviter):
                pipe.delete(scoped_party_invite_key)
                pipe.execute()
                abort(http_client.FORBIDDEN, message="The inviting player has left the party")

            if pipe.sismember(scoped_party_players_key, player_id):
                pipe.multi()
                pipe.set(scoped_player_party_key, party_id)
                pipe.delete(scoped_party_invite_key)
                pipe.execute()
                return int(inviter)

            pipe.multi()
            pipe.sadd(scoped_party_players_key, player_id)
            pipe.set(scoped_player_party_key, party_id)
            pipe.delete(scoped_party_invite_key)
            pipe.execute()
            return int(inviter)
    except WatchError:
        abort(http_client.CONFLICT)


def make_party_invite_key(invite_id, party_id):
    return g.redis.make_key("party:{}:invite:{}:".format(party_id, invite_id))


def make_player_party_key(player_id):
    return g.redis.make_key("player:{}:party:".format(player_id))


def make_party_players_key(party_id):
    return g.redis.make_key("party:{}:players:".format(party_id))


def decline_party_invite(party_id, invite_id, player_id):
    scoped_party_players_key = make_party_players_key(party_id)
    scoped_player_party_key = make_player_party_key(player_id)
    scoped_party_invite_key = make_party_invite_key(invite_id, party_id)

    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_player_party_key)
            invite = pipe.hgetall(scoped_party_invite_key)
            if not invite:
                abort(http_client.NOT_FOUND)

            inviter = invite.get(b"inviter")
            if not inviter:
                pipe.delete(scoped_party_invite_key)
                pipe.execute()
                log.debug("Invite {} for party {} contains no inviting player".format(invite_id, party_id))
                abort(http_client.FORBIDDEN, message="Inviting player doesn't match the invite")

            invited = invite.get(b"invited")
            if not invited:
                log.debug("Invite {} for party {} does not contain the invited player".format(invite_id, party_id))
                abort(http_client.FORBIDDEN, message="Inviting player doesn't match the invite")

            if pipe.sismember(scoped_party_players_key, player_id):
                pipe.delete(scoped_party_invite_key)
                pipe.execute()
                return int(inviter)

            pipe.delete(scoped_party_invite_key)
            pipe.execute()
            return int(inviter)
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
            abort(http_client.FORBIDDEN, message="Player is not a member of the party")

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
        return { "url": resource_uri }, http_client.OK, response_header


@bp.route("/<int:party_id>/players/<int:player_id>", endpoint="player")
class PartyPlayerAPI(MethodView):
    """
    Manage a player in a party
    """
    def get(self, party_id, player_id):
        return {
            "party_id": party_id,
            "player_id": player_id,
            "party_url": url_for("parties.entry", party_id=party_id, _external=True),
            "players_url": url_for("parties.players", party_id=party_id, _external=True),
            "invites_url": url_for("parties.invites", party_id=party_id, _external=True),
        }, http_client.OK

    def delete(self, party_id, player_id):
        if player_id != current_user['player_id']:
            abort(http_client.FORBIDDEN, message="You can only remove yourself from a party")

        if leave_player_party(player_id, party_id) is None:
            abort(http_client.NOT_FOUND, message="You're not a member of this party")

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
        player = g.db.query(CorePlayer).filter(CorePlayer.player_id == player_id).first()
        if player is None:
            log.debug("Player {} tried to invite non-existing player {} to party {}".format(my_player_id, player_id, party_id))
            abort(http_client.BAD_REQUEST, message="Player doesn't exist")

        invite_id = create_party_invite(party_id, my_player_id, player_id)
        log.debug("Player {} invited player {} to party {}".format(my_player_id, player_id, party_id))
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
        return { "url": resource_uri }, http_client.CREATED, response_header


@bp.route("/<int:party_id>/invites/<int:invite_id>", endpoint="invite")
class PartyInviteAPI(MethodView):
    def get(self, party_id, invite_id):
        invite = get_party_invite(party_id, invite_id)
        if not invite:
            abort(http_client.NOT_FOUND)
        resource_uri = url_for("parties.invite", party_id=party_id, invite_id=invite_id, _external=True)
        response_header = {"Location": resource_uri}
        return {
                   "url": resource_uri,
                   "party_url": url_for("parties.entry", party_id=party_id, _external=True),
               }, http_client.OK, response_header

    def patch(self, party_id, invite_id):
        player_id = current_user['player_id']
        members = get_party_members(party_id)
        inviter_id = accept_party_invite(party_id, invite_id, player_id)
        log.debug("Player {} accepted invite from {} to party {}".format(player_id, inviter_id, party_id))
        for member in members:
            _add_message("players", member, "party_notification",
                         {
                             "event": "player_joined",
                             "player_id": player_id,
                             "party_url": url_for("parties.entry", party_id=party_id, _external=True)
                         })
        return {
            "player_url": url_for("parties.player", party_id=party_id, player_id=player_id, _external=True),
            "party_url": url_for("parties.entry", party_id=party_id, _external=True)
        }

    def delete(self, party_id, invite_id):
        player_id = current_user['player_id']
        inviter_id = decline_party_invite(party_id, invite_id, player_id)
        log.debug("Player {} declined an invite from {} to party {}".format(player_id, inviter_id, party_id))
        _add_message("players", inviter_id, "party_notification",
                     {
                         "event": "invite_declined",
                         "player_id": player_id,
                         "party_url": url_for("parties.entry", party_id=party_id, _external=True)
                     })
        return {}, http_client.OK


@bp.route("/", endpoint="list")
class PartiesAPI(MethodView):
    """
    Manage player parties.
    """

    @bp.arguments(PartyPostRequestSchema, location='json')
    @bp.response(PartyResponseSchema)
    def post(self, args):
        """
        Create a player party

        Creates a new party and puts the player in it. Can only be called by the
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

        log.info("Created party {} with player {}".format(party_id, player_id))

        response, response_header = make_party_response(party_id)
        return response, http_client.CREATED, response_header


@bp.route("/<int:party_id>/", endpoint="entry")
class PartyAPI(MethodView):
    """
    Manage party of players.
    """
    def get(self, party_id):
        members = get_party_members(party_id)
        response, response_header = make_party_response(party_id)
        response["players"] = [url_for("parties.player", party_id=party_id, player_id=member, _external=True)
                    for member in members]
        return response, http_client.OK, response_header


def make_party_response(party_id):
    resource_uri = url_for("parties.entry", party_id=party_id, _external=True)
    invites_uri = url_for("parties.invites", party_id=party_id, _external=True)
    players_uri = url_for("parties.players", party_id=party_id, _external=True)
    response_header = {"Location": resource_uri}
    response = {
        "url": resource_uri,
        "invites_url": invites_uri,
        "players_url": players_uri,
    }
    return response, response_header


@endpoints.register
def endpoint_info(*args):
    ret = {"parties": url_for("parties.list", _external=True)}
    return ret
