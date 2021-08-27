"""
    Orchestration of GameLift/FlexMatch matchmaking
"""

from flask_smorest import Blueprint, abort
from drift.core.extensions.urlregistry import Endpoints
from drift.core.extensions.jwt import requires_roles
from marshmallow import Schema, fields
from flask.views import MethodView
from flask import url_for, request
from drift.core.extensions.jwt import current_user
from driftbase import flexmatch
import http.client as http_client
import logging


bp = Blueprint("flexmatch", __name__, url_prefix="/matchmaking/flexmatch", description="Orchestration of GameLift/FlexMatch matchmaking.")
endpoints = Endpoints()
log = logging.getLogger(__name__)

def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


class FlexMatchPlayerAPIPatchArgs(Schema):
    latency_ms = fields.Float(required=True, metadata=dict(description="Latency between client and the region he's measuring against."))
    region = fields.String(required=True, metadata=dict(description="Which region the latency was measured against."))

class FlexMatchPlayerAPIPostArgs(Schema):
    matchmaker = fields.String(required=True, metadata=dict(description="Which matchmaker (configuration name) to issue the ticket for. "))

class FlexMatchPlayerAPIPutArgs(Schema):
    match_id = fields.String(required=True, metadata=dict(description="The id of the match being accepted/rejected"))
    acceptance = fields.Boolean(required=True, metadata=dict(description="True if match_id is accepted, False otherwise"))

# PlayerAPI
#   PATCH to report latencies
#   GET to fetch a URL to his active ticket
#
# TicketAPI has
#   POST to create a ticket
#   GET to retrieve a given ticket
#   PUT to accept a given match, assuming it matches his ticket
#   DELETE to cancel matchmaking

@bp.route("/<int:player_id>", endpoint="matchmaker")
class FlexMatchPlayerAPI(MethodView):

    @bp.arguments(FlexMatchPlayerAPIPatchArgs)
    def patch(self, args, player_id):
        """
        Add a freshly measured latency value to the player tally.
        Returns a region->avg_latency mapping.
        """
        latency = args.get("latency_ms")
        region = args.get("region")
        if not isinstance(latency, (int, float)) or region not in flexmatch.get_valid_regions():
            abort(http_client.BAD_REQUEST, message="Invalid or missing arguments")
        flexmatch.update_player_latency(player_id, region, latency)
        return flexmatch.get_player_latency_averages(player_id), http_client.OK

    @bp.arguments(FlexMatchPlayerAPIPostArgs)
    def post(self, args, player_id):
        """
        Insert a matchmaking ticket for the requesting player or his party.
        Returns a ticket.
        """
        try:
            ticket = flexmatch.upsert_flexmatch_ticket(player_id, args.get("matchmaker"))
            return ticket, http_client.OK
        except flexmatch.GameliftClientException as e:
            log.error(f"Inserting/updating matchmaking ticket for player {player_id} failed: Gamelift response:\n{e.debugs}")
            return {"error": e.msg}, http_client.INTERNAL_SERVER_ERROR

    def get(self, player_id):
        """
        Retrieve the active matchmaking ticket for the requesting player or his party, or empty dict if no such thing is found.
        """
        ticket = flexmatch.get_player_ticket(player_id)
        return ticket or {}, http_client.OK

    @bp.arguments(FlexMatchPlayerAPIPutArgs)
    def put(self, args, player_id):
        """
        Accept or decline a match
        """
        match_id = args.get("match_id")
        acceptance = args.get("acceptance")
        try:
            flexmatch.update_player_acceptance(player_id, match_id, acceptance)
            return {}, http_client.OK
        except flexmatch.GameliftClientException as e:
            log.error(f"Updating the acceptance status for {match_id} on behalf of player {player_id} failed: Gamelift response:\n{e.debugs}")
            return {"error": e.msg}, http_client.INTERNAL_SERVER_ERROR

    def delete(self, player_id):
        """
        Delete the currently active matchmaking ticket for the requesting player or his party.
        """
        try:
            deleted_ticket = flexmatch.cancel_player_ticket(player_id)
            if deleted_ticket is None:
                return {"Status": "NoTicketFound"}, http_client.OK
            if isinstance(deleted_ticket, str):
                return {"Status": deleted_ticket}, http_client.OK
            return {"Status": "Deleted"}, http_client.OK
        except flexmatch.GameliftClientException as e:
            log.error(f"Cancelling matchmaking ticket for player {player_id} failed: Gamelift response:\n{e.debugs}")
            return {"error": e.msg}, http_client.INTERNAL_SERVER_ERROR

@bp.route("/<string:ticket_id>", endpoint="ticket")  # Use the player_id/party_id as the ticket_id ?
class FlexMatchTicketAPI(MethodView):
    """ RUD API for flexmatch tickets. """
    def get(self, ticket_id):
        """
        Return the stored ticket if a) the calling player is a member of the ticket, either solo or via party or b) caller has 'role_service'
        (TODO define leaner schema for response)
        """
        player_id = current_user.get("player_id")
        if not player_id:
            user_roles = current_user.get("roles")
            if "service" not in user_roles:
                abort(http_client.UNAUTHORIZED, description="You do not have access to this resource.")
        pass

    def delete(self, ticket_id):
        """ Delete and cancel 'ticket_id' if caller is allowed to do so. """
        pass

    def patch(self, ticket_id):
        pass

@bp.route("/events", endpoint="events")
class FlexMatchEventAPI(MethodView):

    @requires_roles("flexmatch_event")
    def put(self):
        flexmatch.process_flexmatch_event(request.json)
        return {}, http_client.OK


@endpoints.register
def endpoint_info(*args):
    from driftbase.api import matchmaking
    if "flexmatch" not in matchmaking.__matchmakers__:
        return {}
    ret = {
        "flexmatch_events": url_for("flexmatch.events")
    }
    if current_user and current_user.get("player_id"):
        ret["my_matchmaker"] = url_for("flexmatch.matchmaker", player_id=current_user["player_id"], _external=True)
    return ret

