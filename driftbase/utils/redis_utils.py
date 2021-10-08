from time import time
from flask import g
from redis.client import Pipeline
import typing

OPERATION_TIMEOUT = 10

def timeout_pipe(timeout: int = OPERATION_TIMEOUT) -> typing.Generator[Pipeline, None, None]:
    endtime = time() + timeout
    with g.redis.conn.pipeline() as pipe:
        while time() < endtime:
            yield pipe
