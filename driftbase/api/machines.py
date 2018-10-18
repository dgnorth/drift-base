# -*- coding: utf-8 -*-

import logging
import datetime

from six.moves import http_client

from flask import Blueprint, request, url_for, g
from flask_restplus import Namespace, Resource, reqparse, abort
from drift.core.extensions.urlregistry import Endpoints
from dateutil import parser

from drift.core.extensions.schemachecker import simple_schema_request
from drift.core.extensions.jwt import requires_roles

from driftbase.models.db import Machine, MachineEvent

log = logging.getLogger(__name__)


namespace = Namespace("machines", "Battleserver machine instances")
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.add_namespace(namespace)
    endpoints.init_app(app)


def utcnow():
    return datetime.datetime.utcnow()


@namespace.route('/', endpoint='machines')
class MachinesAPI(Resource):
    """The interface to battleserver machines. Each physical machine
    (for example ec2 instance) has a machine resource here. Each
    machine resource has zero or more battleserver resources.
    A machine is defined as a set of the parameters for the post call below.
    If an instance gets a new publicIP address for example, it will
    get a new machine resource.
    """
    get_args = reqparse.RequestParser()
    get_args.add_argument("realm", type=str, help="Missing realm. Should be one of: aws, local",
                          required=True)
    get_args.add_argument("instance_name", help="Missing instance_name. Should be computer name",
                          type=str, required=True)

    get_args.add_argument("instance_id", type=str, required=False)
    get_args.add_argument("instance_type", type=str, required=False)
    get_args.add_argument("placement", type=str, required=False)
    get_args.add_argument("public_ip", type=str, required=False)
    get_args.add_argument("rows", type=int, required=False)

    @requires_roles("service")
    @namespace.expect(get_args)
    def get(self):
        args = self.get_args.parse_args()
        num_rows = args.get("rows") or 100
        query = g.db.query(Machine)
        if args.get("realm", None) not in ("aws", "local"):
            abort(http_client.BAD_REQUEST, description="realm must be 'aws' or 'local'")

        if args["realm"] == "local":
            query = query.filter(Machine.realm == "local",
                                 Machine.instance_name == args["instance_name"])
        else:
            missing = []
            for param in ("instance_id", "instance_type", "placement", "public_ip"):
                if not args[param]:
                    missing.append(param)
            if missing:
                abort(http_client.BAD_REQUEST,
                      description="missing required parameters: %s" % ", ".join(missing))
            query = query.filter(Machine.realm == args["realm"],
                                 Machine.instance_name == args["instance_name"],
                                 Machine.instance_id == args["instance_id"],
                                 Machine.instance_type == args["instance_type"],
                                 Machine.placement == args["placement"],
                                 Machine.public_ip == args["public_ip"],
                                 )
            query = query.order_by(-Machine.machine_id)
        query = query.limit(num_rows)
        rows = query.all()
        ret = []
        for row in rows:
            record = row.as_dict()
            record["url"] = url_for("machines", machine_id=row.machine_id, _external=True)
            ret.append(record)

        return ret

    @requires_roles("service")
    @simple_schema_request({
        "realm": {"type": "string", },
        "instance_id": {"type": "string", },
        "instance_type": {"type": "string", },
        "instance_name": {"type": "string", },
        "placement": {"type": "string", },
        "public_ip": {"format": "ip-address", },
        "private_ip": {"format": "ip-address", },
        "machine_info": {"type": "object", },
        "details": {"type": "object", },
        "group_name": {"type": "string", },
    }, required=["realm", "instance_name"])
    def post(self):
        args = request.json
        log.info("registering a battleserver machine for realm %s from ip %s",
                 args.get("realm"), args.get("public_ip"))

        machine = Machine(realm=args.get("realm"),
                          instance_id=args.get("instance_id"),
                          instance_type=args.get("instance_type"),
                          instance_name=args.get("instance_name"),
                          placement=args.get("placement"),
                          public_ip=args.get("public_ip"),
                          private_ip=args.get("private_ip"),
                          machine_info=args.get("machine_info"),
                          details=args.get("details"),
                          group_name=args.get("group_name")
                          )
        g.db.add(machine)
        g.db.commit()
        machine_id = machine.machine_id
        resource_uri = url_for("machine", machine_id=machine_id, _external=True)
        response_header = {
            "Location": resource_uri,
        }
        log.info("Battleserver machine %s has been registered on public ip %s",
                 machine_id, args.get("public_ip"))

        return {"machine_id": machine_id,
                "url": resource_uri
                }, http_client.CREATED, response_header


@namespace.route('/<int:machine_id>', endpoint='machine')
class MachineAPI(Resource):
    """
    Information about specific machines
    """
    @requires_roles("service")
    def get(self, machine_id):
        """
        Get information about a single battle server machine.
        Just dumps out the DB row as json
        """
        row = g.db.query(Machine).get(machine_id)
        if not row:
            log.warning("Requested a non-existant machine: %s", machine_id)
            abort(http_client.NOT_FOUND, description="Machine not found")
        record = row.as_dict()
        record["url"] = url_for("machine", machine_id=machine_id, _external=True)
        record["servers_url"] = url_for("servers", machine_id=machine_id, _external=True)
        record["matches_url"] = url_for("matches", machine_id=machine_id, _external=True)

        log.debug("Returning info for battleserver machine %s", machine_id)

        return record

    @requires_roles("service")
    @simple_schema_request({
        "machine_info": {"type": "object", },
        "status": {"type": "object", },
        "details": {"type": "object", },
        "config": {"type": "object", },
        "statistics": {"type": "object", },
        "group_name" : {"type": "string"},
        "events": {"type": "array"}
    }, required=[])
    def put(self, machine_id):
        """
        Heartbeat and update the machine reference
        """
        args = request.json
        row = g.db.query(Machine).get(machine_id)
        if not row:
            abort(http_client.NOT_FOUND, description="Machine not found")
        last_heartbeat = row.heartbeat_date
        row.heartbeat_date = utcnow()
        if args.get("status"):
            row.status = args["status"]
        if args.get("details"):
            row.details = args["details"]
        if args.get("config"):
            row.config = args["config"]
        if args.get("statistics"):
            row.statistics = args["statistics"]
        if args.get("group_name"):
            row.group_name = args["group_name"]
        if args.get("events"):
            for event in args["events"]:
                timestamp = parser.parse(event["timestamp"])
                event_row = MachineEvent(event_type_name=event["event"],
                                         machine_id=machine_id,
                                         details=event,
                                         create_date=timestamp)
                g.db.add(event_row)

        g.db.commit()
        return {"last_heartbeat": last_heartbeat}


@endpoints.register
def endpoint_info(*args):
    ret = {"machines": url_for("machines", _external=True)}
    return ret
