"""
    Custom game lobbies for private/direct matches
"""

from flask_smorest import Blueprint, abort
from drift.core.extensions.urlregistry import Endpoints
from drift.core.extensions.jwt import requires_roles
from marshmallow import Schema, fields
from flask.views import MethodView
from flask import url_for, request
from drift.core.extensions.jwt import current_user
from driftbase import lobbies
from driftbase import flexmatch
import http.client as http_client
import logging



bp = Blueprint("lobbies", "lobbies", url_prefix="/lobbies", description="Custom game lobbies for private/direct matches.")
endpoints = Endpoints()
log = logging.getLogger(__name__)

def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    app.messagebus.register_consumer(lobbies.process_match_message, "match")
    endpoints.init_app(app)

class CreateLobbyRequestSchema(Schema):
    team_capacity = fields.Integer(required=True, metadata=dict(description="How many members can be in one team."))
    team_names = fields.List(fields.String(), required=True, metadata=dict(description="The unique names of the teams."))
    lobby_name = fields.String(required=False, metadata=dict(description="Optional initial name of the lobby."))
    map_name = fields.String(required=False, metadata=dict(description="Optional initial map name for the lobby."))

class UpdateLobbyRequestSchema(Schema):
    team_capacity = fields.Integer(required=False, metadata=dict(description="How many members can be in one team."))
    team_names = fields.List(fields.String(), required=False, metadata=dict(description="The unique names of the teams."))
    lobby_name = fields.String(required=False, metadata=dict(description="Optional initial name of the lobby."))
    map_name = fields.String(required=False, metadata=dict(description="Optional initial map name for the lobby."))

class LobbyMemberResponseSchema(Schema):
    player_id = fields.Integer(metadata=dict(description="The player id of the lobby member."))
    player_name = fields.String(metadata=dict(description="The player name of the lobby member."))
    team_name = fields.String(metadata=dict(description="What team this lobby member is assigned to."))
    ready = fields.Bool(metadata=dict(description="Whether or not this player is ready to start the match."))
    host = fields.Bool(metadata=dict(description="Whether or not this is the lobby host."))

    lobby_member_url = fields.URL(metadata=dict(description="Lobby member URL"))

class LobbyResponseSchema(Schema):
    lobby_id = fields.String(metadata=dict(description="The id for the lobby."))
    lobby_name = fields.String(metadata=dict(description="The name of the lobby."))
    team_capacity = fields.Integer(metadata=dict(description="How many members can be in one team."))
    team_names = fields.List(fields.String(), metadata=dict(description="The unique names of the teams."))
    map_name = fields.String(allow_none=True, metadata=dict(description="The map name for the lobby."))
    create_date = fields.String(metadata=dict(description="The UTC timestamp of when the lobby was created."))
    start_date = fields.String(allow_none=True, metadata=dict(description="The UTC timestamp of when the lobby match was started."))
    status = fields.String(metadata=dict(description="The current status of the lobby."))
    members = fields.List(fields.Nested(LobbyMemberResponseSchema), metadata=dict(description="The lobby members."))

    lobby_url = fields.Url(metadata=dict(description="URL for the lobby."))
    lobby_members_url = fields.Url(metadata=dict(description="URL for the lobby members."))
    lobby_member_url = fields.Url(metadata=dict(description="Lobby member URL for the player issuing the request."))

class UpdateLobbyMemberRequestSchema(Schema):
    team_name = fields.String(allow_none=True, dump_default=None, metadata=dict(description="What team this lobby member is assigned to."))
    ready = fields.Bool(allow_none=True, dump_default=False, metadata=dict(description="Whether or not this player is ready to start the match."))

@bp.route("/", endpoint="lobbies")
class LobbiesAPI(MethodView):

    @bp.response(http_client.OK)
    def get(self):
        """
        Retrieve the lobby the requesting player is a member of, or empty dict if no such thing is found.
        Returns a lobby or nothing if no lobby was found.
        """
        player_id = current_user["player_id"]

        lobby = lobbies.get_player_lobby(player_id)

        if lobby:
            _populate_lobby_urls(lobby)

        return lobby or {}

    @bp.arguments(CreateLobbyRequestSchema)
    @bp.response(http_client.CREATED, LobbyResponseSchema)
    def post(self, args):
        """
        Create a lobby for the requesting player.
        Returns a lobby.
        """
        try:
            player_id = current_user["player_id"]

            lobby = lobbies.create_lobby(player_id, args.get("team_capacity"), args.get("team_names"), args.get("lobby_name"), args.get("map_name"))

            _populate_lobby_urls(lobby)

            return lobby
        except lobbies.InvalidRequestException as e:
            log.warning(e.msg)
            return {"error": e.msg}, http_client.BAD_REQUEST

    @bp.arguments(UpdateLobbyRequestSchema)
    @bp.response(http_client.NO_CONTENT)
    def patch(self, args):
        """
        Update lobby info.
        Requesting player must be the lobby host.
        """
        try:
            lobbies.update_lobby(current_user["player_id"], args.get("team_capacity"), args.get("team_names"), args.get("lobby_name"), args.get("map_name"))
        except lobbies.NotFoundException as e:
            log.warning(e.msg)
            return {"error": e.msg}, http_client.NOT_FOUND
        except lobbies.InvalidRequestException as e:
            log.warning(e.msg)
            return {"error": e.msg}, http_client.BAD_REQUEST

    @bp.response(http_client.NO_CONTENT)
    def delete(self):
        """
        Leave or delete a lobby for the requesting player depending on if the player is the host or not.
        """
        try:
            lobbies.delete_or_leave_lobby(current_user["player_id"])
        except lobbies.InvalidRequestException as e:
            log.warning(e.msg)
            return {"error": e.msg}, http_client.BAD_REQUEST


@bp.route("/<string:lobby_id>", endpoint="lobby")
class LobbyAPI(MethodView):

    @bp.response(http_client.NO_CONTENT)
    def post(self, lobby_id: str):
        """
        Start the match for a specific lobby.
        Requesting player must be the lobby host.
        """
        player_id = current_user["player_id"]
        try:
            lobbies.start_lobby_match(player_id, lobby_id)
        except lobbies.NotFoundException as e:
            log.warning(e.msg)
            return {"error": e.msg}, http_client.NOT_FOUND
        except lobbies.InvalidRequestException as e:
            log.warning(e.msg)
            return {"error": e.msg}, http_client.BAD_REQUEST
        except flexmatch.GameliftClientException as e:
            log.error(f"Failed to start lobby match for lobby {lobby_id} on behalf of player {player_id}: Gamelift response:\n{e.debugs}")
            return {"error": e.msg}, http_client.INTERNAL_SERVER_ERROR

@bp.route("/<string:lobby_id>/members", endpoint="members")
class LobbyMembersAPI(MethodView):

    @bp.response(http_client.CREATED)
    def post(self, lobby_id: str):
        """
        Join a specific lobby for the requesting player.
        """
        try:
            player_id = current_user["player_id"]

            lobby = lobbies.join_lobby(player_id, lobby_id)

            _populate_lobby_urls(lobby)

            return lobby
        except lobbies.NotFoundException as e:
            log.warning(e.msg)
            return {"error": e.msg}, http_client.NOT_FOUND
        except lobbies.InvalidRequestException as e:
            log.warning(e.msg)
            return {"error": e.msg}, http_client.BAD_REQUEST

@bp.route("/<string:lobby_id>/members/<int:member_player_id>", endpoint="member")
class LobbyMemberAPI(MethodView):

    @bp.arguments(UpdateLobbyMemberRequestSchema)
    @bp.response(http_client.NO_CONTENT)
    def put(self, args, lobby_id: str, member_player_id: int):
        """
        Update lobby member info, such as team status and ready check.
        Returns the updated lobby.
        """
        try:
            lobbies.update_lobby_member(current_user["player_id"], member_player_id, lobby_id, args.get("team_name"), args.get("ready"))
        except lobbies.NotFoundException as e:
            log.warning(e.msg)
            return {"error": e.msg}, http_client.NOT_FOUND
        except lobbies.InvalidRequestException as e:
            log.warning(e.msg)
            return {"error": e.msg}, http_client.BAD_REQUEST

    @bp.response(http_client.NO_CONTENT)
    def delete(self, lobby_id: str, member_player_id: int):
        """
        Kick the player from the lobby
        """
        try:
            lobbies.kick_member(current_user["player_id"], member_player_id, lobby_id)
        except lobbies.NotFoundException as e:
            log.warning(e.msg)
            return {"error": e.msg}, http_client.NOT_FOUND
        except lobbies.InvalidRequestException as e:
            log.warning(e.msg)
            return {"error": e.msg}, http_client.BAD_REQUEST


@endpoints.register
def endpoint_info(*args):
    ret = {
        "lobbies": url_for("lobbies.lobbies", _external=True)
    }

    if current_user and current_user.get("player_id"):
        player_id = current_user["player_id"]
        player_lobby = lobbies.get_player_lobby(player_id)
        if player_lobby:
            lobby_id = player_lobby["lobby_id"]

            ret["my_lobby"] = url_for("lobbies.lobby", lobby_id=lobby_id, _external=True)
            ret["my_lobby_members"] = url_for("lobbies.members", lobby_id=lobby_id, _external=True)
            ret["my_lobby_member"] = url_for("lobbies.member", lobby_id=lobby_id, member_player_id=player_id, _external=True)

    return ret

# Helpers

def _populate_lobby_urls(lobby: dict):
    lobby_id = lobby["lobby_id"]

    lobby["lobby_url"] = url_for("lobbies.lobby", lobby_id=lobby_id, _external=True)
    lobby["lobby_members_url"] = url_for("lobbies.members", lobby_id=lobby_id, _external=True)
    lobby["lobby_member_url"] = url_for("lobbies.member", lobby_id=lobby_id, member_player_id=current_user["player_id"], _external=True)

    for member in lobby["members"]:
        member["lobby_member_url"] = url_for("lobbies.member", lobby_id=lobby_id, member_player_id=member["player_id"], _external=True)
