# -*- coding: utf-8 -*-

import json
import logging

from flask import g

from driftbase.models.db import PlayerJournal

log = logging.getLogger(__name__)


class JournalError(Exception):
    pass


def validate_journal_details(details):
    # TODO: Add validation
    if details:
        return json.loads(details)
    else:
        return None


def validate_journal_steps(steps):
    # TODO: Add validation
    if steps:
        return json.loads(steps)
    else:
        return None


def get_latest_journal(player_id, db_session=None):
    if not db_session:
        db_session = g.db
    journal_entry = db_session.query(PlayerJournal) \
                              .filter(PlayerJournal.player_id == player_id) \
                              .order_by(-PlayerJournal.journal_id) \
                              .first()
    return journal_entry


def write_journal(player_id, action, journal_id=None, timestamp=None,
                  details=None, steps=None, actor_id=None, db_session=None):
    """Write a new journal entry into the DB. This should only ever be called from the client
    """
    if not db_session:
        db_session = g.db

    if journal_id is not None and journal_id <= 0:
        raise JournalError("Invalid journal_id %s" % journal_id)

    details = validate_journal_details(details)
    steps = validate_journal_steps(steps)

    if details and not isinstance(details, dict):
        raise JournalError("Journal details must be a dict, not %s" % type(details))

    if steps and not isinstance(steps, list):
        raise JournalError("Journal steps must be a list, not %s" % type(steps))

    # validate that the journal_id has not been used before
    if journal_id:
        prev_journal = get_latest_journal(player_id, db_session)
        if prev_journal:
            if prev_journal.journal_id >= journal_id:
                raise JournalError("Attempting to write journal entry %s out of sequence. "
                                   "Expected %s" % (journal_id, prev_journal.journal_id + 1))

    # if the player is the actor, we don't double-log it and leave actor_id as null
    if actor_id == player_id:
        actor_id = None
    journal = PlayerJournal(player_id=player_id,
                            journal_id=journal_id,
                            action_type_name=action,
                            details=details,
                            actor_id=actor_id,
                            timestamp=timestamp,
                            steps=steps)
    db_session.add(journal)
    db_session.commit()

    log.debug("Journal entry %s (%s) added to player %s", journal_id, action, player_id)
    return journal.as_dict()
