import logging
import datetime

from six.moves import http_client

from flask import url_for, request, g, jsonify
from flask.views import MethodView
import marshmallow as ma
from marshmallow import validates, ValidationError, pre_dump
from marshmallow_sqlalchemy import ModelSchema
from flask_smorest import Blueprint, abort, utils

from drift.core.extensions.schemachecker import simple_schema_request
from drift.core.extensions.jwt import requires_roles
from drift.utils import Url

from driftbase.players import log_event, can_edit_player, create_ticket
from driftbase.models.db import Ticket

log = logging.getLogger(__name__)

bp = Blueprint("player_tickets", __name__, url_prefix='/players')

class TicketPatchRequestSchema(ma.Schema):
    journal_id = ma.fields.Integer()

class TicketSchema(ModelSchema):
    class Meta:
        model = Ticket
        #exclude = ('player_summary',)

    player_url = Url(
        'players.entry',
        doc="Fully qualified URL of the player resource",
        player_id='<player_id>',
    )

    url = Url(
        'player_tickets.entry',
        doc="Fully qualified URL of the player resource",
        player_id='<player_id>',
        ticket_id='<ticket_id>'
    )
    # cannot use Url() because sometimes there is no issuer_id
    issuer_url = ma.fields.String()

    @pre_dump
    def populate_urls(self, obj, many=False):
        if obj.issuer_id:
            obj.issuer_url = (
                url_for(
                    'players.entry',
                    player_id=obj.issuer_id,
                   _external=True
                )
            )
        return obj


@bp.route("/<int:player_id>/tickets", endpoint="list")
class TicketsEndpoint(MethodView):

    @bp.response(TicketSchema(many=True))
    def get(self, player_id):
        """
        List of tickets

        Get a list of outstanding tickets for the player
        """
        can_edit_player(player_id)
        tickets = g.db.query(Ticket)\
            .filter(Ticket.player_id == player_id, Ticket.used_date == None)  # noqa: E711
        return tickets

    @requires_roles("service")
    @simple_schema_request({
        "issuer_id": {"type": "number"},
        "ticket_type": {"type": "string"},
        "external_id": {"type": "string"},
        "details": {"type": "object"},
    }, required=["ticket_type"])
    def post(self, player_id):
        """
        Create ticket

        Create a ticket for a player. Only available to services
        """
        args = request.json
        issuer_id = args.get("issuer_id")
        ticket_type = args.get("ticket_type")
        details = args.get("details")
        external_id = args.get("external_id")
        ticket_id = create_ticket(player_id, issuer_id, ticket_type, details, external_id)
        ticket_url = url_for("player_tickets.entry", ticket_id=ticket_id,
                             player_id=player_id, _external=True)
        ret = {
            "ticket_id": ticket_id,
            "ticket_url": ticket_url
        }
        response_header = {
            "Location": ticket_url,
        }

        return jsonify(ret), http_client.CREATED, response_header


def get_ticket(player_id, ticket_id):
    ticket = g.db.query(Ticket) \
                 .filter(Ticket.player_id == player_id,
                         Ticket.ticket_id == ticket_id) \
                 .first()
    return ticket


@bp.route("/<int:player_id>/tickets/<int:ticket_id>", endpoint="entry")
class TicketEndpoint(MethodView):

    @bp.response(TicketSchema())
    def get(self, player_id, ticket_id):
        """
        Get specific ticket

        Get information about any past or ongoing battle initiated by
        the current player against the other player
        Say what?
        """
        if not can_edit_player(player_id):
            abort(http_client.METHOD_NOT_ALLOWED, message="That is not your player!")

        ticket = get_ticket(player_id, ticket_id)
        if not ticket:
            abort(404, message="Ticket was not found")
        return ticket

    @bp.arguments(TicketPatchRequestSchema)
    @bp.response(TicketSchema())
    def patch(self, args, player_id, ticket_id):
        """
        Claim ticket
        """
        return self._patch(args, player_id, ticket_id)

    @bp.arguments(TicketPatchRequestSchema)
    @bp.response(TicketSchema())
    def put(self, args, player_id, ticket_id):
        """
        Claim ticket
        """
        return self._patch(args, player_id, ticket_id)

    def _patch(self, args, player_id, ticket_id):
        journal_id = args.get("journal_id")

        if not can_edit_player(player_id):
            abort(http_client.METHOD_NOT_ALLOWED, message="That is not your player!")

        ticket = get_ticket(player_id, ticket_id)
        if not ticket:
            abort(404, message="Ticket was not found")

        if ticket.used_date:
            abort(404, message="Ticket has already been claimed")

        log.info("Player %s is claiming ticket %s of type '%s' with journal_id %s",
                 player_id, ticket_id, ticket.ticket_type, journal_id)

        ticket.used_date = datetime.datetime.utcnow()
        ticket.journal_id = journal_id
        g.db.commit()

        log_event(player_id, "event.player.ticketclaimed", {"ticket_id": ticket_id})
        return ticket
