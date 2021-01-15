import logging

import marshmallow as ma
from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints
from drift.utils import Url
from flask import url_for, g
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from six.moves import http_client

from driftbase.api.messages import _add_message
from driftbase.models.db import CorePlayer
from driftbase.parties import accept_party_invite, get_player_party, get_party_members, leave_party, disband_party, \
    create_party_invite, decline_party_invite

log = logging.getLogger(__name__)

bp_parties = Blueprint("parties", __name__, url_prefix='/parties')
bp_party_invites = Blueprint("party_invites", __name__, url_prefix='/party_invites')
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp_parties)
    api.register_blueprint(bp_party_invites)
    endpoints.init_app(app)


class PartyGetSchema(ma.Schema):
    player_id = ma.fields.Integer()


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


class PartyInvitesPostRequestSchema(ma.Schema):
    player_id = ma.fields.Integer()


class PartyInvitesResponseSchema(ma.Schema):
    url = ma.fields.Url()


class PartyPlayerPostRequestSchema(ma.Schema):
    player_id = ma.fields.Integer()


class PartyPlayerResponseSchema(ma.Schema):
    url = ma.fields.Url()


class PartyPlayerSchema(ma.Schema):
    player_id = ma.fields.Integer()


@bp_parties.route("/<int:party_id>/members/", endpoint="members")
class PartyPlayersAPI(MethodView):
    """
    Manage players in a party
    """

    @bp_parties.response(PartyPlayerSchema(many=True))
    def get(self, party_id):
        player_id = current_user['player_id']
        members = get_party_members(party_id)

        if members is None:
            abort(http_client.NOT_FOUND, message="Party not found")

        if player_id not in members:
            abort(http_client.FORBIDDEN, message="Player is not a member of the party")

        response = {
            "members": [
                {
                    'id': player_id,
                    'url': url_for("parties.member", party_id=party_id, player_id=player_id, _external=True),
                    'player_url': url_for("players.entry", player_id=player_id, _external=True),
                }
                for player_id in members]
        }
        return response

    @bp_parties.arguments(PartyPlayerPostRequestSchema, location='json')
    @bp_parties.response(PartyPlayerResponseSchema)
    def post(self, args, party_id):
        player_id = current_user['player_id']
        resource_uri = url_for("parties.member", party_id=party_id, player_id=player_id, _external=True)
        _add_message("players", player_id, "party_notification",
                     {
                         "event": "created",
                         "party_id": party_id,
                         "party_url": resource_uri,
                     })
        response_header = {"Location": resource_uri}
        log.info("Added player {} to party {}".format(player_id, party_id))
        return {"url": resource_uri}, http_client.CREATED, response_header


@bp_parties.route("/<int:party_id>/members/<int:player_id>", endpoint="member")
class PartyPlayerAPI(MethodView):
    """
    Manage a player in a party
    """

    def get(self, party_id, player_id):
        return {
                   "id": player_id,
                   "url": url_for("parties.member", party_id=party_id, player_id=player_id, _external=True),
                   "party_id": party_id,
                   "party_url": url_for("parties.entry", party_id=party_id, _external=True),
                   "members_url": url_for("parties.members", party_id=party_id, _external=True),
                   "invites_url": url_for("parties.invites", party_id=party_id, _external=True),
               }, http_client.OK

    def delete(self, party_id, player_id):
        if player_id != current_user['player_id']:
            abort(http_client.FORBIDDEN, message="You can only remove yourself from a party")

        if leave_party(player_id, party_id) is None:
            abort(http_client.BAD_REQUEST, message="You're not a member of this party")

        members = get_party_members(party_id)
        for member in members:
            _add_message("players", member, "party_notification",
                         {
                             "event": "player_left",
                             "party_id": party_id,
                             "party_url": url_for("parties.entry", party_id=party_id, _external=True),
                             "player_id": player_id,
                             "player_url": url_for("players.entry", player_id=player_id, _external=True),
                         })
        if len(members) <= 1:
            disband_party(party_id)
            _add_message("players", members[0], "party_notification",
                         {
                             "event": "disbanded",
                             "party_id": party_id,
                             "party_url": url_for("parties.entry", party_id=party_id, _external=True),
                         })
        return {}, http_client.NO_CONTENT


@bp_party_invites.route("/", endpoint="list")
class PartyInvitesAPI(MethodView):
    """
    Manage invites for a party
    """

    @bp_parties.arguments(PartyInvitesPostRequestSchema, location='json')
    @bp_parties.response(PartyInvitesResponseSchema)
    def post(self, args):
        my_player_id = current_user['player_id']
        player_id = args.get('player_id')
        if my_player_id == player_id:
            abort(http_client.BAD_REQUEST, message="You can't invite yourself to a party")

        player = g.db.query(CorePlayer).filter(CorePlayer.player_id == player_id).first()
        if player is None:
            log.debug("Player {} tried to invite non-existing player {} to a party".format(my_player_id, player_id))
            abort(http_client.BAD_REQUEST, message="Invited player doesn't exist")

        party_id = args.get('party_id')
        invite_id = create_party_invite(party_id, my_player_id, player_id)
        if invite_id:
            if party_id:
                log.debug("Player {} invited player {} to party {}".format(my_player_id, player_id, party_id))
            else:
                log.debug("Player {} invited player {} to form a new party".format(my_player_id, player_id))

            resource_uri = url_for("party_invites.entry", invite_id=invite_id, _external=True)
            _add_message("players", player_id, "party_notification",
                         {
                             "event": "invite",
                             "invite_id": invite_id,
                             "invite_url": resource_uri,
                             "inviting_player_id": my_player_id,
                             "inviting_player_url": url_for("players.entry", player_id=my_player_id, _external=True),
                         })
            response_header = {"Location": resource_uri}
            return {
                       "id": invite_id,
                       "url": resource_uri,
                   }, http_client.CREATED, response_header
        else:
            abort(http_client.BAD_REQUEST, message="Player is already in the party")


@bp_party_invites.route("/<int:invite_id>", endpoint="entry")
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

    @bp_parties.arguments(PartyInvitesSchema)
    def patch(self, args, invite_id):
        player_id = current_user['player_id']
        inviter_id = args.get('inviter_id')
        party_id, party_members = accept_party_invite(invite_id, inviter_id, player_id)
        log.debug("Player {} accepted invite from player {} to party {}".format(player_id, inviter_id, party_id))
        member_url = url_for("parties.member", party_id=party_id, player_id=player_id, _external=True)
        for member in party_members:
            if member == player_id:
                continue
            _add_message("players", member, "party_notification",
                         {
                             "event": "player_joined",
                             "party_id": party_id,
                             "party_url": url_for("parties.entry", party_id=party_id, _external=True),
                             "player_id": player_id,
                             "member_url": member_url,
                             "player_url": url_for("players.entry", player_id=player_id, _external=True),
                             "inviting_member_url": url_for("parties.member", party_id=party_id, player_id=inviter_id,
                                                            _external=True),
                             "inviting_player_url": url_for("players.entry", player_id=inviter_id, _external=True),
                         })
        response = {
            "party_id": party_id,
            "party_url": url_for("parties.entry", party_id=party_id, _external=True),
            "player_id": player_id,
            "member_url": member_url,
            "player_url": url_for("players.entry", player_id=player_id, _external=True),
        }
        return response, http_client.OK

    def delete(self, invite_id):
        player_id = current_user['player_id']
        inviter_id, invited_id = decline_party_invite(invite_id, player_id)
        if inviter_id == player_id:
            log.debug("Player {} canceled a party invite to {}".format(inviter_id, invited_id))
            _add_message("players", invited_id, "party_notification",
                         {
                             "event": "invite_canceled",
                             "invite_id": invite_id,
                             "inviting_player_id": inviter_id,
                             "inviting_player_url": url_for("players.entry", player_id=inviter_id, _external=True),
                         })
        else:
            log.debug("Player {} declined a party invite from {}".format(player_id, inviter_id))
            _add_message("players", inviter_id, "party_notification",
                         {
                             "event": "invite_declined",
                             "player_id": invited_id,
                             "player_url": url_for("players.entry", player_id=invited_id, _external=True),
                         })
        return {}, http_client.NO_CONTENT


@bp_parties.route("/", endpoint="list")
class PartiesAPI(MethodView):
    """
    Return the party for the current player
    """

    @bp_parties.arguments(PartyGetSchema)
    def get(self, args):
        player_id = current_user['player_id']
        party_id = get_player_party(player_id)

        if party_id is None:
            abort(http_client.NOT_FOUND)

        party_id = int(party_id)
        party_members = get_party_members(party_id)
        member_query = g.db.query(CorePlayer.player_id, CorePlayer.player_name).filter(CorePlayer.player_id.in_(party_members))
        response, response_header = make_party_response(party_id, member_query.all())
        return response, http_client.OK, response_header


@bp_parties.route("/<int:party_id>/", endpoint="entry")
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

        member_query = g.db.query(CorePlayer.player_id, CorePlayer.player_name).filter(CorePlayer.player_id.in_(members))
        response, response_header = make_party_response(party_id, member_query.all())
        return response, http_client.OK, response_header

    def delete(self, party_id):
        members = get_party_members(party_id)
        for member in members:
            leave_party(party_id, member)
        disband_party(party_id)
        return {}, http_client.NO_CONTENT


def make_party_response(party_id, party_members):
    resource_uri = url_for("parties.entry", party_id=party_id, _external=True)
    invites_uri = url_for("party_invites.list", _external=True)
    members_uri = url_for("parties.members", party_id=party_id, _external=True)
    response_header = {"Location": resource_uri}
    response = {
        "id": party_id,
        "url": resource_uri,
        "invites_url": invites_uri,
        "members_url": members_uri,
        "members": [
            {
                'id': player[0],
                'url': url_for("parties.member", party_id=party_id, player_id=player[0], _external=True),
                'player_url': url_for("players.entry", player_id=player[0], _external=True),
                'player_name': player[1],
            }
            for player in party_members]
    }
    return response, response_header


@endpoints.register
def endpoint_info(*args):
    ret = {
        "parties": url_for("parties.list", _external=True),
        "party_invites": url_for("party_invites.list", _external=True),
    }
    return ret
