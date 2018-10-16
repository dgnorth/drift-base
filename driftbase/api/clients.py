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

import six
from six.moves import http_client

from flask import request, url_for, g, current_app
from flask_restplus import Namespace, Resource, reqparse, abort

from drift.utils import json_response, url_client
from drift.core.extensions.urlregistry import Endpoints
from drift.core.extensions.jwt import current_user, issue_token
from driftbase.db.models import User, CorePlayer, Client, UserIdentity
from flask_restplus import fields, marshal

log = logging.getLogger(__name__)
namespace = Namespace("clients", "Client registration")
endpoints = Endpoints()

DEFAULT_HEARTBEAT_PERIOD = 30
DEFAULT_HEARTBEAT_TIMEOUT = 300


def drift_init_extension(app, api, **kwargs):
    api.add_namespace(namespace)
    endpoints.init_app(app)


# for mocking
def utcnow():
    return datetime.datetime.utcnow()


descriptions = {
    'client_type': "Type of client as reported by the client itself. Example: UE4",
    'build': "Build/version information about the client executable",
    'version': "Version information about the client executable",
    'platform_type': "Name of the platform (e.g. Windows, IpadPro, etc)",
    'platform_version': "Version of the platform (e.g. Windows 10, etc)",
    'app_guid': "Globally nique name of the application",
    'platform_info': "Information about the platform in JSON format",
    'num_heartbeats' : "Number of times a heartbeat has been sent on this session",
}
client_statuses = ['active', 'deleted', 'timeout', 'usurped']
client_model = namespace.model('Client', {
    'client_id': fields.Integer(description="Unique ID of the client connection"),
    'client_type': fields.String(description=descriptions['client_type']),
    'user_id': fields.Integer(description="Unique ID of the user who owns this session (> 100000000)"),
    'player_id': fields.Integer(description="Unique ID of the player who owns this session"),
    'create_date': fields.DateTime(description="Timestamp when this session was created"),
    'modify_date': fields.DateTime(description="Timestamp when this session object was last modified"),
    'build': fields.String(description=descriptions['build']),
    'version': fields.String(description=descriptions['version']),
    'platform_type': fields.String(description=descriptions['platform_type']),
    'platform_version': fields.String(description=descriptions['platform_version']),
    'app_guid': fields.String(description=descriptions['app_guid']),
    'heartbeat': fields.DateTime(description="Last time the client sent a heartbeat on this session"),
    'num_heartbeats': fields.Integer(description=descriptions['num_heartbeats']),
    'ip_address': fields.String(description="IPv4 address of the client"),
    'num_requests': fields.Integer(description="Number of requests that have been sent to the drift-base app in this session"),
    'platform_info': fields.Raw(description=descriptions['platform_info']),
    'identity_id': fields.Integer(description="Unique ID of the identity associated with this connection"),
    'status': fields.String(enum=client_statuses, description="Current status of this client session"),
    'details': fields.Raw(description="Information about the status of the client session in JSON format"),
    'client_url': fields.Url('client', absolute=True,
                             description="Fully qualified url of the client resource"),
    'user_url': fields.Url('users.user', absolute=True,
                           description="Fully qualified url of the user resource"),
    'player_url': fields.Url('players.player', absolute=True,
                             description="Fully qualified url of the player resource")
})

client_registration_model = namespace.model('ClientRegistration', {
    'client_id': fields.Integer(description="Unique ID of the client connection"),
    'user_id': fields.Integer(description="Unique ID of the user who owns this session (> 100000000)"),
    'player_id': fields.Integer(description="Unique ID of the player who owns this session"),
    'url': fields.Url('client', absolute=True,
                             description="Fully qualified url of the client resource"),
    'server_time': fields.DateTime(description="Current Server time UTC"),
    'next_heartbeat_seconds': fields.Integer(description="Number of seconds recommended for the client to heartbeat."),
    'heartbeat_timeout': fields.DateTime(description="Timestamp when the client will be removed if heartbeat has not been received"),
    'jti': fields.String(description="JTI lookup key of new JWT"),
    'jwt': fields.String(description="New JWT token that includes client information"),
})

client_heartbeat_model = namespace.model('ClientHeartbeat', {
    "num_heartbeats": fields.Integer(description=descriptions['num_heartbeats']),
    "last_heartbeat": fields.DateTime(description="Timestamp of the previous heartbeat"),
    "this_heartbeat": fields.DateTime(description="Timestamp of this heartbeat"),
    "next_heartbeat": fields.DateTime(description="Timestamp when the next heartbeat is expected"),
    "next_heartbeat_seconds": fields.Integer(description="Number of seconds until the next heartbeat is expected"),
    "heartbeat_timeout": fields.DateTime(description="Timestamp when the client times out if no heartbeat is received"),
    "heartbeat_timeout_seconds": fields.Integer(description="Number of seconds until the client times out if no heartbeat is received"),
})


@namespace.route('/', endpoint='clients')
class ClientsAPI(Resource):
    no_jwt_check = ['GET']
    # GET args
    get_parser = reqparse.RequestParser()
    get_parser.add_argument('player_id', type=int,
                          help="Optional ID of a player to return sessions for")

    @namespace.expect(get_parser)
    @namespace.marshal_with(client_model, as_list=True)
    def get(self):
        """
        Retrieves all active clients. If a client has not heartbeat
        for 5 minutes it is considered disconnected and is not returned by
        this endpoint
        """
        args = self.get_parser.parse_args()

        heartbeat_timeout = current_app.config.get("heartbeat_timeout", DEFAULT_HEARTBEAT_TIMEOUT)
        min_heartbeat_time = utcnow() - datetime.timedelta(seconds=heartbeat_timeout)
        query = g.db.query(Client).filter(Client.heartbeat >= min_heartbeat_time)
        if args["player_id"]:
            query = query.filter(Client.player_id == args["player_id"])
        rows = query.all()
        return rows

    post_parser = reqparse.RequestParser(bundle_errors=True)
    post_parser.add_argument('client_type', type=str, required=True,
                             help=descriptions['client_type'])
    post_parser.add_argument('build', type=str, required=True,
                             help=descriptions['build'])
    post_parser.add_argument('platform_type', type=str, required=True,
                             help=descriptions['platform_type'])
    post_parser.add_argument('app_guid', type=str, required=True,
                             help=descriptions['app_guid'])
    post_parser.add_argument('version', type=str, required=True,
                             help=descriptions['version'])
    post_parser.add_argument('platform_version', type=str,
                             help=descriptions['platform_version'])
    post_parser.add_argument('platform_info', type=str,
                             help=descriptions['platform_info'])
    @namespace.expect(post_parser)
    @namespace.marshal_with(client_registration_model, code=http_client.CREATED)
    def post(self):
        """
        Register a new connected client.
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

        user = g.db.query(User).get(user_id)
        user.logon_date = now
        user.num_logons += 1
        user.client_id = client_id

        my_identity = g.db.query(UserIdentity).get(identity_id)
        my_identity.logon_date = datetime.datetime.utcnow()
        my_identity.num_logons += 1
        my_identity.last_ip_address = request.remote_addr

        player = g.db.query(CorePlayer).get(player_id)
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
        new_token = issue_token(payload)

        jwt = new_token["token"]
        jti = new_token["jti"]

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


def get_client(client_id):
    """
    Check whether the caller has access to this client and return a
    response if he does not. Otherwise return None
    """
    player_id = current_user["player_id"]
    client = g.db.query(Client).get(client_id)
    if not client:
        log.warning("User attempted to retrieve a client that is not registered: %s" %
                    player_id)
        abort(http_client.NOT_FOUND, description="This client is not registered",)
    if client.player_id != player_id:
        log.error("User attempted to update/delete a client that is "
                  "registered to another player, %s vs %s",
                  player_id, client.player_id)
        abort(http_client.NOT_FOUND, description="This is not your client",)

    return client


@namespace.route('/<int:client_id>', endpoint='client')
class ClientAPI(Resource):
    """
    Client API. This is used by the game clients to
    register themselves as connected-to-the-backend and to heartbeat
    to let the backend know that they are still connected.
    """
    @namespace.marshal_with(client_model)
    def get(self, client_id):
        """
        Get information about a single client. Just dumps out the DB row as json
        """
        client = get_client(client_id)
        if client.status == "deleted":
            abort(http_client.NOT_FOUND)

        return client

    @namespace.marshal_with(client_heartbeat_model)
    def put(self, client_id):
        """
        Heartbeat for client registration.
        """
        client = get_client(client_id)

        now = utcnow()
        heartbeat_period = current_app.config.get("heartbeat_period", DEFAULT_HEARTBEAT_PERIOD)
        heartbeat_timeout = current_app.config.get("heartbeat_timeout", DEFAULT_HEARTBEAT_TIMEOUT)

        last_heartbeat = client.heartbeat
        if last_heartbeat + datetime.timedelta(seconds=heartbeat_timeout) < now:
            msg = "Heartbeat timeout. Last heartbeat was at {} and now we are at {}" \
                  .format(last_heartbeat, now)
            log.info(msg)
            abort(http_client.NOT_FOUND, message=msg)

        client.heartbeat = now
        client.num_heartbeats += 1
        g.db.commit()
        ret = {
            "num_heartbeats": client.num_heartbeats,
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
        client = get_client(client_id)
        if client.status == "deleted":
            abort(http_client.NOT_FOUND)

        client.heartbeat = utcnow()
        client.num_heartbeats += 1
        client.status = "deleted"
        g.db.commit()

        log.info("Client %s from player %s has been unregistered",
                 client_id, current_user["player_id"])

        return json_response("Client has been closed. Please terminate the client.",
                             http_client.OK)


@endpoints.register
def endpoint_info(*args):
    ret = {"clients": url_for("clients", _external=True)}
    ret["my_client"] = None
    if current_user and current_user.get("client_id"):
        ret["my_client"] = url_for("client", client_id=current_user.get("client_id"),
                                   _external=True)
    return ret
