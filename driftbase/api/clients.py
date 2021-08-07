"""
    A client is required to register itself via POST /clients after it
    has authenticated. Before the client shuts down it should deregister itself
    via DELETE /clients/client_id

    During play the client is expected to heartbeat with PUT /clients/client_id
    every 30 seconds. If it misses heartbeats for 5 minutes it will be
    deregistered automatically (by a timestamp check in sql returning clients).
"""

import datetime
import http.client as http_client
import json
import logging
import marshmallow as ma
from flask import request, url_for, g, current_app
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema

from drift.core.extensions.jwt import current_user, issue_token
from drift.core.extensions.urlregistry import Endpoints
from drift.utils import json_response, Url
from driftbase.config import get_client_heartbeat_config
from driftbase.models.db import (
    User, CorePlayer, Client, UserIdentity
)
from driftbase.utils import url_client

log = logging.getLogger(__name__)
bp = Blueprint("clients", __name__, url_prefix="/clients", description="Client registration")
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


# for mocking
def utcnow():
    return datetime.datetime.utcnow()


client_descriptions = {
    'client_type': "Type of client as reported by the client itself. Example: UE4",
    'build': "Build/version information about the client executable",
    'version': "Version information about the client executable",
    'platform_type': "Name of the platform (e.g. Windows, IpadPro, etc)",
    'platform_version': "Version of the platform (e.g. Windows 10, etc)",
    'app_guid': "Globally nique name of the application",
    'platform_info': "Information about the platform in JSON format",
    'num_heartbeats': "Number of times a heartbeat has been sent on this session",
}


class ClientSchema(SQLAlchemyAutoSchema):
    class Meta:
        load_instance = True
        include_relationships = True
        strict = True
        model = Client
        exclude = ()

    client_url = Url('clients.entry',
                     doc="Fully qualified URL of the client resource",
                     client_id='<client_id>')


class ClientPostRequestSchema(ma.Schema):
    client_type = ma.fields.Str(metadata=dict(description=client_descriptions['client_type']))
    build = ma.fields.Str(metadata=dict(description=client_descriptions['build']))
    platform_type = ma.fields.Str(metadata=dict(description=client_descriptions['platform_type']))
    app_guid = ma.fields.Str(metadata=dict(description=client_descriptions['app_guid']))
    version = ma.fields.Str(metadata=dict(description=client_descriptions['version']))
    platform_version = ma.fields.Str(metadata=dict(description=client_descriptions['platform_version']))
    platform_info = ma.fields.Raw(metadata=dict(description=client_descriptions['platform_info']))


class ClientPostResponseSchema(ma.Schema):
    class Meta:
        strict = True

    client_id = ma.fields.Int()
    player_id = ma.fields.Int()
    user_id = ma.fields.Int()
    server_time = ma.fields.Str()
    next_heartbeat_seconds = ma.fields.Int()
    heartbeat_timeout = ma.fields.Str()
    jti = ma.fields.Str()
    jwt = ma.fields.Str()
    url = ma.fields.Str(metadata=dict(description="Fully qualified URL of the client resource"))


class ClientHeartbeatSchema(ma.Schema):
    num_heartbeats = ma.fields.Integer(metadata=dict(description=client_descriptions['num_heartbeats']))
    last_heartbeat = ma.fields.DateTime(metadata=dict(description="Timestamp of the previous heartbeat"))
    this_heartbeat = ma.fields.DateTime(metadata=dict(description="Timestamp of this heartbeat"))
    next_heartbeat = ma.fields.DateTime(metadata=dict(description="Timestamp when the next heartbeat is expected"))
    next_heartbeat_seconds = ma.fields.Integer(
        metadata=dict(description="Number of seconds until the next heartbeat is expected"))
    heartbeat_timeout = ma.fields.DateTime(
        metadata=dict(description="Timestamp when the client times out if no heartbeat is received"))
    heartbeat_timeout_seconds = ma.fields.Integer(
        metadata=dict(description="Number of seconds until the client times out if no heartbeat is received"))


class ClientsGetQuerySchema(ma.Schema):
    player_id = ma.fields.Integer(load_default=None,
                                  metadata=dict(description="Optional ID of a player to return sessions for"))


@bp.route('/', endpoint='list')
class ClientsAPI(MethodView):
    no_jwt_check = ['GET']

    @bp.arguments(ClientsGetQuerySchema, location='query')
    @bp.response(http_client.OK, ClientSchema(many=True))
    def get(self, args):
        """
        Retrieve all active clients.

        If a client has not heartbeat
        for 5 minutes it is considered disconnected and is not returned by
        this endpoint
        """
        _, heartbeat_timeout = get_client_heartbeat_config()
        min_heartbeat_time = utcnow() - datetime.timedelta(seconds=heartbeat_timeout)
        query = g.db.query(Client).filter(Client.heartbeat >= min_heartbeat_time)
        if args["player_id"]:
            query = query.filter(Client.player_id == args["player_id"])
        rows = query.all()
        return rows

    @bp.arguments(ClientPostRequestSchema)
    @bp.response(http_client.CREATED, ClientPostResponseSchema)
    def post(self, args):
        """
        Register a client

        Registers a newly connected client and get a JWT with the new client_id back
        """
        now = utcnow()

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
        jti = new_token['payload']["jti"]

        resource_url = url_client(client_id)
        response_header = {
            "Location": resource_url,
        }
        log.info("Client %s for user %s / player %s has been registered",
                 client_id, user_id, player_id)
        heartbeat_period, heartbeat_timeout = get_client_heartbeat_config()
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

        return ret


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
        abort(http_client.NOT_FOUND, description="This client is not registered", )
    if client.player_id != player_id:
        log.error("User attempted to update/delete a client that is "
                  "registered to another player, %s vs %s",
                  player_id, client.player_id)
        abort(http_client.NOT_FOUND, description="This is not your client", )

    return client


@bp.route('/<int:client_id>', endpoint='entry')
class ClientAPI(MethodView):
    """
    Client API. This is used by the game clients to
    register themselves as connected-to-the-backend and to heartbeat
    to let the backend know that they are still connected.
    """

    @bp.response(http_client.OK, ClientSchema())
    def get(self, client_id):
        """
        Find client by ID

        Get information about a single client. Just dumps out the DB row as json
        """
        client = get_client(client_id)
        if client.status == "deleted":
            abort(http_client.NOT_FOUND)

        return client

    @bp.response(http_client.OK, ClientHeartbeatSchema())
    def put(self, client_id):
        """
        Client heartbeat

        Heartbeat for client registration.
        """
        client = get_client(client_id)

        now = utcnow()
        heartbeat_period, heartbeat_timeout = get_client_heartbeat_config()

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
        Deregister client

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
    ret = {"clients": url_for("clients.list", _external=True)}
    ret["my_client"] = None
    if current_user and current_user.get("client_id"):
        ret["my_client"] = url_for("clients.entry", client_id=current_user.get("client_id"),
                                   _external=True)
    return ret
