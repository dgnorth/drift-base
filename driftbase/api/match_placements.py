"""
    Custom game lobbies for private/direct matches
"""

from flask_smorest import Blueprint
from drift.core.extensions.urlregistry import Endpoints
from marshmallow import Schema, fields
from flask.views import MethodView
from flask import url_for
from drift.core.extensions.jwt import current_user
from driftbase import match_placements, lobbies, flexmatch
import http.client as http_client
import logging

bp = Blueprint("match-placements", "match-placements", url_prefix="/match-placements", description="Placements for pending matches.")
endpoints = Endpoints()
log = logging.getLogger(__name__)

def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    app.messagebus.register_consumer(match_placements.process_match_message, "match")
    app.messagebus.register_consumer(match_placements.process_gamelift_queue_event, "gamelift_queue")
    endpoints.init_app(app)

class CreateMatchPlacementRequestSchema(Schema):
    lobby_id = fields.String(required=False, metadata=dict(description="Create a match placement for a lobby."))

class MatchPlacementResponseSchema(Schema):
    placement_id = fields.String(metadata=dict(description="The id of the match placement."))
    player_id = fields.Integer(metadata=dict(description="The id of the player who issued the match placement."))
    match_provider = fields.String(metadata=dict(description="The service that is providing the match."))
    status = fields.String(metadata=dict(description="The match placement status."))

    lobby_id = fields.String(allow_none=True, metadata=dict(description="The lobby id if this is a lobby match"))

    match_placement_url = fields.Url(metadata=dict(description="The URL for the match placement"))

@bp.route("/", endpoint="match-placements")
class MatchPlacementsAPI(MethodView):

    @bp.response(http_client.OK, MatchPlacementResponseSchema)
    def get(self):
        """
        Gets the current match placement for the requesting player.
        Returns a match placement.
        """
        try:
            player_id = current_user["player_id"]
            match_placement = match_placements.get_player_match_placement(player_id)

            match_placement["match_placement_url"] = url_for("match-placements.match-placement", match_placement_id=match_placement["placement_id"], _external=True)

            return match_placement
        except lobbies.NotFoundException as e:
            return {"error": e.msg}, http_client.NOT_FOUND
        except lobbies.UnauthorizedException as e:
            return {"error": e.msg}, http_client.UNAUTHORIZED

    @bp.arguments(CreateMatchPlacementRequestSchema)
    @bp.response(http_client.CREATED, MatchPlacementResponseSchema)
    def post(self, args):
        """
        Create a match placement for the requesting player.
        Returns a match placement.
        """
        player_id = current_user["player_id"]
        try:
            match_placement = match_placements.start_lobby_match_placement(player_id, args.get("lobby_id"))

            match_placement["match_placement_url"] = url_for("match-placements.match-placement", match_placement_id=match_placement["placement_id"], _external=True)

            return match_placement
        except lobbies.InvalidRequestException as e:
            return {"error": e.msg}, http_client.BAD_REQUEST
        except flexmatch.GameliftClientException as e:
            log.error(f"Failed to start match placement for player '{player_id}': Gamelift response:\n'{e.debugs}'")
            return {"error": e.msg}, http_client.INTERNAL_SERVER_ERROR

@bp.route("/<string:match_placement_id>", endpoint="match-placement")
class MatchPlacementAPI(MethodView):

    @bp.response(http_client.OK, MatchPlacementResponseSchema)
    def get(self, match_placement_id: str):
        """
        Gets a match placement for the requesting player.
        Returns a match placement.
        """
        try:
            player_id = current_user["player_id"]
            match_placement = match_placements.get_player_match_placement(player_id, match_placement_id)

            match_placement["match_placement_url"] = url_for("match-placements.match-placement", match_placement_id=match_placement_id, _external=True)

            return match_placement
        except lobbies.NotFoundException as e:
            return {"error": f"Match placement '{match_placement_id}' not found"}, http_client.NOT_FOUND
        except lobbies.UnauthorizedException as e:
            return {"error": e.msg}, http_client.UNAUTHORIZED

    @bp.response(http_client.NO_CONTENT)
    def delete(self, match_placement_id: str):
        """
        Stop a match placement issued by the requesting player
        """
        player_id = current_user["player_id"]

        try:
            match_placements.stop_player_match_placement(player_id, match_placement_id)
        except lobbies.NotFoundException:
            pass
        except lobbies.InvalidRequestException as e:
            return {"error": e.msg}, http_client.BAD_REQUEST
        except flexmatch.GameliftClientException as e:
            log.error(f"Failed to stop match placement for player '{player_id}': Gamelift response:\n'{e.debugs}'")
            return {"error": e.msg}, http_client.INTERNAL_SERVER_ERROR
        except lobbies.UnauthorizedException as e:
            return {"error": e.msg}, http_client.UNAUTHORIZED


@endpoints.register
def endpoint_info(*args):
    ret = {
        "match_placements": url_for("match-placements.match-placements", _external=True)
    }

    if current_user and current_user.get("player_id"):
        player_id = current_user["player_id"]
        try:
            player_placement = match_placements.get_player_match_placement(player_id)
            if player_placement:
                ret["my_match_placement"] = url_for("match-placements.match-placement", match_placement_id=player_placement["placement_id"], _external=True)
        except lobbies.NotFoundException:
            pass
        except lobbies.UnauthorizedException as e:
            log.error(e.msg)

    return ret
