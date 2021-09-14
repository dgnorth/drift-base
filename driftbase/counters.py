import datetime
import json
import logging
import six
from flask import g
from sqlalchemy.exc import IntegrityError

from driftbase.models.db import Counter, CorePlayer, PlayerCounter, CounterEntry

COUNTER_CACHE_TTL = 60 * 10

TOTAL_TIMESTAMP = datetime.datetime.strptime("2000-01-01", "%Y-%m-%d")
COUNTER_PERIODS = ['total', 'month', 'day', 'hour', 'minute', 'second']

log = logging.getLogger(__name__)


def get_all_counters(force=False):
    def get_all_counters_from_db():
        counters = g.db.query(Counter).all()
        all_counters = {}
        for c in counters:
            counter = {
                "counter_id": c.counter_id,
                "name": c.name,
                "counter_type": c.counter_type,
            }
            all_counters[c.counter_id] = counter
            all_counters[c.name] = counter
        return all_counters

    val = g.redis.get("counters")
    if not val or force:
        all_counters = get_all_counters_from_db()
        # FIXME: Since trying to fetch a non-existing counter will cause a cache refresh, what's the point of the TTL?
        g.redis.set("counters", json.dumps(all_counters), expire=COUNTER_CACHE_TTL)
    else:
        try:
            all_counters = json.loads(val)
        except Exception:
            log.error("Cannot decode '%s'", val)
            raise
    return all_counters


def get_counter(counter_key):
    counters = get_all_counters()
    try:
        return counters[six.text_type(counter_key)]
    except KeyError:
        log.info("Counter '%s' not found in cache. Fetching from db", counter_key)
        log.info("Counter cache contains: %s" % (counters.keys()))
        counters = get_all_counters(force=True)
        return counters.get(counter_key, None)


def clear_counter_cache():
    g.redis.delete("counter_names")


def get_player(player_id):
    player = g.db.query(CorePlayer).get(player_id)
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
