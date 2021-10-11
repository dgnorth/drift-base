from time import time
from flask import g
from redis.client import Pipeline
import typing
import datetime
import json

OPERATION_TIMEOUT = 10

def timeout_pipe(timeout: int = OPERATION_TIMEOUT) -> typing.Generator[Pipeline, None, None]:
    endtime = time() + timeout
    with g.redis.conn.pipeline() as pipe:
        while time() < endtime:
            yield pipe

class JsonLock(object):
    """
    Context manager for synchronizing creation and modification of a json redis value.
    """
    MAX_LOCK_WAIT_TIME_SECONDS = 30
    TTL_SECONDS = 60 * 60 * 24

    def __init__(self, key):
        self._key = key
        self._redis = g.redis
        self._modified = False
        self._value = None
        self._lock = g.redis.conn.lock(self._key + "LOCK", timeout=self.MAX_LOCK_WAIT_TIME_SECONDS)

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, new_value):
        self._value = new_value
        self._modified = True

    def __enter__(self):
        self._lock.acquire(blocking=True)
        value = self._redis.conn.get(self._key)
        if value is not None:
            value = json.loads(value)
            self._value = value
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._lock.owned():  # If we don't own the lock at this point, we don't want to update anything
            with self._redis.conn.pipeline() as pipe:
                if self._modified is True and exc_type is None:
                    pipe.delete(self._key)  # Always update the lobby wholesale, i.e. don't leave stale fields behind.
                    if self._value:
                        pipe.set(self._key, json.dumps(self._value, default=self._json_serial), ex=self.TTL_SECONDS)
                pipe.execute()
            self._lock.release()

    @staticmethod
    def _json_serial(obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()

        raise TypeError(f"Type {type(obj)} not serializable")
