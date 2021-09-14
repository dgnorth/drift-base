import json
import six
from flask import g

from driftbase.models.db import Counter
from driftbase.utils import log

COUNTER_CACHE_TTL = 60 * 10


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
