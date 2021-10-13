"""
Custom game lobbies for private/direct matches
"""

from flask_smorest import Blueprint
from drift.core.extensions.urlregistry import Endpoints
from marshmallow import Schema, fields
from flask.views import MethodView
from flask_smorest import abort
from flask import url_for
from drift.core.extensions.jwt import current_user
from driftbase import lobbies
import http.client as http_client
import logging
import copy

bp = Blueprint("lobbies", "lobbies", url_prefix="/lobbies", description="Custom game lobbies for private/direct matches.")
endpoints = Endpoints()
log = logging.getLogger(__name__)

def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)

class LobbyMemberResponseSchema(Schema):
    player_id = fields.Integer(metadata=dict(description="The player id of the lobby member."))
    player_name = fields.String(metadata=dict(description="The player name of the lobby member."))
    team_name = fields.String(metadata=dict(description="What team this lobby member is assigned to."))
    ready = fields.Bool(metadata=dict(description="Whether or not this player is ready to start the match."))
    host = fields.Bool(metadata=dict(description="Whether or not this is the lobby host."))
    join_date = fields.String(metadata=dict(description="The UTC timestamp of when the lobby member joined the lobby."))

    lobby_member_url = fields.URL(metadata=dict(description="Lobby member URL"))

class LobbyResponseSchema(Schema):
    lobby_id = fields.String(metadata=dict(description="The id for the lobby."))
    lobby_name = fields.String(metadata=dict(description="The name of the lobby."))
    team_capacity = fields.Integer(metadata=dict(description="How many members can be in one team."))
    team_names = fields.List(fields.String(), metadata=dict(description="The unique names of the teams."))
    map_name = fields.String(allow_none=True, metadata=dict(description="The map name for the lobby."))
    create_date = fields.String(metadata=dict(description="The UTC timestamp of when the lobby was created."))
    start_date = fields.String(allow_none=True, metadata=dict(description="The UTC timestamp of when the lobby match was started."))
    placement_date = fields.String(allow_none=True, metadata=dict(description="The UTC timestamp of when the lobby match placement was started."))
    status = fields.String(metadata=dict(description="The current status of the lobby."))
    members = fields.List(fields.Nested(LobbyMemberResponseSchema), metadata=dict(description="The lobby members."))
    custom_data = fields.String(allow_none=True, metadata=dict(description="Optional custom data for the lobby. Will be forwarded to the match server"))

    connection_string = fields.String(allow_none=True, metadata=dict(description="The IP and port of the lobby match if it has started."))
    connection_options = fields.String(allow_none=True, metadata=dict(description="Connection options for the requesting player"))

    lobby_url = fields.Url(metadata=dict(description="URL for the lobby."))
    lobby_members_url = fields.Url(metadata=dict(description="URL for the lobby members."))
    lobby_member_url = fields.Url(metadata=dict(description="Lobby member URL for the player issuing the request."))

    lobby_match_placement_url = fields.Url(metadata=dict(description="URL for the lobby match placement if there is an active match placement for the lobby"))


@bp.route("/", endpoint="lobbies")
class LobbiesAPI(MethodView):
    class CreateLobbyRequestSchema(Schema):
        team_capacity = fields.Integer(required=True, metadata=dict(description="How many members can be in one team."))
        team_names = fields.List(fields.String(), required=True, metadata=dict(description="The unique names of the teams."))
        lobby_name = fields.String(required=False, metadata=dict(description="Optional initial name of the lobby."))
        map_name = fields.String(required=False, metadata=dict(description="Optional initial map name for the lobby."))
        custom_data = fields.String(required=False, metadata=dict(description="Optional custom data for the lobby. Will be forwarded to the match server"))

    @bp.response(http_client.OK, LobbyResponseSchema)
    def get(self):
        """
        Retrieve the lobby the requesting player is a member of.
        Returns a lobby.
        """
        player_id = current_user["player_id"]



        try:
            lobby = lobbies.get_player_lobby(player_id)
            return _add_lobby_urls(lobby)
        except lobbies.NotFoundException as e:
            abort(http_client.NOT_FOUND, message=e.msg)
        except lobbies.UnauthorizedException as e:
            abort(http_client.UNAUTHORIZED, message=e.msg)
        except lobbies.ConflictException as e:
            abort(http_client.CONFLICT, message=e.msg)

    @bp.arguments(CreateLobbyRequestSchema)
    @bp.response(http_client.CREATED, LobbyResponseSchema)
    def post(self, args):
        """
        Create a lobby for the requesting player.
        Returns a lobby.
        """
        try:
            player_id = current_user["player_id"]

            lobby = lobbies.create_lobby(
                player_id,
                args.get("team_capacity"),
                args.get("team_names"),
                args.get("lobby_name"),
                args.get("map_name"),
                args.get("custom_data"),
            )

            return _add_lobby_urls(lobby)
        except lobbies.InvalidRequestException as e:
            abort(http_client.BAD_REQUEST, message=e.msg)
        except lobbies.ConflictException as e:
            abort(http_client.CONFLICT, message=e.msg)

@bp.route("/<string:lobby_id>", endpoint="lobby")
class LobbyAPI(MethodView):
    class UpdateLobbyRequestSchema(Schema):
        team_capacity = fields.Integer(required=False, metadata=dict(description="How many members can be in one team."))
        team_names = fields.List(fields.String(), required=False, metadata=dict(description="The unique names of the teams."))
        lobby_name = fields.String(required=False, metadata=dict(description="Optional initial name of the lobby."))
        map_name = fields.String(required=False, metadata=dict(description="Optional initial map name for the lobby."))
        custom_data = fields.String(required=False, metadata=dict(description="Optional custom data for the lobby. Will be forwarded to the match server"))

    @bp.response(http_client.OK, LobbyResponseSchema)
    def get(self, lobby_id: str):
        """
        Retrieve a specific lobby if the requesting player is a member of the lobby.
        Returns a lobby.
        """
        player_id = current_user["player_id"]

        try:
            lobby = lobbies.get_player_lobby(player_id, lobby_id)
            return _add_lobby_urls(lobby)
        except lobbies.NotFoundException as e:
            abort(http_client.NOT_FOUND, message=e.msg)
        except lobbies.UnauthorizedException as e:
            abort(http_client.UNAUTHORIZED, message=e.msg)
        except lobbies.ConflictException as e:
            abort(http_client.CONFLICT, message=e.msg)

    @bp.arguments(UpdateLobbyRequestSchema)
    @bp.response(http_client.NO_CONTENT)
    def patch(self, args, lobby_id: str):
        """
        Update lobby info.
        Requesting player must be the lobby host.
        """
        try:
            lobbies.update_lobby(
                current_user["player_id"],
                lobby_id,
                args.get("team_capacity"),
                args.get("team_names"),
                args.get("lobby_name"),
                args.get("map_name"),
                args.get("custom_data"),
            )
        except lobbies.NotFoundException as e:
            abort(http_client.NOT_FOUND, message=e.msg)
        except lobbies.InvalidRequestException as e:
            abort(http_client.BAD_REQUEST, message=e.msg)
        except lobbies.UnauthorizedException as e:
            abort(http_client.UNAUTHORIZED, message=e.msg)
        except lobbies.ConflictException as e:
            abort(http_client.CONFLICT, message=e.msg)

    @bp.response(http_client.NO_CONTENT)
    def delete(self, lobby_id: str):
        """
        Delete a lobby.
        Requesting player must be the lobby host
        """
        try:
            lobbies.delete_lobby(current_user["player_id"], lobby_id)
        except lobbies.NotFoundException:
            pass
        except lobbies.InvalidRequestException as e:
            abort(http_client.BAD_REQUEST, message=e.msg)
        except lobbies.UnauthorizedException as e:
            abort(http_client.UNAUTHORIZED, message=e.msg)
        except lobbies.ConflictException as e:
            abort(http_client.CONFLICT, message=e.msg)

@bp.route("/<string:lobby_id>/members", endpoint="members")
class LobbyMembersAPI(MethodView):

    @bp.response(http_client.CREATED, LobbyResponseSchema)
    def post(self, lobby_id: str):
        """
        Join a specific lobby for the requesting player.
        """
        try:
            player_id = current_user["player_id"]

            lobby = lobbies.join_lobby(player_id, lobby_id)

            return _add_lobby_urls(lobby)
        except lobbies.NotFoundException as e:
            abort(http_client.NOT_FOUND, message=e.msg)
        except lobbies.InvalidRequestException as e:
            abort(http_client.BAD_REQUEST, message=e.msg)
        except lobbies.ConflictException as e:
            abort(http_client.CONFLICT, message=e.msg)

@bp.route("/<string:lobby_id>/members/<int:member_player_id>", endpoint="member")
class LobbyMemberAPI(MethodView):
    class UpdateLobbyMemberRequestSchema(Schema):
        team_name = fields.String(allow_none=True, dump_default=None, metadata=dict(description="What team this lobby member is assigned to."))
        ready = fields.Bool(allow_none=True, dump_default=False, metadata=dict(description="Whether or not this player is ready to start the match."))

    @bp.arguments(UpdateLobbyMemberRequestSchema)
    @bp.response(http_client.NO_CONTENT)
    def put(self, args, lobby_id: str, member_player_id: int):
        """
        Update lobby member info, such as team status and ready check.
        Returns the updated lobby.
        """
        try:
            lobbies.update_lobby_member(
                current_user["player_id"],
                member_player_id, lobby_id,
                args.get("team_name"),
                args.get("ready")
            )
        except lobbies.NotFoundException as e:
            abort(http_client.NOT_FOUND, message=e.msg)
        except lobbies.InvalidRequestException as e:
            abort(http_client.BAD_REQUEST, message=e.msg)
        except lobbies.UnauthorizedException as e:
            abort(http_client.UNAUTHORIZED, message=e.msg)
        except lobbies.ConflictException as e:
            abort(http_client.CONFLICT, message=e.msg)

    @bp.response(http_client.NO_CONTENT)
    def delete(self, lobby_id: str, member_player_id: int):
        """
        Leave the lobby or kick a player from the lobby
        """
        player_id = current_user["player_id"]
        try:
            if player_id == member_player_id:
                lobbies.leave_lobby(player_id, lobby_id)
            else:
                lobbies.kick_member(player_id, member_player_id, lobby_id)
        except lobbies.NotFoundException as e:
            abort(http_client.NOT_FOUND, message=e.msg)
        except lobbies.InvalidRequestException as e:
            abort(http_client.BAD_REQUEST, message=e.msg)
        except lobbies.UnauthorizedException as e:
            abort(http_client.UNAUTHORIZED, message=e.msg)
        except lobbies.ConflictException as e:
            abort(http_client.CONFLICT, message=e.msg)

@endpoints.register
def endpoint_info(*args):
    ret = {
        "lobbies": url_for("lobbies.lobbies", _external=True),
    }

    # Lobby members template
    url = url_for("lobbies.members", lobby_id="lobby_id", _external=True)
    url = url.replace("lobby_id", "{lobby_id}")

    ret["template_lobby_members"] = url

    # Lobby member template
    url = url_for("lobbies.member", lobby_id="lobby_id", member_player_id=1337, _external=True)
    url = url.replace("lobby_id", "{lobby_id}")
    url = url.replace("1337", "{lobby_member_id}")

    ret["template_lobby_member"] = url

    return ret

# Helpers

def _add_lobby_urls(lobby: dict):
    lobby_id = lobby["lobby_id"]
    lobby_with_urls = copy.deepcopy(lobby)

    lobby_with_urls["lobby_url"] = url_for("lobbies.lobby", lobby_id=lobby_id, _external=True)
    lobby_with_urls["lobby_members_url"] = url_for("lobbies.members", lobby_id=lobby_id, _external=True)
    lobby_with_urls["lobby_member_url"] = url_for("lobbies.member", lobby_id=lobby_id, member_player_id=current_user["player_id"], _external=True)

    for member in lobby_with_urls["members"]:
        member["lobby_member_url"] = url_for("lobbies.member", lobby_id=lobby_id, member_player_id=member["player_id"], _external=True)

    lobby_status = lobby["status"]
    placement_id = lobby.get("placement_id", None)
    if placement_id and lobby_status == "starting":
        lobby_with_urls["lobby_match_placement_url"] = url_for("match-placements.match-placement", match_placement_id=placement_id, _external=True)

    return lobby_with_urls