import logging

import marshmallow as ma
from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints
from drift.utils import Url
from flask import url_for, g
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from redis import WatchError
from six.moves import http_client

from driftbase.api.messages import _add_message
from driftbase.models.db import CorePlayer

log = logging.getLogger(__name__)

bp = Blueprint("parties", __name__, url_prefix='/parties')
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


class PartyGetRequestSchema(ma.Schema):
    secret = ma.fields.String(description="Shared secret for this group")


class PartyInvitesSchema(ma.Schema):
    inviter_id = ma.fields.Integer()


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


def new_accept_invite(invite_id, sending_player, accepting_player):
    sending_player_party_key = make_player_party_key(sending_player)
    accepting_player_party_key = make_player_party_key(accepting_player)
    sending_player_invites_key = g.redis.make_key("player:{}:invites:".format(accepting_player))
    invite_key = g.redis.make_key("party_invite:{}:".format(invite_id))
    party_id_key = g.redis.make_key("party:id:")

    with g.redis.conn.pipeline() as pipe:
        try:
            pipe.watch(invite_key, accepting_player_party_key, sending_player_party_key, sending_player_invites_key)

            # Get player and invite details
            pipe.multi()
            pipe.get(sending_player_party_key)
            pipe.get(accepting_player_party_key)
            pipe.hgetall(invite_key)
            sending_player_party_id, accepting_player_party_id, invite = pipe.execute()

            # Check that everything is valid
            if not invite:
                abort(http_client.NOT_FOUND)

            if int(invite[b'from']) != sending_player or int(invite[b'to']) != accepting_player:
                abort(http_client.BAD_REQUEST, message="Invite doesn't match players")

            if accepting_player_party_id and sending_player_party_id != accepting_player_party_id:
                abort(http_client.BAD_REQUEST, message="You must leave your current party first")

            pipe.watch(invite_key, accepting_player_party_key, sending_player_party_key, sending_player_invites_key)

            # If the inviting player is not in a party, form one now
            if sending_player_party_id is None:
                sending_player_party_id = pipe.incr(party_id_key)
                party_players_key = make_party_players_key(sending_player_party_id)
                pipe.multi()
                # Add inviting player to the new party
                pipe.sadd(party_players_key, sending_player)
                pipe.set(sending_player_party_key, sending_player_party_id)
            else:
                party_players_key = make_party_players_key(int(sending_player_party_id))
                pipe.multi()
            # Delete the invite
            pipe.delete(invite_key)
            pipe.srem(sending_player_invites_key, invite_id)
            # Add invited player to the party
            pipe.sadd(party_players_key, accepting_player)
            pipe.set(accepting_player_party_key, sending_player_party_id)
            # Get all the members
            pipe.smembers(party_players_key)
            result = pipe.execute()
            return int(sending_player_party_id),[int(entry) for entry in result[-1]]
        except WatchError:
            abort(http_client.CONFLICT)


def create_party():
    party_id = g.redis.incr("party:id:")
    return party_id


def get_party_members(party_id):
    scoped_party_players_key = make_party_players_key(party_id)
    return [int(member) for member in g.redis.conn.smembers(scoped_party_players_key)]


def set_player_party(player_id, party_id):
    scoped_party_players_key = make_party_players_key(party_id)
    scoped_player_party_key = make_player_party_key(player_id)

    with g.redis.conn.pipeline() as pipe:
        try:
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


def leave_party(player_id, party_id):
    scoped_party_players_key = make_party_players_key(party_id)
    scoped_player_party_key = make_player_party_key(player_id)

    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_party_players_key, scoped_player_party_key)
            current_party = pipe.get(scoped_player_party_key)

            # Can't leave a party you're not a member of
            if current_party != party_id:
                abort(http_client.BAD_REQUEST, message="You're not a member of this party")

            # If the player has already left, do nothing
            if not pipe.sismember(scoped_party_players_key, player_id):
                return

            pipe.multi()
            pipe.srem(scoped_party_players_key, player_id)
            pipe.rem(scoped_player_party_key)
            result = pipe.execute()
            return result
    except WatchError:
        abort(http_client.CONFLICT)


def new_leave_party(player_id, party_id):
    scoped_party_players_key = make_party_players_key(party_id)
    scoped_player_party_key = make_player_party_key(player_id)

    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_party_players_key, scoped_player_party_key)
            current_party = pipe.get(scoped_player_party_key)

            # Can't leave a party you're not a member of
            if int(current_party) != party_id:
                abort(http_client.BAD_REQUEST, message="You're not a member of this party")

            # If the player has already left, do nothing
            if not pipe.sismember(scoped_party_players_key, player_id):
                return

            pipe.multi()
            pipe.srem(scoped_party_players_key, player_id)
            pipe.delete(scoped_player_party_key)
            result = pipe.execute()
            return result
    except WatchError:
        abort(http_client.CONFLICT)


def disband_party(party_id):
    scoped_party_players_key = make_party_players_key(party_id)

    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_party_players_key)
            players = pipe.smembers(scoped_party_players_key)
            pipe.multi()
            for player in players:
                pipe.delete(make_player_party_key(player))
            pipe.delete(scoped_party_players_key)
            result = pipe.execute()
            return result
    except WatchError:
        abort(http_client.CONFLICT)


def new_create_party_invite(party_id, sending_player_id, invited_player_id):
    inviting_player_party_key = make_player_party_key(sending_player_id)
    invited_player_party_key = make_player_party_key(invited_player_id)
    scoped_invite_id_key = g.redis.make_key("party_invite:id:")

    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(invited_player_party_key)

            inviting_player_party_id = pipe.get(inviting_player_party_key)
            if inviting_player_party_id:
                party_players_key = make_party_players_key(inviting_player_party_id)
                pipe.multi()
                pipe.sismember(party_players_key, invited_player_id)
                pipe.get(invited_player_party_key)
                is_already_in_team, invited_player_party_id = pipe.execute()
                pipe.watch(invited_player_party_key)
                if is_already_in_team and invited_player_party_id == inviting_player_party_id:
                    log.debug("Player {} is already a member of party {}".format(invited_player_id, party_id))
                    return None

            invite_id = pipe.incr(scoped_invite_id_key)
            scoped_invite_key = make_new_party_invite_key(invite_id)
            pipe.multi()
            pipe.hset(scoped_invite_key, mapping={ b"from": sending_player_id, b"to": invited_player_id})
            pipe.execute()
            return invite_id
    except WatchError:
        abort(http_client.CONFLICT)


def make_new_party_invite_key(invite_id):
    return g.redis.make_key("party_invite:{}:".format(invite_id))


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

            invite_id = pipe.incr(g.redis.make_key("party:{}:invite:id:"))
            scoped_party_invite_key = g.redis.make_key("invite:{}:".format(invite_id))
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


def new_decline_party_invite(invite_id, declining_player_id):
    scoped_player_party_key = make_player_party_key(declining_player_id)
    scoped_party_invite_key = make_new_party_invite_key(invite_id)

    try:
        with g.redis.conn.pipeline() as pipe:
            pipe.watch(scoped_player_party_key)

            # Get invite details
            invite = pipe.hgetall(scoped_party_invite_key)

            # Check there's an invite
            if not invite:
                abort(http_client.NOT_FOUND)

            invite_sender_id = invite.get(b"from")
            invite_receiver_id = invite.get(b"to")
            if not invite_receiver_id:
                log.debug("Party invite {} does not contain the invited player".format(invite_id))
                abort(http_client.FORBIDDEN, message="Inviting player doesn't match the invite")

            if int(invite_receiver_id) != declining_player_id:
                log.debug("Party invite {} does not belong to the declining player".format(invite_id))
                abort(http_client.FORBIDDEN, message="You can only decline invites to or from yourself")

            pipe.delete(scoped_party_invite_key)
            pipe.execute()
            return int(invite_sender_id)
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

        if new_leave_party(player_id, party_id) is None:
            abort(http_client.FORBIDDEN, message="You're not a member of this party")

        members = get_party_members(party_id)
        if len(members) > 1:
            for member in members:
                _add_message("players", member, "party_notification",
                             {
                                 "event": "player_left",
                                 "party_url": url_for("parties.entry", party_id=party_id, _external=True),
                                 "player_id": player_id,
                                 "player_url": url_for("players.entry", player_id=player_id, _external=True)
                             })
        else:
            disband_party(party_id)
            _add_message("players", members[0], "party_notification",
                     {
                         "event": "player_left",
                         "party_url": url_for("parties.entry", party_id=party_id, _external=True),
                         "player_id": player_id,
                         "player_url": url_for("players.entry", player_id=player_id, _external=True)
                     })
        return {}, http_client.OK


@bp.route("/party_invites/", endpoint="invites")
class PartyInvitesAPI(MethodView):
    """
    Manage invites for a party
    """

    @bp.arguments(PartyInvitePostRequestSchema, location='json')
    @bp.response(PartyInviteResponseSchema)
    def post(self, args):
        my_player_id = current_user['player_id']
        player_id = args.get('player_id')
        player = g.db.query(CorePlayer).filter(CorePlayer.player_id == player_id).first()
        if player is None:
            log.debug("Player {} tried to invite non-existing player {} to a party".format(my_player_id, player_id))
            abort(http_client.BAD_REQUEST, message="Player doesn't exist")

        party_id = args.get('party_id')
        invite_id = new_create_party_invite(party_id, my_player_id, player_id)
        if invite_id:
            if party_id:
                log.debug("Player {} invited player {} to party {}".format(my_player_id, player_id, party_id))
            else:
                log.debug("Player {} invited player {} to form a new party".format(my_player_id, player_id))

        resource_uri = url_for("parties.invite", invite_id=invite_id, _external=True)
        _add_message("players", player_id, "party_notification",
                     {
                         "event": "invite",
                         "inviting_player_id": my_player_id,
                         "invite_url": resource_uri,
                     })
        response_header = {"Location": resource_uri}
        return { "url": resource_uri }, http_client.CREATED, response_header


@bp.route("/invites/<int:invite_id>", endpoint="invite")
class PartyInviteAPI(MethodView):
    # def get(self, party_id, invite_id):
    #     invite = get_party_invite(party_id, invite_id)
    #     if not invite:
    #         abort(http_client.NOT_FOUND)
    #     resource_uri = url_for("parties.invite", party_id=party_id, invite_id=invite_id, _external=True)
    #     response_header = {"Location": resource_uri}
    #     response = {
    #         "url": resource_uri,
    #         "party_url": url_for("parties.entry", party_id=party_id, _external=True),
    #     }
    #     return response, http_client.OK, response_header

    @bp.arguments(PartyInvitesSchema)
    def patch(self, args, invite_id):
        player_id = current_user['player_id']
        inviter_id = args.get('inviter_id')
        party_id, party_members = new_accept_invite(invite_id, inviter_id, player_id)
        log.debug("Player {} accepted invite from player {} to party {}".format(player_id, inviter_id, party_id))
        player_url = url_for("parties.player", party_id=party_id, player_id=player_id, _external=True)
        for member in party_members:
            if member == player_id:
                continue
            _add_message("players", member, "party_notification",
                         {
                             "event": "player_joined",
                             "party_url": url_for("parties.entry", party_id=party_id, _external=True),
                             "player_id": player_id,
                             "player_url": player_url,
                         })
        response = {
            "party_url": url_for("parties.entry", party_id=party_id, _external=True),
            "player_url": player_url,
        }
        return response, http_client.OK

    def delete(self, invite_id):
        player_id = current_user['player_id']
        inviter_id = new_decline_party_invite(invite_id, player_id)
        log.debug("Player {} declined a party invite from {}".format(player_id, inviter_id))
        _add_message("players", inviter_id, "party_notification",
                     {
                         "event": "invite_declined",
                         "player_id": player_id,
                     })
        return {}, http_client.OK


@bp.route("/", endpoint="list")
class PartiesAPI(MethodView):
    """
    Manage player parties.
    """

    def get(self):
        return {}


@bp.route("/<int:party_id>/", endpoint="entry")
class PartyAPI(MethodView):
    """
    Manage party of players.
    """

    def get(self, party_id):
        members = get_party_members(party_id)
        if not members:
            abort(http_client.NOT_FOUND)

        player_id = current_user['player_id']
        if player_id not in members:
            abort(http_client.FORBIDDEN, message="This is not your party")

        response, response_header = make_party_response(party_id)
        response['players'] = [
            {
                'id': player_id,
                'url': url_for("parties.player", party_id=party_id, player_id=player_id, _external=True)
            }
            for player_id in members]
        return response, http_client.OK, response_header

    def delete(self, party_id):
        members = get_party_members(party_id)
        for member in members:
            leave_party(party_id, member)
        return {}, http_client.OK


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
    ret = {
        "parties": url_for("parties.list", _external=True),
        "party_invites": url_for("parties.invites", _external=True),
    }
    return ret
