# -*- coding: utf-8 -*-

import logging
import datetime, httplib

from flask import Blueprint, url_for, request, g
from flask_restful import Api, Resource, abort

from drift.core.extensions.schemachecker import simple_schema_request
from drift.auth.jwtchecker import requires_roles

from driftbase.players import log_event, can_edit_player
from driftbase.players.tickets import create_ticket
from driftbase.db.models import Ticket

log = logging.getLogger(__name__)
bp = Blueprint("tickets", __name__)
api = Api(bp)


def add_ticket_links(ticket):
    ret = ticket.as_dict()
    ret["player_url"] = url_for("players.player", player_id=ticket.player_id, _external=True)
    ret["issuer_url"] = None
    if ticket.issuer_id:
        ret["issuer_url"] = url_for("players.player", player_id=ticket.issuer_id, _external=True)
    ret["url"] = url_for("tickets.entry", player_id=ticket.player_id,
                         ticket_id=ticket.ticket_id, _external=True)
    return ret


class TicketsEndpoint(Resource):

    def get(self, player_id):
        """
        Get a list of outstanding tickets for the player
        """
        can_edit_player(player_id)
        tickets = g.db.query(Ticket) \
                 .filter(Ticket.player_id == player_id, Ticket.used_date == None)
        ret = [add_ticket_links(t) for t in tickets]
        return ret

    @requires_roles("service")
    @simple_schema_request({
        "issuer_id": {"type": "number"},
        "ticket_type": {"type": "string"},
        "external_id": {"type": "string"},
        "details": {"type": "object"},
    }, required=["ticket_type"])
    def post(self, player_id):
        """
        Create a ticket for a player. Only available to services
        """
        args = request.json
        issuer_id = args.get("issuer_id")
        ticket_type = args.get("ticket_type")
        details = args.get("details")
        external_id = args.get("external_id")
        ticket_id = create_ticket(player_id, issuer_id, ticket_type, details, external_id)
        ticket_url = url_for("tickets.entry", ticket_id=ticket_id,
                             player_id=player_id, _external=True)
        ret = {
            "ticket_id": ticket_id,
            "ticket_url": ticket_url
        }
        response_header = {
            "Location": ticket_url,
        }

        return ret, httplib.CREATED, response_header


def get_ticket(player_id, ticket_id):
    ticket = g.db.query(Ticket) \
                 .filter(Ticket.player_id == player_id,
                         Ticket.ticket_id == ticket_id) \
                 .first()
    return ticket


class TicketEndpoint(Resource):

    def get(self, player_id, ticket_id):
        """
        Get information about any past or ongoing battle initiated by
        the current player against the other player
        """
        if not can_edit_player(player_id):
            abort(httplib.METHOD_NOT_ALLOWED, message="That is not your player!")

        ticket = get_ticket(player_id, ticket_id)
        if not ticket:
            abort(404, message="Ticket was not found")
        return add_ticket_links(ticket)

    @simple_schema_request({"journal_id": {"type": "number", }})
    def patch(self, player_id, ticket_id):
        return self._patch(player_id, ticket_id)
    @simple_schema_request({"journal_id": {"type": "number", }})
    def put(self, player_id, ticket_id):
        return self._patch(player_id, ticket_id)

    def _patch(self, player_id, ticket_id):
        """
        Claim a ticket
        """
        args = request.json
        journal_id = args.get("journal_id")

        if not can_edit_player(player_id):
            abort(httplib.METHOD_NOT_ALLOWED, message="That is not your player!")

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

        return add_ticket_links(ticket)


api.add_resource(TicketsEndpoint, "/players/<int:player_id>/tickets",
                 endpoint="list")
api.add_resource(TicketEndpoint, "/players/<int:player_id>/tickets/<int:ticket_id>",
                 endpoint="entry")
