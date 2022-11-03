"""
    Orchestration of GameLift/FlexMatch matchmaking
"""

# Matchmakers API @ /matchmakers/
#   GET To retrieve available matchmakers
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
# QueueEventAPI @ /matchmakers/flexmatch/queue-events/ - endpoint "queue-events"
#   PUT exposed to AWS EventBridge to publish flexmatch queue events

from drift.blueprint import Blueprint, abort
from drift.core.extensions.urlregistry import Endpoints
from drift.core.extensions.jwt import requires_roles
from marshmallow import Schema, fields
from flask.views import MethodView
from flask import url_for, request, current_app
from drift.core.extensions.jwt import current_user
from driftbase import flexmatch
import http.client as http_client
import logging

bp = Blueprint("flexmatch", __name__, url_prefix="/matchmakers/flexmatch")
endpoints = Endpoints()
log = logging.getLogger(__name__)


def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)
    app.messagebus.register_consumer(flexmatch.handle_party_event, "parties")
    app.messagebus.register_consumer(flexmatch.handle_client_event, "client")
    app.messagebus.register_consumer(flexmatch.handle_match_event, "match")
    endpoints.init_app(app)


@bp.route("/regions/", endpoint="regions")
class FlexMatchPlayerAPI(MethodView):
    class FlexMatchRegionsSchema(Schema):
        regions = fields.List(fields.String(), metadata=dict(description="The list of regions."))

    @bp.response(http_client.OK, FlexMatchRegionsSchema)
    def get(self):
        """
        Returns the valid regions the client should ping.
        """
        return {"regions": flexmatch.get_valid_regions()}


@bp.route("/<int:player_id>", endpoint="matchmaker")
class FlexMatchPlayerAPI(MethodView):
    class FlexMatchLatencySchema(Schema):
        latencies = fields.Mapping(keys=fields.String(), values=fields.Integer(), required=True,
                                   metadata=dict(description="Latency between client and the region he's measuring against."))

    @bp.arguments(FlexMatchLatencySchema)
    @bp.response(http_client.OK, FlexMatchLatencySchema)  # The response schema is the same as the input schema for now
    def patch(self, args, player_id):
        """
        Add a freshly measured latency value to the player tally.
        Returns a region->avg_latency mapping.
        """
        for region, latency in args.get("latencies", {}).items():
            if not isinstance(latency, (int, float)):
                abort(http_client.BAD_REQUEST, message="Invalid or missing arguments")
            flexmatch.update_player_latency(player_id, region, latency)
        return {"latencies": flexmatch.get_player_latency_averages(player_id)}

    @bp.response(http_client.OK, FlexMatchLatencySchema)
    def get(self, player_id):
        """
        Return the calculated averages of the player latencies per region.
        """
        return {"latencies": flexmatch.get_player_latency_averages(player_id)}


@bp.route("/tickets/", endpoint="tickets")
class FlexMatchTicketsAPI(MethodView):
    class FlexMatchTicketsAPIPostArgs(Schema):
        matchmaker = fields.String(required=True, metadata=dict(
            description="Which matchmaker (configuration name) to issue the ticket for. "))
        extras = fields.Mapping(required=False, keys=fields.Integer(), values=fields.Mapping(), metadata=dict(
            description="Extra matchmaking data to pass along to flexmatch, key'd on player_id"
        ))

    class FlexMatchTicketsAPIGetResponse(Schema):
        ticket_url = fields.String()
        ticket_id = fields.String()
        ticket_status = fields.String()
        matchmaker = fields.String()

    @staticmethod
    @bp.response(http_client.OK, FlexMatchTicketsAPIGetResponse)
    def get():
        """
        Returns the URL to the active matchmaking ticket for the requesting player or his party, or empty dict if no
        such thing is found.
        """
        player_id = current_user.get("player_id")
        ticket = flexmatch.get_player_ticket(player_id)
        if ticket:
            return {
                "ticket_url": url_for("flexmatch.ticket", ticket_id=ticket["TicketId"], _external=True),
                "ticket_id": ticket["TicketId"],
                "ticket_status": ticket["Status"],
                "matchmaker": ticket["ConfigurationName"],
            }
        return abort(http_client.NOT_FOUND, message="No ticket found")

    @staticmethod
    @bp.arguments(FlexMatchTicketsAPIPostArgs)
    @bp.response(http_client.CREATED, FlexMatchTicketsAPIGetResponse)
    def post(args):
        """
        Insert a matchmaking ticket for the requesting player or his party.
        Returns a ticket.
        """
        player_id = current_user.get("player_id")
        try:
            ticket = flexmatch.upsert_flexmatch_ticket(player_id, args.get("matchmaker"), args.get("extras", {}))
            return {
                "ticket_url": url_for("flexmatch.ticket", ticket_id=ticket["TicketId"], _external=True),
                "ticket_id": ticket["TicketId"],
                "ticket_status": ticket["Status"],
                "matchmaker": ticket["ConfigurationName"],
            }
        except flexmatch.GameliftClientException as e:
            player_id = player_id or "UNKNOWN"
            log.error(
                f"Inserting/updating matchmaking ticket for player {player_id} failed: Gamelift response:\n{e.debugs}")
            return abort(http_client.INTERNAL_SERVER_ERROR, message=e.msg)
        except flexmatch.TicketConflict as e:
            player_id = player_id or "UNKNOWN"
            log.error(
                f"Player {player_id} attempted to start matchmaking while older ticket is still being cancelled.\n{e.debugs}")
            return abort(http_client.CONFLICT, message=e.msg)


@bp.route("/tickets/<string:ticket_id>", endpoint="ticket")
class FlexMatchTicketAPI(MethodView):
    """ RUD API for flexmatch tickets. """

    class FlexMatchTicketAPIPatchArgs(Schema):
        match_id = fields.String(required=True, metadata=dict(description="The id of the match being accepted/rejected"))
        acceptance = fields.Boolean(required=True, metadata=dict(description="True if match_id is accepted, False otherwise"))

    class FlexMatchTicketAPIDeleteResponse(Schema):
        status = fields.String(required=True, metadata=dict(description="The status of the ticket after the operation"))

    class FlexMatchTicketAPIGetResponse(Schema):
        ticket_id = fields.String(required=True)
        ticket_status = fields.String(required=True)
        configuration_name = fields.String(required=True)
        players = fields.List(fields.Mapping(keys=fields.String(), values=fields.String()))
        connection_info = fields.Mapping(keys=fields.String(), values=fields.String())
        match_status = fields.String(required=False)

    @staticmethod
    @bp.response(http_client.OK, FlexMatchTicketAPIGetResponse)
    def get(ticket_id):
        """
        Return the stored ticket if the calling player is a member of the ticket, either solo or via party
        """
        player_id = current_user.get("player_id")
        if player_id:
            ticket = flexmatch.get_player_ticket(player_id)
            if ticket and ticket["TicketId"] == ticket_id:
                ret = dict(
                    ticket_id=ticket["TicketId"],
                    ticket_status=ticket["Status"],
                    configuration_name=ticket["ConfigurationName"],
                    players=ticket["Players"],
                    connection_info=ticket.get("GameSessionConnectionInfo"),
                    match_status=ticket.get("MatchStatus")
                )
                return ret
            return abort(http_client.NOT_FOUND, message=f"Ticket {ticket_id} not found")
        abort(http_client.UNAUTHORIZED)

    @staticmethod
    @bp.response(http_client.OK, FlexMatchTicketAPIDeleteResponse)
    def delete(ticket_id):
        """ Delete and cancel 'ticket_id' if caller is allowed to do so. """
        player_id = current_user.get("player_id")
        if player_id:
            try:
                deleted_ticket = flexmatch.cancel_active_ticket(player_id, ticket_id)
                if deleted_ticket is None:
                    return {"status": "NoTicketFound"}
                if isinstance(deleted_ticket, str):
                    return {"status": deleted_ticket}
                return {"status": "Deleted"}
            except flexmatch.GameliftClientException as e:
                log.error(f"Cancelling matchmaking ticket for player {player_id} failed: Gamelift response:\n{e.debugs}")
                return abort(http_client.INTERNAL_SERVER_ERROR, message=e.msg)
        abort(http_client.UNAUTHORIZED)

    @bp.arguments(FlexMatchTicketAPIPatchArgs)
    @bp.response(http_client.OK)
    def patch(self, args, ticket_id):
        """
        Accept or decline a match
        """
        match_id = args.get("match_id")
        acceptance = args.get("acceptance")
        player_id = current_user.get("player_id")
        try:
            flexmatch.update_player_acceptance(ticket_id, player_id, match_id, acceptance)
            return {}
        except flexmatch.GameliftClientException as e:
            log.error(
                f"Updating the acceptance status for {match_id} on behalf of player {player_id} failed: Gamelift response:\n{e.debugs}")
            return abort(http_client.INTERNAL_SERVER_ERROR, message=e.msg)


@bp.route("/events", endpoint="events")
class FlexMatchEventAPI(MethodView):

    @requires_roles("flexmatch_event")
    def put(self):
        flexmatch.process_flexmatch_event(request.json)
        return {}, http_client.OK


@bp.route("/queue-events", endpoint="queue-events")
class FlexMatchQueueEventAPI(MethodView):

    @requires_roles("flexmatch_event")
    @bp.response(http_client.OK)
    def put(self):
        # TODO: Have publish message consumer do the try/except in Drift lib
        log.info(f"Queue event: {request.json}")
        try:
            current_app.extensions["messagebus"].publish_message("gamelift_queue", request.json)
        except Exception as e:
            log.error(f"Error processing queue event: {e}")

        return {}


@endpoints.register
def endpoint_info(*args):
    from driftbase.api import matchmakers
    if "flexmatch" not in matchmakers.MATCHMAKER_MODULES:
        return {}
    ret = {
        "flexmatch_events": url_for("flexmatch.events", _external=True),
        "flexmatch_queue": url_for("flexmatch.queue-events", _external=True),
        "flexmatch_tickets": url_for("flexmatch.tickets", _external=True),
        "flexmatch_regions": url_for("flexmatch.regions", _external=True),
    }
    if current_user and current_user.get("player_id"):
        ret["my_flexmatch"] = url_for("flexmatch.matchmaker", player_id=current_user["player_id"], _external=True)
        player_ticket = flexmatch.get_player_ticket(current_user["player_id"])
        if player_ticket:
            ret["my_flexmatch_ticket"] = url_for("flexmatch.ticket", ticket_id=player_ticket["TicketId"], _external=True)
    return ret
