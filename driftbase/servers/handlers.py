# -*- coding: utf-8 -*-

import logging, httplib, datetime
import uuid

from flask import Blueprint, request, url_for, g, current_app
from flask_restful import Api, Resource, reqparse, abort

from drift.utils import url_player
from drift.core.extensions.schemachecker import simple_schema_request
from drift.urlregistry import register_endpoints
from drift.auth.jwtchecker import current_user, requires_roles

from driftbase.db.models import Machine, Server, Match, ServerDaemonCommand

log = logging.getLogger(__name__)
bp = Blueprint("servers", __name__)
api = Api(bp)

SECONDS_BETWEEN_HEARTBEAT = 30


def utcnow():
    return datetime.datetime.utcnow()


class ServersAPI(Resource):
    get_args = reqparse.RequestParser()
    get_args.add_argument("machine_id", type=int, required=False)
    get_args.add_argument("rows", type=int, required=False)

    @requires_roles("service")
    def get(self):
        """
        Get a list of the last 100 battleservers that have been registered in
        the system.
        """
        args = self.get_args.parse_args()
        num_rows = args.get("rows") or 100
        query = g.db.query(Server)
        if args.get("machine_id"):
            query = query.filter(Server.machine_id == args.get("machine_id"))
        query = query.order_by(-Server.server_id)
        query = query.limit(num_rows)
        rows = query.all()

        ret = []
        for row in rows:
            record = row.as_dict()
            record["url"] = url_for("servers.entry", server_id=row.server_id, _external=True)
            ret.append(record)
        return ret

    @requires_roles("service")
    @simple_schema_request({
        "machine_id": {"type": "number", },
        "version": {"type": "string", },
        "public_ip": {"format": "ip-address", },
        "port": {"type": "number", },
        "command_line": {"type": "string", },
        "command_line_custom": {"type": "string", },
        "pid": {"type": "number", },
        "status": {"type": "string", },
        "image_name": {"type": "string", },
        "instance_name": {"type": "string", },
        "branch": {"type": "string", },
        "commit_id": {"type": "string", },
        "version": {"type": "string", },
        "process_info": {"type": "object", },
        "details": {"type": "object", },
        "repository": {"type": "string", },
        "ref": {"type": "string", },
        "build": {"type": "string", },
        "build_number": {"type": "number", },
        "target_platform": {"type": "string", },
        "build_info": {"type": "object", },
        "placement": {"type": "string", },
    }, required=[])
    def post(self):
        """
        The daemon process (and server, for local development) post here
        to register the server instance with the backend. You need to
        register the server before you can register a battle.
        """
        args = request.json
        machine_id = args.get("machine_id")
        log.info("registering a server on machine_id %s, realm %s and public_ip %s",
                 machine_id, args.get("realm"), args.get("public_ip"))
        # If we don't already have a machine we make one just in time now on the realm "Local".
        # This is to support local devs where an external daemon is not running and the server iself
        # does this registration without a prior registration on the machines endpoint
        if not machine_id:
            realm = "local"
            instance_name = args.get("instance_name")
            placement = args.get("placement") or "<unknown placement>"
            if not instance_name:
                abort(httplib.BAD_REQUEST, description="You need to supply an instance_name")

            machine = g.db.query(Machine).filter(Machine.realm == realm,
                                                 Machine.instance_name == instance_name,
                                                 Machine.placement == placement).first()
            if machine:
                machine_id = machine.machine_id
                log.info("machine_id %s found for server", machine_id)
            else:
                machine = Machine(realm=realm, instance_name=instance_name,
                                  placement=placement, server_count=0)
                g.db.add(machine)
                g.db.flush()
                machine_id = machine.machine_id
                log.info("Created machine_id %s for server instance \"%s\"",
                         machine_id, instance_name)
        else:
            machine = g.db.query(Machine).get(machine_id)
            if not machine:
                abort(httplib.NOT_FOUND, description="Machine %s was not found" % machine_id)

        token = str(uuid.uuid4()).replace("-", "")[:20]

        server = Server(machine_id=machine_id,
                        version=args.get("version"),
                        public_ip=args.get("public_ip"),
                        port=args.get("port"),
                        command_line=args.get("command_line"),
                        command_line_custom=args.get("command_line_custom"),
                        pid=args.get("pid"),
                        status=args.get("status"),
                        image_name=args.get("image_name"),
                        branch=args.get("branch"),
                        commit_id=args.get("commit_id"),
                        process_info=args.get("process_info"),
                        details=args.get("details"),
                        repository=args.get("repository"),
                        ref=args.get("ref"),
                        build=args.get("build"),
                        build_number=args.get("build_number"),
                        target_platform=args.get("target_platform"),
                        build_info=args.get("build_info"),
                        token=token
                        )
        g.db.add(server)

        machine.server_count += 1
        machine.server_date = utcnow()
        g.db.commit()

        server_id = server.server_id

        resource_url = url_for("servers.entry", server_id=server_id, _external=True)
        machine_url = url_for("machines.entry", machine_id=machine_id, _external=True)
        heartbeat_url = url_for("servers.heartbeat", server_id=server_id, _external=True)
        commands_url = url_for("servers.commands", server_id=server_id, _external=True)
        response_header = {
            "Location": resource_url,
        }
        log.info("Server %s has been registered on machine_id %s", server_id, machine_id)
        return {"server_id": server_id,
                "url": resource_url,
                "machine_id": machine_id,
                "machine_url": machine_url,
                "heartbeat_url": heartbeat_url,
                "commands_url": commands_url,
                "token": token,
                }, httplib.CREATED, response_header


class ServerAPI(Resource):
    """
    Interface to battle servers instances. A battleserver instance is
    a single run of a battleserver executable. The battleserver will
    have a single battle on it. You should never have a battle resource
    without an associated battleserver resource.
    """
    @requires_roles("service")
    def get(self, server_id):
        """
        Get information about a single battle server instance.
        Returns information from the machine and the associated
        battle if found.
        """
        server = g.db.query(Server).get(server_id)

        if not server:
            log.warning("Requested a non-existant battleserver: %s", server_id)
            abort(httplib.NOT_FOUND, description="Server not found")

        machine_id = server.machine_id
        record = server.as_dict()
        record["url"] = url_for("servers.entry", server_id=server_id, _external=True)
        record["heartbeat_url"] = url_for("servers.heartbeat", server_id=server_id, _external=True)
        record["commands_url"] = url_for("servers.commands", server_id=server_id, _external=True)

        record["machine_url"] = None
        if machine_id:
            machine = g.db.query(Machine).get(machine_id)
            if machine:
                record["machine"] = machine.as_dict()
                record["machine_url"] = url_for("machines.entry", machine_id=machine_id,
                                                _external=True)

        matches = []
        rows = g.db.query(Match).filter(Match.server_id == server_id).all()
        for row in rows:
            match_id = row.match_id
            match = {"match_id": match_id,
                     "url": url_for("matches.entry", match_id=match_id, _external=True),
                     }
            matches.append(match)
        record["matches"] = matches

        commands = []
        rows = g.db.query(ServerDaemonCommand).filter(ServerDaemonCommand.server_id == server_id,
                                                      ServerDaemonCommand.status == "pending").all()
        for row in rows:
            command = {"command_id": row.command_id,
                       "command": row.command,
                       "arguments": row.arguments,
                       "create_date": row.create_date,
                       "url": url_for("servers.command", server_id=server_id,
                                      command_id=row.command_id, _external=True)
                       }
            commands.append(command)
        record["pending_commands"] = commands

        log.debug("Returning info for battleserver %s", server_id)
        return record

    @requires_roles("service")
    @simple_schema_request({
        "machine_id": {"type": "number", },
        "status": {"type": "string", },
        "version": {"type": "string", },
        "public_ip": {"format": "ip-address", },
        "port": {"type": "number", },
        "command_line": {"type": "string", },
        "command_line_custom": {"type": "string", },
        "pid": {"type": "number", },
        "image_name": {"type": "string", },
        "error": {"type": "string", },
        "branch": {"type": "string", },
        "commit_id": {"type": "string", },
        "version": {"type": "string", },
        "process_info": {"type": "object", },
        "details": {"type": "object", },
        "repository": {"type": "string", },
        "ref": {"type": "string", },
        "build": {"type": "string", },
        "build_number": {"type": "number", },
        "target_platform": {"type": "string", },
        "build_info": {"type": "object", },
    }, required=["status"])
    def put(self, server_id):
        """
        The battleserver management (celery) process calls this to update
        the status of running a specific battleserver task
        """
        args = request.json
        log.info("Updating battleserver %s", server_id)
        server = g.db.query(Server).get(server_id)
        if not server:
            abort(httplib.NOT_FOUND)
        if args.get("status"):
            log.info("Changing status of server %s from '%s' to '%s'",
                     server_id, server.status, args["status"])
        for arg in args:
            setattr(server, arg, args[arg])
        g.db.commit()

        machine_id = server.machine_id
        machine_url = None
        if machine_id:
            machine_url = url_for("machines.entry", machine_id=machine_id, _external=True)

        return {"server_id": server_id,
                "url": url_for("servers.entry", server_id=server_id, _external=True),
                "machine_id": machine_id,
                "machine_url": machine_url,
                "heartbeat_url": url_for("servers.heartbeat", server_id=server_id, _external=True),
                "next_heartbeat_seconds": SECONDS_BETWEEN_HEARTBEAT,
                }, httplib.OK, None


class ServerHeartbeatAPI(Resource):
    """
    Thin heartbeat API
    """
    @requires_roles("service")
    def put(self, server_id):
        """
        Battleserver heartbeat
        """
        log.debug("%s is heartbeating battleserver %s",
                  current_user.get("user_name", "unknown"), server_id)
        server = g.db.query(Server).get(server_id)
        server.heartbeat_count += 1
        server.heartbeat_date = utcnow()
        g.db.commit()

        return {"next_heartbeat_seconds": SECONDS_BETWEEN_HEARTBEAT, }, httplib.OK, None


class ServerCommandsAPI(Resource):
    """
    Commands for the battleserver daemon
    """
    @requires_roles("service")
    @simple_schema_request({
        "command": {"type": "string", },
        "arguments": {"type": "object", },
        "details": {"type": "object", },
    }, required=["command"])
    def post(self, server_id):
        """
        Add a new command for the daemon to execute
        """
        server = g.db.query(Server).get(server_id)
        if not server:
            abort(httplib.NOT_FOUND)

        args = request.json
        status = "pending"
        command = ServerDaemonCommand(server_id=server_id,
                                      command=args["command"],
                                      arguments=args.get("arguments"),
                                      details=args.get("details"),
                                      status=status,
                                      )
        g.db.add(command)
        g.db.commit()

        resource_url = url_for("servers.command", server_id=server_id,
                               command_id=command.command_id, _external=True)
        return {"command_id": command.command_id,
                "url": resource_url,
                "status": status,
                }, httplib.CREATED, None

    @requires_roles("service")
    def get(self, server_id):
        rows = g.db.query(ServerDaemonCommand) \
                   .filter(ServerDaemonCommand.server_id == server_id) \
                   .all()
        ret = []
        for r in rows:
            command = r.as_dict()
            command["url"] = url_for("servers.command",
                                     server_id=server_id,
                                     command_id=r.command_id,
                                     _external=True)
            ret.append(command)
        return ret


class ServerCommandAPI(Resource):
    @requires_roles("service")
    @simple_schema_request({
        "status": {"type": "string", },
        "details": {"type": "object", },
    }, required=["status"])
    def patch(self, server_id, command_id):
        return self._patch(server_id, command_id)
    @requires_roles("service")
    @simple_schema_request({
        "status": {"type": "string", },
        "details": {"type": "object", },
    }, required=["status"])
    def put(self, server_id, command_id):
        return self._patch(server_id, command_id)

    def _patch(self, server_id, command_id):
        """
        Add a new command for the daemon to execute
        """
        server = g.db.query(Server).get(server_id)
        if not server:
            abort(httplib.NOT_FOUND)

        args = request.json
        row = g.db.query(ServerDaemonCommand).get(command_id)
        row.status = args["status"]
        row.status_date = utcnow()
        if "details" in args:
            row.details = args["details"]
        g.db.commit()

        ret = row.as_dict()
        ret["url"] = url_for("servers.command", server_id=server_id, command_id=row.command_id,
                             _external=True)
        return ret

    @requires_roles("service")
    def get(self, server_id, command_id):
        row = g.db.query(ServerDaemonCommand).get(command_id)
        ret = row.as_dict()
        ret["url"] = url_for("servers.command", server_id=server_id, command_id=row.command_id,
                             _external=True)
        return ret


api.add_resource(ServersAPI, '/servers', endpoint="list")
api.add_resource(ServerAPI, '/servers/<int:server_id>', endpoint="entry")
api.add_resource(ServerHeartbeatAPI, '/servers/<int:server_id>/heartbeat', endpoint="heartbeat")
api.add_resource(ServerCommandsAPI, '/servers/<int:server_id>/commands', endpoint="commands")
api.add_resource(ServerCommandAPI, '/servers/<int:server_id>/commands/<int:command_id>',
                 endpoint="command")


@register_endpoints
def endpoint_info(*args):
    ret = {"servers": url_for("servers.list", _external=True), }
    return ret
