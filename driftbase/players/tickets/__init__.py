# -*- coding: utf-8 -*-

from flask import g

from driftbase.db.models import Ticket

import logging
log = logging.getLogger(__name__)


def create_ticket(player_id, issuer_id, ticket_type, details, external_id, db_session=None):
    if not db_session:
        db_session = g.db

    ticket = Ticket(player_id=player_id,
                    issuer_id=issuer_id,
                    ticket_type=ticket_type,
                    details=details,
                    external_id=external_id)
    db_session.add(ticket)
    db_session.commit()
    ticket_id = ticket.ticket_id
    log.info("Player %s got ticket %s of type '%s'", player_id, ticket_id, ticket_type)
    return ticket_id
