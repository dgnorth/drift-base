"""
    Message box, mostly meant for client-to-client communication
"""

import copy

import datetime
import gevent
import http.client as http_client
import json
import logging
import marshmallow as ma
import operator
from flask import g, url_for, stream_with_context, Response, jsonify
from flask.views import MethodView
from flask_smorest import Blueprint, abort

import driftbase.messages
from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints

log = logging.getLogger(__name__)

bp = Blueprint("messages", "messages", url_prefix="/messages",
               description="Message box, mostly meant for client-to-client communication")
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


# for mocking
def utcnow():
    return datetime.datetime.utcnow()


def _patch_messages(messages):
    """Return all messages patched to match the old API"""
    patched = {}
    for k, v in iter(messages.items()):
        for e in v:
            e.update({'message_number': int(e['message_id'])})
            e.update({'exchange_id': int(e['exchange_id'])})
            e.update({'sender_id': int(e['sender_id'])})
        v.sort(key=operator.itemgetter("message_number"), reverse=True)
        patched[k] = v
    return patched


class MessagesExchangeGetQuerySchema(ma.Schema):
    timeout = ma.fields.Integer(load_default=0)
    messages_after = ma.fields.Integer(load_default=0)
    rows = ma.fields.Integer()


@bp.route('/<string:exchange>/<int:exchange_id>', endpoint='exchange')
class MessagesExchangeAPI(MethodView):
    no_jwt_check = ["GET"]

    @bp.arguments(MessagesExchangeGetQuerySchema, location='query')
    def get(self, args, exchange, exchange_id):
        driftbase.messages.check_can_use_exchange(exchange, exchange_id, read=True)

        timeout = args['timeout']
        messages_after = str(args.get('messages_after'))
        rows = args.get('rows')
        if rows:
            # Old API read rows from newest to oldest
            rows = -int(rows)

        my_player_id = None
        if current_user:
            my_player_id = current_user["player_id"]

        # players can only use player exchanges
        if exchange != "players" and not driftbase.messages.is_service():
            abort(http_client.BAD_REQUEST,
                  message="Only service users can use exchange '%s'" % exchange)

        exchange_full_name = "{}-{}".format(exchange, exchange_id)
        start_time = utcnow()
        poll_timeout = utcnow()

        if timeout > 0:
            poll_timeout += datetime.timedelta(seconds=timeout)
            log.debug("[%s] Long poll - Waiting %s seconds for messages...", my_player_id, timeout)

            def streamer():
                yield " "
                while 1:
                    try:
                        streamer_messages = driftbase.messages.fetch_messages(exchange, exchange_id, messages_after,
                                                                              rows)
                        if streamer_messages:
                            log.debug("[%s/%s] Returning messages after %.1f seconds",
                                      my_player_id, exchange_full_name,
                                      (utcnow() - start_time).total_seconds())
                            yield json.dumps(_patch_messages(streamer_messages), default=driftbase.messages.json_serial)
                            return
                        elif utcnow() > poll_timeout:
                            log.debug("[%s/%s] Poll timeout with no messages after %.1f seconds",
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
                        return

            return Response(stream_with_context(streamer()), mimetype="application/json")
        else:
            messages = driftbase.messages.fetch_messages(exchange, exchange_id, messages_after, rows)
            return jsonify(_patch_messages(messages))


class MessagesQueuePostArgs(ma.Schema):
    message = ma.fields.Dict(required=True)
    expire = ma.fields.Integer()


class MessagesQueuePostResponse(ma.Schema):
    exchange = ma.fields.String()
    exchange_id = ma.fields.Integer()
    queue = ma.fields.String()
    payload = ma.fields.Dict()
    expire_seconds = ma.fields.String()
    message_id = ma.fields.String()
    message_number = ma.fields.Integer()
    url = ma.fields.Url()


@bp.route('/<string:exchange>/<int:exchange_id>/<string:queue>', endpoint='queue')
class MessagesQueueAPI(MethodView):

    @bp.arguments(MessagesQueuePostArgs)
    @bp.response(http_client.OK, MessagesQueuePostResponse)
    def post(self, args, exchange, exchange_id, queue):
        driftbase.messages.check_can_use_exchange(exchange, exchange_id, read=False)
        expire_seconds = args.get("expire") or driftbase.messages.DEFAULT_EXPIRE_SECONDS

        message = driftbase.messages.post_message(
            exchange=exchange,
            exchange_id=exchange_id,
            queue=queue,
            payload=args["message"],
            expire_seconds=expire_seconds,
        )

        # Fill in legacy data the new API doesn't care about
        message['exchange'] = exchange
        message['exchange_id'] = exchange_id
        message['message_number'] = int(message['message_id'])
        message['queue'] = queue
        message['payload'] = args['message']

        log.debug(
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

        return ret


class MessageQueueAPIGetResponse(ma.Schema):
    exchange = ma.fields.String()
    exchange_id = ma.fields.Integer()
    queue = ma.fields.String()
    payload = ma.fields.Dict()
    expire_seconds = ma.fields.String()
    message_id = ma.fields.String()


@bp.route('/<string:exchange>/<int:exchange_id>/<string:queue>/<string:message_id>', endpoint='message')
class MessageQueueAPI(MethodView):

    @bp.response(http_client.OK, MessageQueueAPIGetResponse)
    def get(self, exchange, exchange_id, queue, message_id):
        driftbase.messages.check_can_use_exchange(exchange, exchange_id, read=True)

        message = driftbase.messages.get_message(exchange, exchange_id, message_id)
        if message:
            message['payload'] = json.loads(message['payload'])
            return message
        else:
            abort(http_client.NOT_FOUND)


@endpoints.register
def endpoint_info(*args):
    return {
        "my_messages": url_for("messages.exchange", exchange="players", exchange_id=current_user["player_id"],
                               _external=True) if current_user else None
    }
