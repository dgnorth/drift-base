"""
    Message box, mostly meant for client-to-client communication
"""

import collections
import copy
import datetime
import json
import logging
import operator
import sys
import uuid

import gevent
import marshmallow as ma
from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints
from flask import g, url_for, stream_with_context, Response, jsonify
from flask.views import MethodView
from flask_restx import reqparse
from flask_smorest import Blueprint, abort
from six.moves import http_client

log = logging.getLogger(__name__)

bp = Blueprint("messages", "messages", url_prefix="/messages",
               description="Message box, mostly meant for client-to-client communication")
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


# messages expire in a day by default
DEFAULT_EXPIRE_SECONDS = 60 * 60 * 24
# keep the top message around for a month
MESSAGE_EXCHANGE_TTL = 60 * 60 * 24 * 30


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


def incr_message_number(exchange, exchange_id):
    k = "top_message_number:%s:%s" % (exchange, exchange_id)
    g.redis.incr(k, expire=MESSAGE_EXCHANGE_TTL)
    val = g.redis.get(k)
    return int(val)


def fetch_messages(exchange, exchange_id, min_message_number=0, rows=None):
    messages = []
    key = "messages:%s-%s" % (exchange, exchange_id)
    redis_key = g.redis.make_key(key)
    seen_key = "messages:seen:%s-%s" % (exchange, exchange_id)
    redis_seen_key = g.redis.make_key(seen_key)
    my_player_id = None
    if current_user:
        my_player_id = current_user["player_id"]
    i = 1

    seen_message_number = g.redis.conn.get(redis_seen_key)
    if min_message_number == 1 and seen_message_number:
        min_message_number = int(seen_message_number) + 1
    else:
        g.redis.conn.setex(redis_seen_key, MESSAGE_EXCHANGE_TTL, min_message_number - 1)

    curr_message_number = sys.maxsize
    g.redis.conn.expire(redis_key, MESSAGE_EXCHANGE_TTL)
    while curr_message_number >= min_message_number:
        all_contents = g.redis.conn.lrange(redis_key, -i, -i)
        if not all_contents:
            break
        contents = all_contents[0]
        message = json.loads(contents)
        curr_message_number = message["message_number"]
        i += 1
        if curr_message_number < min_message_number:
            break
        expires = datetime.datetime.fromisoformat(message["expires"][:-1])
        if expires > utcnow():
            messages.append(message)
            log.info("Message %s ('%s') has been retrieved from queue '%s' in "
                     "exchange '%s-%s' by player %s",
                     message["message_number"], message["message_id"],
                     message["queue"], exchange, exchange_id, my_player_id)

            if rows and len(messages) >= rows:
                break
        else:
            log.info("Message %s ('%s') has been expired from queue '%s' in "
                     "exchange '%s-%s' by player %s",
                     message["message_number"], message["message_id"],
                     message["queue"], exchange, exchange_id, my_player_id)

    messages.sort(key=operator.itemgetter("message_number"), reverse=True)
    rows = rows or len(messages)
    ret = collections.defaultdict(list)
    for m in messages[:rows]:
        ret[m["queue"]].append(m)
    return ret


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


@bp.route('/<string:exchange>/<int:exchange_id>', endpoint='exchange')
class MessagesExchangeAPI(MethodView):
    no_jwt_check = ["GET"]

    get_args = reqparse.RequestParser()
    get_args.add_argument("timeout", type=int)
    get_args.add_argument("messages_after", type=int)
    get_args.add_argument("rows", type=int)

    def get(self, exchange, exchange_id):
        check_can_use_exchange(exchange, exchange_id, read=True)

        args = self.get_args.parse_args()
        timeout = args.timeout or 0
        min_message_number = int(args.messages_after or 0) + 1
        rows = args.rows
        if rows:
            rows = int(rows)

        my_player_id = None
        if current_user:
            my_player_id = current_user["player_id"]

        # players can only use player exchanges
        if exchange != "players" and not is_service():
            abort(http_client.BAD_REQUEST,
                  message="Only service users can use exchange '%s'" % exchange)

        exchange_full_name = "{}-{}".format(exchange, exchange_id)
        start_time = utcnow()
        poll_timeout = utcnow()

        if timeout > 0:
            poll_timeout += datetime.timedelta(seconds=timeout)
            log.info("[%s] Long poll - Waiting %s seconds for messages...", my_player_id, timeout)

            def streamer():
                yield " "
                while 1:
                    try:
                        messages = fetch_messages(exchange, exchange_id, min_message_number, rows)
                        if messages:
                            log.debug("[%s/%s] Returning messages after %.1f seconds",
                                      my_player_id, exchange_full_name,
                                      (utcnow() - start_time).total_seconds())
                            yield json.dumps(messages, default=json_serial)
                            return
                        elif utcnow() > poll_timeout:
                            log.info("[%s/%s] Poll timeout with no messages after %.1f seconds",
                                     my_player_id, exchange_full_name,
                                     (utcnow() - start_time).total_seconds())
                            yield json.dumps({})
                            return
                        # sleep for 100ms
                        gevent.sleep(0.1)
                        yield " "
                    except Exception as e:
                        log.error("[%s/%s] Exception %s", my_player_id, exchange_full_name, repr(e))
                        yield json.dumps({})

            return Response(stream_with_context(streamer()), mimetype="application/json")
        else:
            messages = fetch_messages(exchange, exchange_id, min_message_number, rows)
            return jsonify(messages)


class MessagesQueuePostArgs(ma.Schema):
    message = ma.fields.Dict(required=True)
    expire = ma.fields.Integer()


@bp.route('/<string:exchange>/<int:exchange_id>/<string:queue>', endpoint='queue')
class MessagesQueueAPI(MethodView):

    @bp.arguments(MessagesQueuePostArgs)
    def post(self, args, exchange, exchange_id, queue):
        check_can_use_exchange(exchange, exchange_id, read=False)
        expire_seconds = args.get("expire") or DEFAULT_EXPIRE_SECONDS

        message = _add_message(
            exchange=exchange,
            exchange_id=exchange_id,
            queue=queue,
            payload=args["message"],
            expire_seconds=expire_seconds,
        )

        log.info(
            "Message %s ('%s') has been added to queue '%s' in exchange "
            "'%s-%s' by player %s. It will expire on '%s'",
            message["message_number"], message["message_id"],
            queue, exchange, exchange_id,
            current_user["player_id"] if current_user else None,
            expire_seconds
        )

        ret = copy.copy(message)
        ret["url"] = url_for(
            "messages.message",
            exchange=message['exchange'],
            exchange_id=message['exchange_id'],
            queue=message['queue'],
            message_id=message['message_id'],
            _external=True
        )

        return jsonify(ret)


def _add_message(exchange, exchange_id, queue, payload, expire_seconds=None):
    if not is_key_legal(exchange) or not is_key_legal(queue):
        abort(http_client.BAD_REQUEST, message="Exchange or Queue name is invalid.")

    expire_seconds = expire_seconds or DEFAULT_EXPIRE_SECONDS
    message_id = str(uuid.uuid4())
    message_number = incr_message_number(exchange, exchange_id)
    timestamp = utcnow()
    expires = timestamp + datetime.timedelta(seconds=expire_seconds)
    message = {
        "timestamp": timestamp.isoformat() + "Z",
        "expires": expires.isoformat() + "Z",
        "sender_id": current_user["player_id"],
        "message_id": message_id,
        "message_number": message_number,
        "payload": payload,
        "queue": queue,
        "exchange": exchange,
        "exchange_id": exchange_id,
    }

    key = "messages:%s-%s" % (exchange, exchange_id)
    val = json.dumps(message, default=json_serial)

    lock_key = "lockmessage_%s_%s" % (exchange, exchange_id)
    with g.redis.lock(lock_key):
        k = g.redis.make_key(key)
        g.redis.conn.rpush(k, val)
        g.redis.conn.expire(k, MESSAGE_EXCHANGE_TTL)

    return message


@bp.route('/<string:exchange>/<int:exchange_id>/<string:queue>/<string:message_id>', endpoint='message')
class MessageQueueAPI(MethodView):

    def get(self, exchange, exchange_id, queue, message_id):
        check_can_use_exchange(exchange, exchange_id, read=True)

        key = "messages:%s-%s:%s:%s" % (exchange, exchange_id, queue, message_id)
        val = g.redis.get(key)
        if val:
            return jsonify(json.loads(val))
        else:
            abort(http_client.NOT_FOUND)


@endpoints.register
def endpoint_info(*args):
    return {
        "my_messages": url_for("messages.exchange", exchange="players", exchange_id=current_user["player_id"],
                               _external=True) if current_user else None
    }
