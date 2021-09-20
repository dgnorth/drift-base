import datetime
import json
import logging
import six
from flask import g
from sqlalchemy.dialects.postgresql import insert

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


def get_player(player_id):
    player = g.db.query(CorePlayer).get(player_id)
    return player


def batch_get_or_create_counters(counters, db_session=None):
    """
    return [(counter_id, name), ...]
    """
    if not db_session:
        db_session = g.db

    values = [{"name": name, "counter_type": counter_type} for (name, counter_type) in counters]
    insert_clause = insert(Counter).returning(Counter.counter_id, Counter.name).values(values)
    # This is essentially a no-op, but it's required to ensure we get all the IDs back in the result
    update_clause = insert_clause.on_conflict_do_update(index_elements=['name'],
                                                        set_=dict(name=insert_clause.excluded.name))
    result = db_session.execute(update_clause)
    return result


def batch_create_player_counters(player_id, counter_ids, db_session=None):
    """
    Create all missing player counters for the specified counter IDs
    """
    if not db_session:
        db_session = g.db

    values = [{"counter_id": counter_id, "player_id": player_id} for counter_id in counter_ids]
    insert_clause = insert(PlayerCounter).values(values)
    fallback_clause = insert_clause.on_conflict_do_nothing(index_elements=['counter_id', 'player_id'])
    return db_session.execute(fallback_clause)


def batch_update_counter_entries(player_id, entries, db_session=None):
    if not db_session:
        db_session = g.db

    absolute_values = []
    counter_values = []
    for k, e in entries.items():
        for period in COUNTER_PERIODS:
            date_time = get_date_time_for_period(period, e["timestamp"])
            entry = dict(counter_id=e["counter_id"], player_id=player_id, period=period, date_time=date_time,
                         value=e["value"])
            if e["is_absolute"]:
                absolute_values.append(entry)
            else:
                counter_values.append(entry)

    if len(absolute_values):
        insert_clause = insert(CounterEntry).values(absolute_values)
        update_clause = insert_clause.on_conflict_do_update(
            index_elements=['counter_id', 'player_id', 'period', 'date_time'],
            set_=dict(value=insert_clause.excluded.value))
        db_session.execute(update_clause)
        db_session.commit()

    if len(counter_values):
        insert_clause = insert(CounterEntry).values(counter_values)
        update_clause = insert_clause.on_conflict_do_update(
            index_elements=['counter_id', 'player_id', 'period', 'date_time'],
            set_=dict(value=CounterEntry.value + insert_clause.excluded.value))
        db_session.execute(update_clause)
        db_session.commit()


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
