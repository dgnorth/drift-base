from http import client as http_client

import collections
import datetime
import functools
import json
import logging
import textwrap
from flask import g
from webargs.flaskparser import abort

from drift.core.extensions.jwt import current_user

log = logging.getLogger(__name__)

# messages expire in a day by default
DEFAULT_EXPIRE_SECONDS = 60 * 60 * 24
# prune a player's message list if they're not listening
MAX_PENDING_MESSAGES = 100


# for mocking
def utcnow():
    return datetime.datetime.utcnow()


def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, datetime.datetime):
        serial = obj.isoformat()
        return serial
    raise TypeError("Type not serializable")


def is_key_legal(key):
    if len(key) > 64:
        return False
    if ":" in key:
        return False
    return True


def fetch_messages(exchange, exchange_id, messages_after_id=None, rows=None):
    my_player_id = None
    if current_user:
        my_player_id = current_user["player_id"]

    redis_messages_key = _make_exchange_messages_key(exchange, exchange_id)
    redis_seen_key = _make_exchange_messages_seen_key(exchange)

    seen_message_id = g.redis.conn.hget(redis_seen_key, exchange_id)
    if messages_after_id == '0' and seen_message_id:
        messages_after_id = seen_message_id
    else:
        g.redis.conn.hset(redis_seen_key, exchange_id, messages_after_id)

    now = utcnow()
    messages = []
    expired_ids = []
    highest_processed_message_id = '0'
    from_message_id = _next_message_id(messages_after_id)

    # if rows is negative, read in reverse, to satisfy old API
    if not rows or rows >= 0:
        content = g.redis.conn.xrange(redis_messages_key, min=from_message_id, max='+', count=rows)
    else:
        content = g.redis.conn.xrevrange(redis_messages_key, min=from_message_id, max='+', count=-rows)
    if len(content):
        for message_id, message in content:
            # Redis will append '-0' to custom IDs too, so make sure we remove it here
            message_id = message_id.split('-')[0]
            message['payload'] = json.loads(message['payload'])
            message['message_id'] = int(message_id)
            highest_processed_message_id = message_id
            expires = datetime.datetime.fromisoformat(message["expires"][:-1])  # remove trailing 'Z'
            if expires > now:
                messages.append(message)
                log.debug("Message %s has been retrieved from queue '%s' in "
                          "exchange '%s:%s' by player %s",
                          message['message_id'],
                          message['queue'], exchange, exchange_id, my_player_id)
            else:
                expired_ids += message_id
                log.debug("Expired message %s was removed from queue '%s' in "
                          "exchange '%s:%s' by player %s",
                          message['message_id'],
                          message['queue'], exchange, exchange_id, my_player_id)

    with g.redis.conn.pipeline() as pipe:
        # If there were only expired messages, make sure we skip those next time
        if len(messages) == 0 and highest_processed_message_id != '0':
            pipe.hset(redis_seen_key, exchange_id, highest_processed_message_id)

        # Delete expired messages
        if expired_ids:
            pipe.xdel(redis_messages_key, expired_ids)
        pipe.execute()

    result = collections.defaultdict(list)
    for m in messages:
        result[m['queue']].append(m)
    return result


def get_message(exchange, exchange_id, message_id):
    key = _make_exchange_messages_key(exchange, exchange_id)
    val = g.redis.conn.xrange(key, min=message_id, max=message_id, count=1)
    if val:
        message = val[0][1]
        return message
    else:
        return None


def is_service():
    ret = False
    if current_user and 'service' in current_user['roles']:
        ret = True
    return ret


def check_can_use_exchange(exchange, exchange_id, read=False):
    # service users have unrestricted access to all exchanges
    if is_service():
        return True

    # players can only use player exchanges
    if exchange != "players":
        abort(http_client.BAD_REQUEST, message="Only service users can use exchange '%s'" % exchange)

    # players can only read from their own exchanges but can write to others
    if read:
        if not current_user or current_user["player_id"] != exchange_id:
            abort(http_client.BAD_REQUEST,
                  message="You can only read from an exchange that belongs to you!")


@functools.lru_cache
def _get_add_message_script():
    return g.redis.conn.register_script(textwrap.dedent(f"""
        local id = redis.call('INCRBY', KEYS[2], 1)
        redis.call('XADD', KEYS[1], 'MAXLEN', '~', {MAX_PENDING_MESSAGES}, id, unpack(ARGV))
        return tostring(id)
        """))


def post_message(exchange, exchange_id, queue, payload, expire_seconds=None, sender_system=False):
    if not is_key_legal(exchange) or not is_key_legal(queue):
        abort(http_client.BAD_REQUEST, message="Exchange or Queue name is invalid.")

    expire_seconds = expire_seconds or DEFAULT_EXPIRE_SECONDS
    timestamp = utcnow()
    expires = timestamp + datetime.timedelta(seconds=expire_seconds)
    message = {
        'timestamp': timestamp.isoformat() + "Z",
        'expires': expires.isoformat() + "Z",
        'sender_id': 0 if sender_system else current_user["player_id"],
        'payload': json.dumps(payload, default=json_serial),
        'queue': queue,
        'exchange': exchange,
        'exchange_id': exchange_id,
    }

    pieces = []
    for pair in iter(message.items()):
        pieces.extend(pair)
    message_id = _get_add_message_script()(keys=[_make_exchange_messages_key(exchange, exchange_id),
                                                 _make_exchange_messages_id_key(exchange, exchange_id)],
                                           args=pieces)

    return {
        'message_id': int(message_id),
    }


def _make_exchange_messages_id_key(exchange, exchange_id):
    return g.redis.make_key(f"messages:id:{exchange}:{exchange_id}:")


def _make_exchange_messages_seen_key(exchange):
    return g.redis.make_key(f"messages:seen:{exchange}:")


def _make_exchange_messages_key(exchange, exchange_id):
    return g.redis.make_key(f"messages:{exchange}:{exchange_id}:")


def _next_message_id(message_id: str) -> str:
    """ Return the minimum valid increment to the passed in message_id """
    return str(int(message_id) + 1)
