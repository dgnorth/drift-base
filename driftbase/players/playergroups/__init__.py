# -*- coding: utf-8 -*-

import json
import re
import httplib

from flask import g
from flask_restful import abort

from drift.auth.jwtchecker import current_user

PLAYER_GROUP_NAME_REGEX = '^[a-z_]{1,15}?$'
RETENTION_IN_SEC = 60 * 60 * 24 * 2  # Store each group for 48 hours.


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
        abort(httplib.NOT_FOUND,
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
        abort(httplib.BAD_REQUEST,
              message="'group_name' must match regex '{}'".format(PLAYER_GROUP_NAME_REGEX))

    key = "playergroup:{}.{}".format(player_id, group_name)
    return key
