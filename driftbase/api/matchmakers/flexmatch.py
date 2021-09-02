"""
    Orchestration of GameLift/FlexMatch matchmaking
"""

# Matchmakers API @ /matchmakers/
#   GET To retrive available matchmakers
#
# PlayerAPI @ /matchmakers/flexmatch/<player_id>/ - endpoint "flexmatch"
#   PATCH to report latencies
#   GET to fetch average latency per region
#
# TicketsAPI @ /matchmakers/flexmatch/tickets/ - endpoint "flexmatch_tickets"
#   GET to fetch a URL to players active ticket(s)
#   POST to create a ticket
#
# TicketAPI @ /matchmakers/flexmatch/ticket/<ticket_id>/
#   GET to retrieve a given ticket
#   PATCH to accept a given match, assuming it matches his ticket
#   DELETE to cancel matchmaking ticket
#
# EventAPI @ /matchmakers/flexmatch/events/ - endpoint "flexmatch_events"
#   PUT exposed to AWS EventBridge to publish flexmatch events into Drift
#
# QueueEventAPI @ /matchmakers/flexmatch/queue_events/ - endpoint "queue_events"
#   PUT exposed to AWS EventBridge to publish flexmatch queue events

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


bp = Blueprint("flexmatch", __name__, url_prefix="/matchmakers/flexmatch", description="Orchestration of GameLift/FlexMatch matchmakers.")
endpoints = Endpoints()
log = logging.getLogger(__name__)

def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


class FlexMatchLatencySchema(Schema):
    latencies = fields.Mapping(keys=fields.String(), values=fields.Integer(), required=True,
                               metadata=dict(description="Latency between client and the region he's measuring against.")
                               )

@bp.route("/<int:player_id>", endpoint="matchmaker")
class FlexMatchPlayerAPI(MethodView):

    @bp.arguments(FlexMatchLatencySchema)
    @bp.response(http_client.OK, FlexMatchLatencySchema)  # The response schema is the same as the input schema for now
    def patch(self, args, player_id):
        """
        Add a freshly measured latency value to the player tally.
        Returns a region->avg_latency mapping.
        """
        for region, latency in args.get("latencies", {}).items():
            if not isinstance(latency, (int, float)) or region not in flexmatch.get_valid_regions():
                abort(http_client.BAD_REQUEST, message="Invalid or missing arguments")
            flexmatch.update_player_latency(player_id, region, latency)
        return {"latencies": flexmatch.get_player_latency_averages(player_id)}

    @bp.response(http_client.OK, FlexMatchLatencySchema)
    def get(self, player_id):
        """
        Return the calculated averages of the player latencies per region.
        """
        return {"latencies": flexmatch.get_player_latency_averages(player_id)}


class FlexMatchTicketsAPIPostArgs(Schema):
    matchmaker = fields.String(required=True, metadata=dict(description="Which matchmaker (configuration name) to issue the ticket for. "))

class FlexMatchTicketsAPIGetResponse(Schema):
    ticket_url = fields.String()
    ticket_id = fields.String()
    ticket_status = fields.String()

@bp.route("/tickets/", endpoint="tickets")
class FlexMatchTicketsAPI(MethodView):

    @staticmethod
    @bp.response(http_client.OK, FlexMatchTicketsAPIGetResponse)
    def get():
        """
        Returns the URL to the active matchmaking ticket for the requesting player or his party, or empty dict if no such thing is found.
        """
        player_id = current_user.get("player_id")
        ticket = flexmatch.get_player_ticket(player_id)
        if ticket:
            return {
                       "ticket_url": url_for("flexmatch.ticket", ticket_id=ticket["TicketId"]),
                       "ticket_id": ticket["TicketId"],
                       "ticket_status": ticket["Status"]
                   }, http_client.OK
        return {}, http_client.NOT_FOUND

    @staticmethod
    @bp.arguments(FlexMatchTicketsAPIPostArgs)
    @bp.response(http_client.CREATED, FlexMatchTicketsAPIGetResponse)
    def post(args):
        """
        Insert a matchmaking ticket for the requesting player or his party.
        Returns a ticket.
        """
        try:
            player_id = current_user.get("player_id")
            ticket = flexmatch.upsert_flexmatch_ticket(player_id, args.get("matchmaker"))
            return {
                "ticket_url": url_for("flexmatch.ticket", ticket_id=ticket["TicketId"], _external=True),
                "ticket_id": ticket["TicketId"],
                "ticket_status": ticket["Status"]
            }
        except flexmatch.GameliftClientException as e:
            player_id = current_user.get("player_id", "UNKNOWN")
            log.error(
                f"Inserting/updating matchmaking ticket for player {player_id} failed: Gamelift response:\n{e.debugs}")
            return {"error": e.msg}, http_client.INTERNAL_SERVER_ERROR


class FlexMatchTicketAPIPatchArgs(Schema):
    match_id = fields.String(required=True, metadata=dict(description="The id of the match being accepted/rejected"))
    acceptance = fields.Boolean(required=True, metadata=dict(description="True if match_id is accepted, False otherwise"))

@bp.route("/tickets/<string:ticket_id>", endpoint="ticket")
class FlexMatchTicketAPI(MethodView):
    """ RUD API for flexmatch tickets. """

    @staticmethod
    def get(ticket_id):
        """
        Return the stored ticket if the calling player is a member of the ticket, either solo or via party
        (TODO define leaner schema for response)
        """
        player_id = current_user.get("player_id")
        if player_id:
            ticket = flexmatch.get_player_ticket(player_id)
            if ticket and ticket["TicketId"] == ticket_id:
                return ticket, http_client.OK
            return {}, http_client.NOT_FOUND
        abort(http_client.UNAUTHORIZED)

    @staticmethod
    def delete(ticket_id):
        """ Delete and cancel 'ticket_id' if caller is allowed to do so. """
        player_id = current_user.get("player_id")
        if player_id:
            try:
                deleted_ticket = flexmatch.cancel_player_ticket(player_id, ticket_id)
                if deleted_ticket is None:
                    return {"Status": "NoTicketFound"}, http_client.OK
                if isinstance(deleted_ticket, str):
                    return {"Status": deleted_ticket}, http_client.OK
                return {"Status": "Deleted"}, http_client.OK
            except flexmatch.GameliftClientException as e:
                log.error(f"Cancelling matchmaking ticket for player {player_id} failed: Gamelift response:\n{e.debugs}")
                return {"error": e.msg}, http_client.INTERNAL_SERVER_ERROR
        abort(http_client.UNAUTHORIZED)

    @bp.arguments(FlexMatchTicketAPIPatchArgs)
    def patch(self, args, ticket_id):
        """
        Accept or decline a match
        """
        match_id = args.get("match_id")
        acceptance = args.get("acceptance")
        player_id = current_user.get("player_id")
        try:
            flexmatch.update_player_acceptance(ticket_id, player_id, match_id, acceptance)
            return {}, http_client.OK
        except flexmatch.GameliftClientException as e:
            log.error(
                f"Updating the acceptance status for {match_id} on behalf of player {player_id} failed: Gamelift response:\n{e.debugs}")
            return {"error": e.msg}, http_client.INTERNAL_SERVER_ERROR


@bp.route("/events", endpoint="events")
class FlexMatchEventAPI(MethodView):

    @requires_roles("flexmatch_event")
    def put(self):
        flexmatch.process_flexmatch_event(request.json)
        return {}, http_client.OK

@bp.route("/queue_events", endpoint="queue_events")
class FlexMatchQueueEventAPI(MethodView):

    @requires_roles("flexmatch_event")
    def put(self):
        # TODO: implement handling
        log.log(f"Queue event: {request.json}")
        return {}, http_client.OK

@endpoints.register
def endpoint_info(*args):
    from driftbase.api import matchmakers
    if "flexmatch" not in matchmakers.MATCHMAKER_MODULES:
        return {}
    ret = {
        "flexmatch_events": url_for("flexmatch.events"),
        "flexmatch_queue": url_for("flexmatch.queue_events"),
        "flexmatch_tickets": url_for("flexmatch.tickets")
    }
    if current_user and current_user.get("player_id"):
        ret["my_flexmatch"] = url_for("flexmatch.matchmaker", player_id=current_user["player_id"], _external=True)
        player_ticket = flexmatch.get_player_ticket(current_user["player_id"])
        if player_ticket:
            ret["my_flexmatch_ticket"] = url_for("flexmatch.ticket", ticket_id=player_ticket["TicketId"])
    return ret

