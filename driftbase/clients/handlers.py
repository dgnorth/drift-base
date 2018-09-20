# -*- coding: utf-8 -*-
"""
    A client is required to register itself via POST /clients after it
    has authenticated. Before the client shuts down it should deregister itself
    via DELETE /clients/client_id

    During play the client is expected to heartbeat with PUT /clients/client_id
    every 30 seconds. If it misses heartbeats for 5 minutes it will be
    deregistered automatically (by a timestamp check in sql returning clients).
"""

import logging, datetime, json

from six.moves import http_client

from flask import Blueprint, request, url_for, g, current_app
from flask_restful import Api, Resource, reqparse, abort

from drift.utils import json_response, url_player, url_user, url_client
from drift.core.extensions.schemachecker import simple_schema_request
from drift.urlregistry import register_endpoints
from drift.core.extensions.jwt import current_user, issue_token
from driftbase.db.models import User, CorePlayer, Client, UserIdentity

log = logging.getLogger(__name__)
bp = Blueprint("clients", __name__)
api = Api(bp)

DEFAULT_HEARTBEAT_PERIOD = 30
DEFAULT_HEARTBEAT_TIMEOUT = 300


# for mocking
def utcnow():
    return datetime.datetime.utcnow()


class ClientsAPI(Resource):
    # GET args
    get_args = reqparse.RequestParser()
    get_args.add_argument("name", type=unicode)
    get_args.add_argument("player_id", type=int)

    def get(self):
        """
        Retrieves all active clients. If a client has not heartbeat
        for 5 minutes it is considered disconnected and is not returned by
        this endpoint
        """
        args = self.get_args.parse_args()

        ret = []
        heartbeat_timeout = current_app.config.get("heartbeat_timeout", DEFAULT_HEARTBEAT_TIMEOUT)
        min_heartbeat_time = utcnow() - datetime.timedelta(seconds=heartbeat_timeout)
        filters = [Client.heartbeat >= min_heartbeat_time]
        if args["player_id"]:
            filters.append(Client.player_id == args["player_id"])
        rows = g.db.query(Client).filter(*filters)
        for row in rows:
            data = row.as_dict()
            data["client_url"] = url_client(row.client_id)
            data["player_url"] = url_player(row.player_id)
            ret.append(data)
        return ret

    @simple_schema_request({
        "client_type": {"type": "string", },
        "build": {"type": "string", },
        "platform_type": {"type": "string", },
        "app_guid": {"type": "string", },
        "version": {"type": "string", },
        "platform_version": {"type": "string", },
        "platform_info": {"type": ["string", "object"], },
    }, required=["client_type", "build", "platform_type", "app_guid", "version"])
    def post(self):
        """
        Register a new connected client
        """
        now = utcnow()

        args = request.json
        player_id = current_user["player_id"]
        user_id = current_user["user_id"]
        identity_id = current_user["identity_id"]
        platform_info = args.get("platform_info")
        if platform_info and not isinstance(platform_info, dict):
            platform_info = json.loads(platform_info)
        platform_version = None
        if args.get("platform_version"):
            platform_version = args.get("platform_version")[:20]
        client = Client(user_id=user_id,
                        player_id=player_id,
                        build=args.get("build"),
                        platform_type=args.get("platform_type"),
                        platform_version=platform_version,
                        platform_info=platform_info,
                        app_guid=args.get("app_guid"),
                        version=args.get("version"),
                        ip_address=request.remote_addr,
                        client_type=args.get("client_type"),
                        identity_id=identity_id,
                        status="active"
                        )
        g.db.add(client)
        g.db.commit()
        client_id = client.client_id

        user = g.db.query(User).filter(User.user_id == user_id).first()
        user.logon_date = now
        user.num_logons += 1
        user.client_id = client_id

        my_identity = g.db.query(UserIdentity).get(identity_id)
        my_identity.logon_date = datetime.datetime.utcnow()
        my_identity.num_logons += 1
        my_identity.last_ip_address = request.remote_addr

        player = g.db.query(CorePlayer).filter(CorePlayer.player_id == player_id).first()
        player.logon_date = now
        player.num_logons += 1

        g.db.commit()

        # if we find a client already registered in redis, mark it as 'usurped'
        cache_key = "clients:uid_%s" % user_id
        old_client_id = g.redis.get(cache_key)
        if old_client_id:
            old_client = g.db.query(Client).get(old_client_id)
            if old_client and old_client.is_online:
                old_client.status = "usurped"
                details = old_client.details or {}
                details["reason"] = "Usurped by client %s" % client_id
                old_client.details = details
                g.db.commit()
                log.info("Disconnected client %s for user %s. New client is %s",
                         old_client_id, user_id, client_id)

        # set our new client_id as the one and only client_id for this user
        g.redis.set(cache_key, client_id)

        payload = dict(current_user)
        payload["client_id"] = client_id
        ret = issue_token(payload)

        jwt = ret["token"]
        jti = ret["jti"]

        resource_url = url_client(client_id)
        response_header = {
            "Location": resource_url,
        }
        log.info("Client %s for user %s / player %s has been registered",
                 client_id, user_id, player_id)
        heartbeat_period = current_app.config.get("heartbeat_period", DEFAULT_HEARTBEAT_PERIOD)
        heartbeat_timeout = current_app.config.get("heartbeat_timeout", DEFAULT_HEARTBEAT_TIMEOUT)
        ret = {
            "client_id": client_id,
            "player_id": player_id,
            "user_id": user_id,
            "url": resource_url,
            "server_time": utcnow(),
            "next_heartbeat_seconds": heartbeat_period,
            "heartbeat_timeout": utcnow() + datetime.timedelta(seconds=heartbeat_timeout),
            "jti": jti,
            "jwt": jwt,
        }

        current_app.extensions['messagebus'].publish_message(
            'clients',
            {'event': 'created', 'payload': payload, 'url': resource_url}
        )

        return ret, http_client.CREATED, response_header


class ClientAPI(Resource):
    """
    Client API. This is used by the game clients to
    register themselves as connected-to-the-backend and to heartbeat
    to let the backend know that they are still connected.
    """
    def validate_call(self, client_id):
        """
        Check whether the caller has access to this client and return a
        response if he does not. Otherwise return None
        """
        player_id = current_user["player_id"]
        client = g.db.query(Client).filter(Client.client_id == client_id).first()
        if not client:
            log.warning("User attempted to retrieve a client that is not registered: %s" %
                        player_id)
            abort(http_client.NOT_FOUND, description="This client is not registered",)
        if client.player_id != player_id:
            log.error("User attempted to update/delete a client that is "
                      "registered to another player, %s vs %s",
                      player_id, client.player_id)
            abort(http_client.NOT_FOUND, description="This is not your client",)

        return None

    def get(self, client_id):
        """
        Get information about a single client. Just dumps out the DB row as json
        """
        ret = self.validate_call(client_id)
        if ret:
            return ret

        client = g.db.query(Client).get(client_id)
        if not client or client.status == "deleted":
            abort(http_client.NOT_FOUND)
        ret = client.as_dict()
        ret["url"] = url_client(client_id)
        ret["player_url"] = url_player(client.player_id)
        ret["user_url"] = url_user(client.user_id)

        log.debug("Returning info for client %s", client_id)
        return ret

    def put(self, client_id):
        """
        Heartbeat for client registration
        """
        ret = self.validate_call(client_id)
        if ret:
            return ret

        now = utcnow()
        heartbeat_period = current_app.config.get("heartbeat_period", DEFAULT_HEARTBEAT_PERIOD)
        heartbeat_timeout = current_app.config.get("heartbeat_timeout", DEFAULT_HEARTBEAT_TIMEOUT)

        client = g.db.query(Client).get(client_id)
        last_heartbeat = client.heartbeat
        if last_heartbeat + datetime.timedelta(seconds=heartbeat_timeout) < now:
            msg = "Heartbeat timeout. Last heartbeat was at {} and now we are at {}" \
                  .format(last_heartbeat, now)
            log.info(msg)
            abort(http_client.NOT_FOUND, message=msg)

        client.heartbeat = now
        client.num_heartbeats += 1
        g.db.commit()
        ret = {"num_heartbeats": client.num_heartbeats,
               "last_heartbeat": last_heartbeat,
               "this_heartbeat": client.heartbeat,
               "next_heartbeat": client.heartbeat + datetime.timedelta(seconds=heartbeat_period),
               "next_heartbeat_seconds": heartbeat_period,
               "heartbeat_timeout": utcnow() + datetime.timedelta(seconds=heartbeat_timeout),
               "heartbeat_timeout_seconds": heartbeat_timeout,
               }

        log.debug("player %s has updated heartbeat for client %s. Heartbeat count is %s",
                  current_user["player_id"], client_id, client.num_heartbeats)

        return ret

    def delete(self, client_id):
        """
        Deregister an already registered client. Should return status 200 if successful.
        """
        ret = self.validate_call(client_id)
        if ret:
            return ret
        client = g.db.query(Client).get(client_id)
        if not client or client.status == "deleted":
            abort(http_client.NOT_FOUND)
        client.heartbeat = utcnow()
        client.num_heartbeats += 1
        client.status = "deleted"
        g.db.commit()

        log.info("Client %s from player %s has been unregistered",
                 client_id, current_user["player_id"])

        return json_response("Client has been closed. Please terminate the client.",
                             http_client.OK)


api.add_resource(ClientsAPI, '/clients', endpoint="clients")
api.add_resource(ClientAPI, '/clients/<int:client_id>', endpoint="client")


@register_endpoints
def endpoint_info(*args):
    ret = {"clients": url_for("clients.clients", _external=True)}
    ret["my_client"] = None
    if current_user and current_user.get("client_id"):
        ret["my_client"] = url_for("clients.client", client_id=current_user.get("client_id"),
                                   _external=True)
    return ret
