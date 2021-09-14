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
from flask_smorest import Blueprint, abort

from drift.core.extensions.jwt import current_user
from drift.utils import Url
from driftbase.counters import get_counter, get_player, get_or_create_counter_id, \
    get_or_create_player_counter, add_count, check_and_update_player_counter, COUNTER_PERIODS, get_all_counters
from driftbase.models.db import CounterEntry, PlayerCounter

log = logging.getLogger(__name__)

bp = Blueprint("player_counters", __name__, url_prefix='/players', description="Counters for individual players")


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
    url = Url('player_counters.entry', player_id='<player_id>', counter_id='<counter_id>', doc="This is the url")
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
        DEFAULT_COUNTER_TYPE = "count"
        LEGAL_COUNTER_TYPES = (DEFAULT_COUNTER_TYPE, "absolute")
        args = request.json

        if not isinstance(args, list):
            abort(http_client.METHOD_NOT_ALLOWED,
                  message="This endpoint expects a list of counters to update. got %s" % args)

        log.info("patch for player %s with %s counters...", player_id, len(args))

        required_keys = ("name", "value", "timestamp")

        # we might have several entries with the same counter_name.
        # Therefore we do any work for creating and updating these
        # counters here, once per counter
        result = {}
        counters = {}
        timestamp = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
        for entry in args:
            log.debug("Adding count for player %s: %s" % (player_id, entry))

            try:
                name = entry["name"]
            except Exception:
                continue
            missing_keys = []
            for k in required_keys:
                if k not in entry:
                    missing_keys.append(k)
            if missing_keys:
                result[name] = "Missing keys: %s" % ",".join(missing_keys)
                continue

            counter_type = entry.get("counter_type", DEFAULT_COUNTER_TYPE).lower()
            if counter_type not in LEGAL_COUNTER_TYPES:
                result[name] = "Illegal counter type. Expecting: %s" % ",".join(LEGAL_COUNTER_TYPES)
                continue

            counter_type = entry.get("counter_type", DEFAULT_COUNTER_TYPE)
            counters[name] = {"counter_type": counter_type}

            context_id = int(entry.get("context_id", 0))

            redis_start_time = time.time()
            # write the counter into redis as well. I will refactor the db calls out
            # and use only redis here in the future
            value = int(entry["value"])
            key = 'counters:%s:%s:%s:%s:%s' % (name, counter_type, player_id, timestamp, context_id)
            # expire in 1 day
            ex = 86400
            if counter_type == "absolute":
                g.redis.set(key, value, expire=ex)
            else:
                g.redis.incr(key, value, expire=ex)
            log.info("Added %s to redis in %.2fsec", name, time.time() - redis_start_time)

        for counter_name, counter_info in counters.items():
            counter_id = get_or_create_counter_id(counter_name, counter_info["counter_type"])
            player_counter = get_or_create_player_counter(counter_id, player_id)
            counter_info["player_counter"] = player_counter
            counter_info["counter_id"] = counter_id

        g.db.commit()

        # now we should have any needed counters and player_counters created

        for entry in args:
            name = entry.get("name")
            counter = counters.get(name)
            if not counter:
                continue

            value = float(entry["value"])
            # timestamp = parser.parse(entry["timestamp"].replace("Z", ""))
            # NOTE: We use the server timestamp instead since the client one might be way off.
            #       We need to figure out a good method to allow the client to send timestamps
            #       that we can trust
            timestamp = datetime.datetime.utcnow()
            counter_type = entry.get("counter_type", DEFAULT_COUNTER_TYPE).lower()
            context_id = int(entry.get("context_id", 0))
            is_absolute = (counter_type == "absolute")
            counter_id = counter["counter_id"]

            ok = check_and_update_player_counter(counter["player_counter"], timestamp)
            if not ok:
                # Note: This never happens now since we are using the server time for the timestamp
                result[name] = "duplicate"
                continue

            add_count(counter_id, player_id, timestamp, value, is_absolute=is_absolute,
                      context_id=context_id)
            result[name] = "OK"

        g.db.commit()

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
