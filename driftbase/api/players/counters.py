"""
    Update summary and stats for the player
"""

import collections
import datetime
import http.client as http_client
import logging
import marshmallow as ma
import time
from dateutil import parser
from flask import request, g, url_for, jsonify
from flask.views import MethodView
from drift.blueprint import Blueprint, abort

from drift.core.extensions.jwt import current_user
from flask_marshmallow.fields import AbsoluteUrlFor

from driftbase.counters import get_counter, get_player, add_count, check_and_update_player_counter, COUNTER_PERIODS, \
    get_all_counters, \
    batch_get_or_create_counters, batch_create_player_counters, batch_update_counter_entries
from driftbase.models.db import CounterEntry, PlayerCounter

COUNTER_TYPE_COUNT = "count"
COUNTER_TYPE_ABSOLUTE = "absolute"
DEFAULT_COUNTER_TYPE = COUNTER_TYPE_COUNT
LEGAL_COUNTER_TYPES = (COUNTER_TYPE_COUNT, COUNTER_TYPE_ABSOLUTE)

log = logging.getLogger(__name__)

bp = Blueprint("player_counters", __name__, url_prefix='/players')


class PlayerCounterRequestSchema(ma.Schema):
    timestamp = ma.fields.DateTime()
    value = ma.fields.Integer()
    context_id = ma.fields.Integer()
    name = ma.fields.String()


class PlayerCounterSchema(ma.Schema):
    counter_id = ma.fields.Integer()
    player_id = ma.fields.Integer()
    first_update = ma.fields.DateTime()
    last_update = ma.fields.DateTime()
    num_updates = ma.fields.Integer()
    url = AbsoluteUrlFor('player_counters.entry', player_id='<player_id>', counter_id='<counter_id>')
    name = ma.fields.String()
    total = ma.fields.Integer()
    periods = ma.fields.Dict()


@bp.route("/<int:player_id>/counters", endpoint="list")
class CountersApi(MethodView):

    @bp.response(http_client.OK, PlayerCounterSchema(many=True))
    def get(self, player_id):
        """
        Counters for player

        Returns a list of counters that have been created on the players' behalf.
        """
        # TODO: Playercheck
        if not get_player(player_id):
            abort(http_client.NOT_FOUND, message="Player Not found")

        # Cache all the values, we will need all of them anyway
        rows = g.db.query(PlayerCounter).filter(PlayerCounter.player_id == player_id)
        ret = []
        counter_ids = [row.counter_id for row in rows]
        value_rows = g.db.query(CounterEntry.counter_id, CounterEntry.value).filter(
            CounterEntry.player_id == player_id,
            CounterEntry.counter_id.in_(counter_ids),
            CounterEntry.period == "total").all()
        counter_totals = {row.counter_id: row.value for row in value_rows}
        # Get all the cached counter metadata
        counters = get_all_counters()

        for row in rows:
            counter_id = row.counter_id
            try:
                counter = counters[counter_id]
            except KeyError:
                # if a counter is missing, the cache was stale, so refresh it
                counters = get_all_counters(force=True)
                counter = counters[counter_id]
            entry = {
                "counter_id": counter_id,
                "player_id": player_id,
                "first_update": row.create_date,
                "last_update": row.modify_date,
                "num_updates": row.num_updates,
                "name": counter["name"],
                "periods": {},
                "total": 0,
            }
            for period in COUNTER_PERIODS + ["all"]:
                entry["periods"][period] = url_for("player_counters.period", player_id=player_id,
                                                   counter_id=counter_id, period=period,
                                                   _external=True)
            total = counter_totals.get(counter_id, None)
            if total:
                entry["total"] = total
            ret.append(entry)

        return ret

    # we accept lists of PlayerCounterRequestSchema items 
    # so we cannot use the arguments field
    # @bp.arguments(PlayerCounterRequestSchema)
    def patch(self, player_id):
        """
        Update counters for player

        The endpoint accepts a list of counters to update at once.
        """
        return self._patch(player_id)

    # @bp.arguments(PlayerCounterRequestSchema)
    def put(self, player_id):
        """
        Update counters for player

        This verb is provided for backwards-compatibility for clients that
        do not support PATCH        
        """
        return self._patch(player_id)

    def _patch(self, player_id):
        """
        Expects a list of counters to update in the format:
        [
            {
                "name": "myname",
                "counter_type": "count"}, # count or absolute
                "value": 5.4},
                "timestamp": "2016-01-01T10:22:33.332Z",
                "context_id:": 12345 (optional)
            },
            ...
        ]
        """
        if current_user["player_id"] != player_id and 'service' not in current_user['roles']:
            message = "Player %s is not %s. Role 'service' is required for updating other" \
                      " players counters. Your role set is %s."
            message = message % (current_user["player_id"], player_id, current_user['roles'])
            abort(http_client.UNAUTHORIZED, message=message)

        start_time = time.time()
        args = request.json

        if not isinstance(args, list):
            abort(http_client.METHOD_NOT_ALLOWED,
                  message="This endpoint expects a list of counters to update. got %s" % args)

        log.info("patch for player %s with %s counters...", player_id, len(args))

        required_keys = ("name", "value", "timestamp")

        # Sort out invalid entries, and merge all operations on the same counter
        result = {}
        counter_names = []
        counter_updates = {}
        timestamp = datetime.datetime.utcnow()
        for update in args:
            log.debug("Adding count for player %s: %s" % (player_id, update))

            try:
                name = update["name"]
            except Exception:
                continue
            missing_keys = []
            for k in required_keys:
                if k not in update:
                    missing_keys.append(k)
            if missing_keys:
                result[name] = "Missing keys: %s" % ",".join(missing_keys)
                continue

            counter_type = update.get("counter_type", DEFAULT_COUNTER_TYPE).lower()
            if counter_type not in LEGAL_COUNTER_TYPES:
                result[name] = "Illegal counter type. Expecting: %s" % ",".join(LEGAL_COUNTER_TYPES)
                continue

            is_absolute = counter_type == COUNTER_TYPE_ABSOLUTE
            value = float(update["value"])

            counter_names.append(name)

            # Skip no-op values
            if not is_absolute and value == 0.0:
                continue

            context_id = int(update.get("context_id", 0))
            # ensure that multiple updates all get applied
            # theoretically these should be individual entries, if the client flushes at a low rate,
            # but since we don't trust the client's time stamp, it's better to merge them for now
            update_entry = counter_updates.get(name)
            if update_entry:
                if is_absolute:
                    update_entry["value"] = value
                else:
                    update_entry["value"] += value
            else:
                counter_updates[name] = dict(counter_type=counter_type, value=value,
                                             context_id=context_id,
                                             is_absolute=is_absolute,
                                             timestamp=timestamp
                                             )

        counter_ids = []
        if len(counter_updates) > 0:
            counters = batch_get_or_create_counters([(k, v["counter_type"]) for k, v in counter_updates.items()])
            for (counter_id, name) in counters:
                counter_updates[name]["counter_id"] = counter_id
                counter_ids.append(counter_id)

            # Player counters keep track of which counters have ever been set for a given player
            batch_create_player_counters(player_id, counter_ids)

            batch_update_counter_entries(player_id, counter_updates)

        for name in counter_names:
            result[name] = "OK"

        log.info("patch(%s) done in %.2fs!", player_id, time.time() - start_time)
        return jsonify(result)


@bp.route("/<int:player_id>/counters/<int:counter_id>", endpoint="entry")
class CounterApi(MethodView):
    def get(self, player_id, counter_id):
        """
        Find counter for player

        Returns information for a specific counter for the player.
        """
        counter = get_counter(counter_id)
        if not counter:
            abort(404)
        player_counter = g.db.query(PlayerCounter) \
            .filter(PlayerCounter.player_id == player_id,
                    PlayerCounter.counter_id == counter_id) \
            .first()
        if not player_counter:
            abort(404)

        ret = {
            "counter": counter,
            "player_counter": player_counter.as_dict(),
            "periods": {}
        }
        for period in COUNTER_PERIODS + ["all"]:
            ret["periods"][period] = url_for("player_counters.period", player_id=player_id,
                                             counter_id=counter_id, period=period, _external=True)

        return jsonify(ret)

    @bp.arguments(PlayerCounterRequestSchema)
    def patch(self, player_id, counter_id, context_id):
        """
        Update single counter

        Update a single counter for the player. Includes optional context
        """
        return self._patch(player_id, counter_id, context_id)

    @bp.arguments(PlayerCounterRequestSchema)
    def put(self, player_id, counter_id, context_id):
        """
        Update single counter

        Update a single counter for the player. Includes optional context
        """
        return self._patch(player_id, counter_id, context_id)

    def _patch(self, player_id, counter_id, context_id):
        """
        Update a single existing counter
        """
        args = request.json
        value = args["value"]
        timestamp = parser.parse(args["timestamp"])

        ok = check_and_update_player_counter(player_id, counter_id, timestamp)
        if not ok:
            return "Count has been applied before at this timestamp"

        counter = get_counter(counter_id)
        is_absolute = (counter["counter_type"] == "absolute")
        add_count(counter_id, player_id, timestamp, value, is_absolute=is_absolute,
                  context_id=context_id)
        return "OK"


@bp.route("/<int:player_id>/counters/<int:counter_id>/<string:period>", endpoint="period")
class CounterPeriodApi(MethodView):
    def get(self, player_id, counter_id, period):
        """
        Counter entries for period

        Retruns a list of counters for the requested period.
        """
        counter = get_counter(counter_id)
        if not counter:
            abort(404)
        if period == "all":
            counter_entries = g.db.query(CounterEntry) \
                .filter(CounterEntry.player_id == player_id,
                        CounterEntry.counter_id == counter_id) \
                .order_by(CounterEntry.period, CounterEntry.id)
            ret = collections.defaultdict(dict)
            for row in counter_entries:
                ret[row.period][row.date_time.isoformat() + "Z"] = row.value

        else:
            counter_entries = g.db.query(CounterEntry) \
                .filter(CounterEntry.player_id == player_id,
                        CounterEntry.counter_id == counter_id,
                        CounterEntry.period == period)
            ret = {}
            for row in counter_entries:
                ret[row.date_time.isoformat() + "Z"] = row.value
        return jsonify(ret)


@bp.route("/<int:player_id>/countertotals", endpoint="totals")
class CounterTotalsApi(MethodView):
    def get(self, player_id):
        """
        Counter Totals

        Return the 'total' count for all counters belonging to the player.
        """
        counter_entries = g.db.query(CounterEntry) \
            .filter(CounterEntry.player_id == player_id,
                    CounterEntry.period == "total")
        ret = {}
        for row in counter_entries:
            counter = get_counter(row.counter_id)
            ret[counter["name"]] = row.value

        return jsonify(ret)
