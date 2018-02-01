# -*- coding: utf-8 -*-

import httplib

from flask import request, g
from flask_restful import abort

from drift.core.extensions.jwt import current_user

from driftbase.db.models import CorePlayer, PlayerEvent

import logging
log = logging.getLogger(__name__)


def get_check_player(player_id):
    player = g.db.query(CorePlayer).get(player_id)
    if not player:
        msg = "Player does not exist"
        log.warning(msg)
        abort(httplib.NOT_FOUND)
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
