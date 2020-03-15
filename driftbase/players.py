
import json
import re
from six.moves import http_client
import logging

from flask import g, request
from flask_smorest import abort

from drift.core.extensions.jwt import current_user

from driftbase.models.db import CorePlayer, PlayerEvent
from driftbase.models.db import PlayerJournal
from driftbase.models.db import Ticket

PLAYER_GROUP_NAME_REGEX = '^[a-z_]{1,15}?$'
RETENTION_IN_SEC = 60 * 60 * 24 * 2  # Store each group for 48 hours.

log = logging.getLogger(__name__)


def get_check_player(player_id):
    player = g.db.query(CorePlayer).get(player_id)
    if not player:
        msg = "Player does not exist"
        log.warning(msg)
        abort(http_client.NOT_FOUND)
    return player


def can_edit_player(player_id):
    if player_id != current_user["player_id"] and "service" not in current_user["roles"]:
        log.warning("Player %s is calling endpoint %s for a player that is not himself!",
                    current_user["player_id"], request)
        return False
    get_check_player(player_id)
    return True


def log_event(player_id, event_type_name, details=None, db_session=None):

    if not db_session:
        db_session = g.db

    log.info("Logging player event to DB: player_id=%s, event=%s", player_id, event_type_name)
    event = PlayerEvent(event_type_id=None,
                        event_type_name=event_type_name,
                        player_id=player_id,
                        details=details)
    db_session.add(event)
    db_session.commit()


def get_playergroup(group_name, player_id=None):
    """Utility function to return player group.
    Can be used freely within a Flask request context.
    Raises 404 if group is not found.
    """
    player_id = player_id or current_user['player_id']
    key = _get_playergroup_key(group_name, player_id)
    pg = g.redis.get(key)
    if pg:
        return json.loads(pg)
    else:
        abort(http_client.NOT_FOUND,
              message="No player group named '%s' exists for player %s." % (group_name, player_id))


def get_playergroup_ids(group_name, player_id=None, caress_in_predicate=True):
    """Utility function to return a list of player id's for a given player group.
    If list is empty and 'caress_in_predicate' is True, a single entry of -1 is
    inserted into the list to make SQLAlchemy IN predicate happy.
    Can be used freely within a Flask request context.
    Raises 404 if group is not found.
    """
    pg = get_playergroup(group_name, player_id)
    player_ids = [player['player_id'] for player in pg['players']]
    if not player_ids and caress_in_predicate:
        player_ids = [-1]
    return player_ids


def set_playergroup(group_name, player_id, payload):
    key = _get_playergroup_key(group_name, player_id)
    g.redis.set(key, json.dumps(payload), expire=RETENTION_IN_SEC)


def _get_playergroup_key(group_name, player_id):
    """Returns redis key for player group. Throw exception if group name is invalid."""
    # Verify group name
    if not re.match(PLAYER_GROUP_NAME_REGEX, group_name):
        abort(http_client.BAD_REQUEST,
              message="'group_name' must match regex '{}'".format(PLAYER_GROUP_NAME_REGEX))

    key = "playergroup:{}.{}".format(player_id, group_name)
    return key


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
