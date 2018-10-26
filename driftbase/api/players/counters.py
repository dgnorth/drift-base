"""
    Update summary and stats for the player
"""

import datetime
import time
import logging
from dateutil import parser
import collections

from six.moves import http_client

from sqlalchemy.exc import IntegrityError

from flask import request, g, url_for, jsonify
from flask.views import MethodView
import marshmallow as ma
from flask_restplus import reqparse
from flask_rest_api import Blueprint, abort

from drift.core.extensions.jwt import current_user
from drift.core.extensions.schemachecker import simple_schema_request

from driftbase.models.db import CounterEntry, Counter, CorePlayer, PlayerCounter
from driftbase.utils import clear_counter_cache, get_counter

log = logging.getLogger(__name__)

bp = Blueprint("player_counters", __name__, url_prefix='/players', description="Counters for individual players")

TOTAL_TIMESTAMP = datetime.datetime.strptime("2000-01-01", "%Y-%m-%d")
COUNTER_PERIODS = ['total', 'month', 'day', 'hour', 'minute', 'second']


def get_player(player_id):
    player = g.db.query(CorePlayer).filter(CorePlayer.player_id == player_id).first()
    return player


def get_or_create_counter_id(name, counter_type, db_session=None):
    if not db_session:
        db_session = g.db
    name = name.lower()
    counter = get_counter(name)
    if counter:
        return counter["counter_id"]

    # we fall through here if the counter does not exist

    # Note: counter type is only inserted for the first entry and then not updated again
    row = db_session.query(Counter).filter(Counter.name == name).first()
    if not row:
        db_session.commit()
        log.info("Creating new counter called %s", name)
        try:
            row = Counter(name=name, counter_type=counter_type)
            db_session.add(row)
            db_session.commit()
        except IntegrityError as e:
            # if someone has inserted the counter in the meantime, retrieve it
            if "duplicate key" in repr(e):
                db_session.rollback()
                row = db_session.query(Counter).filter(Counter.name == name).first()
            else:
                raise

        clear_counter_cache()
    counter_id = row.counter_id

    return counter_id


def get_or_create_player_counter(counter_id, player_id):
    player_counter = g.db.query(PlayerCounter) \
                         .filter(PlayerCounter.player_id == player_id,
                                 PlayerCounter.counter_id == counter_id) \
                         .first()

    if not player_counter:
        log.info("Creating new player counter for counter_id %s", counter_id)
        player_counter = PlayerCounter(counter_id=counter_id, player_id=player_id)
        g.db.add(player_counter)
    g.db.commit()
    return player_counter


def get_date_time_for_period(period, timestamp):
    """
    Clamps the timestamp according to the period
    """
    date_time = timestamp.replace(microsecond=0)
    if period == 'total':
        date_time = TOTAL_TIMESTAMP
    elif period == 'month':
        date_time = date_time.replace(day=1, hour=0, minute=0, second=0)
    elif period == 'day':
        date_time = date_time.replace(hour=0, minute=0, second=0)
    elif period == 'hour':
        date_time = date_time.replace(minute=0, second=0)
    elif period == 'minute':
        date_time = date_time.replace(second=0)
    elif period == 'second':
        # Note: second is wrongly named and should be 10seconds
        date_time = date_time.replace(second=10 * int(date_time.second / 10))
    return date_time


def add_count(counter_id, player_id, timestamp, value, is_absolute=False,
              context_id=0, db_session=None):
    """
    Add a count into each of the periods that we want to keep track of
    """
    if not db_session:
        db_session = g.db
    log.debug("add_count(%s, %s, %s, %s, %s, %s)" %
              (counter_id, player_id, timestamp, value, is_absolute, context_id))
    for period in COUNTER_PERIODS:
        date_time = get_date_time_for_period(period, timestamp)
        row = db_session.query(CounterEntry).filter(CounterEntry.counter_id == counter_id,
                                                    CounterEntry.player_id == player_id,
                                                    CounterEntry.period == period,
                                                    CounterEntry.date_time == date_time).first()
        if row:
            if is_absolute:
                row.value = value
            else:
                row.value += value
        else:
            entry = CounterEntry(counter_id=counter_id,
                                 period=period,
                                 date_time=date_time,
                                 player_id=player_id,
                                 value=value,
                                 )
            # we add the context_id for the non-bucketed (raw) data only
            if period == "second":
                entry.context_id = context_id
            db_session.add(entry)


def check_and_update_player_counter(player_counter, timestamp):
    """
    Updates the player_counter row with the latest info
    Returns False if the timestamp has been updated before since we want to be idempotent
    """

    if player_counter.last_update == timestamp:
        log.warning("Trying to update count for counter %s for player %s at '%s' again. "
                    "Rejecting update",
                    player_counter.counter_id, player_counter.player_id, timestamp)
        return False
    else:
        player_counter.last_update = timestamp
        player_counter.num_updates += 1

    return True


@bp.route("/<int:player_id>/counters", endpoint="list")
class CountersApi(MethodView):

    def get(self, player_id):
        """
        Find counters by player ID
        """
        # TODO: Playercheck
        if not get_player(player_id):
            abort(404, message="Player Not found")

        rows = g.db.query(PlayerCounter).filter(PlayerCounter.player_id == player_id)
        ret = []
        for row in rows:
            counter_id = row.counter_id
            counter = get_counter(counter_id)
            entry = {
                "counter_id": counter_id,
                "first_update": row.create_date,
                "last_update": row.modify_date,
                "num_updates": row.num_updates,
                "url": url_for("player_counter", player_id=player_id,
                               counter_id=counter_id, _external=True),
                "name": counter["name"],
                "periods": {}
            }
            for period in COUNTER_PERIODS + ["all"]:
                entry["periods"][period] = url_for("player_counter_period", player_id=player_id,
                                                   counter_id=counter_id, period=period,
                                                   _external=True)
            total = g.db.query(CounterEntry.value).filter(CounterEntry.player_id == player_id,
                                                          CounterEntry.counter_id == counter_id,
                                                          CounterEntry.period == "total").first()
            if total:
                entry["total"] = total.value
            else:
                entry["total"] = 0
            ret.append(entry)

        return jsonify(ret)

    def patch(self, player_id):
        """
        Update counter for player
        """
        return self._patch(player_id)

    def put(self, player_id):
        """
        Update counter for player

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
        Find counter by counter ID and player ID
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
            ret["periods"][period] = url_for("player_counter_period", player_id=player_id,
                                             counter_id=counter_id, period=period, _external=True)

        return jsonify(ret)

    @simple_schema_request({"timestamp": {"type": "string", }, "value": {"type": "number"}, "context_id": {"type": "number"}})
    def patch(self, player_id, counter_id, context_id):
        return self._patch(player_id, counter_id, context_id)

    @simple_schema_request({"timestamp": {"type": "string", }, "value": {"type": "number"}, "context_id": {"type": "number"}})
    def put(self, player_id, counter_id, context_id):
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
        counter_entries = g.db.query(CounterEntry) \
                              .filter(CounterEntry.player_id == player_id,
                                      CounterEntry.period == "total")
        ret = {}
        for row in counter_entries:
            counter = get_counter(row.counter_id)
            ret[counter["name"]] = row.value

        return jsonify(ret)
