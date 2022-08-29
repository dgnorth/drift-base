import datetime
import http.client
import http.client as http_client
import logging
import marshmallow as ma
from dateutil import parser
from flask import url_for, g, jsonify
from flask.views import MethodView
from drift.blueprint import Blueprint, abort
from marshmallow import validate, ValidationError
from marshmallow.decorators import validates_schema

from drift.core.extensions.jwt import requires_roles
from drift.core.extensions.urlregistry import Endpoints
from driftbase.config import get_machine_heartbeat_config
from driftbase.models.db import Machine, MachineEvent

log = logging.getLogger(__name__)

bp = Blueprint("machines", __name__, url_prefix="/machines")
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


def utcnow():
    return datetime.datetime.utcnow()


class MachinesPostRequestSchema(ma.Schema):
    realm = ma.fields.String(required=True)
    instance_name = ma.fields.String(required=True)

    instance_id = ma.fields.String()
    instance_type = ma.fields.String()
    placement = ma.fields.String()
    public_ip = ma.fields.IPv4()
    private_ip = ma.fields.IPv4()
    machine_info = ma.fields.Dict()
    details = ma.fields.Dict()
    group_name = ma.fields.String()


class MachinesPostResponseSchema(ma.Schema):
    machine_id = ma.fields.Integer(required=True)
    url = ma.fields.Url(required=True)
    next_heartbeat_seconds = ma.fields.Number(required=True)
    heartbeat_timeout = ma.fields.Str(required=True)


class MachinePutRequestSchema(ma.Schema):
    machine_info = ma.fields.Dict()
    config = ma.fields.Dict()
    details = ma.fields.Dict()
    status = ma.fields.Dict()
    statistics = ma.fields.Dict()
    group_name = ma.fields.String()
    events = ma.fields.List(ma.fields.Dict())


class MachinePutResponseSchema(ma.Schema):
    last_heartbeat = ma.fields.DateTime(metadata=dict(description="Timestamp of the previous heartbeat"))
    this_heartbeat = ma.fields.DateTime(metadata=dict(description="Timestamp of this heartbeat"))
    next_heartbeat = ma.fields.DateTime(metadata=dict(description="Timestamp when the next heartbeat is expected"))
    next_heartbeat_seconds = ma.fields.Integer(
        metadata=dict(description="Number of seconds until the next heartbeat is expected"))
    heartbeat_timeout = ma.fields.DateTime(
        metadata=dict(description="Timestamp when the machine times out if no heartbeat is received"))
    heartbeat_timeout_seconds = ma.fields.Integer(
        metadata=dict(description="Number of seconds until the machine times out if no heartbeat is received"))


class MachinesGetQuerySchema(ma.Schema):
    realm = ma.fields.String(required=True,
                             validate=validate.OneOf(['aws', 'local']),
                             metadata=dict(description="Realm, [aws, local]"))
    instance_name = ma.fields.String(required=True, metadata=dict(description="Computer name"))
    instance_id = ma.fields.String()
    instance_type = ma.fields.String()
    placement = ma.fields.String()
    public_ip = ma.fields.String()
    rows = ma.fields.Integer()

    @validates_schema
    def validate_required_fields(self, data, **kwargs):
        if data.get("realm") == "aws":
            missing = []
            for param in ("instance_id", "instance_type", "placement", "public_ip"):
                if not data.get(param):
                    missing.append(param)
            if missing:
                raise ValidationError(f"Missing required parameter(s) for realm 'aws': [{', '.join(missing)}]")


@bp.route('', endpoint='list')
class MachinesAPI(MethodView):
    """The interface to battle server machines. Each physical machine
    (for example ec2 instance) has a machine resource here. Each
    machine resource has zero or more battle server resources.
    A machine is defined as a set of the parameters for the post call below.
    If an instance gets a new publicIP address for example, it will
    get a new machine resource.
    """

    @requires_roles("service")
    # @namespace.expect(get_args)
    @bp.arguments(MachinesGetQuerySchema, location='query', error_status_code=http.client.BAD_REQUEST)
    def get(self, args):
        """
        Get a list of machines
        """
        num_rows = args.get("rows") or 100
        query = g.db.query(Machine)

        if args["realm"] == "local":
            query = query.filter(Machine.realm == "local",
                                 Machine.instance_name == args["instance_name"])
        else:
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
            record["url"] = url_for("machines.entry", machine_id=row.machine_id, _external=True)
            ret.append(record)

        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(MachinesPostRequestSchema)
    @bp.response(http_client.CREATED, MachinesPostResponseSchema)
    def post(self, args):
        """
        Register a machine
        """
        log.info("registering a battle server machine for realm %s from ip %s",
                 args.get("realm"), args.get("public_ip"))

        def get_or_null(ip):
            return ip and str(ip) or None

        machine = Machine(realm=args.get("realm"),
                          instance_id=args.get("instance_id"),
                          instance_type=args.get("instance_type"),
                          instance_name=args.get("instance_name"),
                          placement=args.get("placement"),
                          public_ip=get_or_null(args.get("public_ip")),
                          private_ip=get_or_null(args.get("private_ip")),
                          machine_info=args.get("machine_info"),
                          details=args.get("details"),
                          group_name=args.get("group_name")
                          )
        g.db.add(machine)
        g.db.commit()
        machine_id = machine.machine_id
        resource_uri = url_for("machines.entry", machine_id=machine_id, _external=True)
        response_header = {
            "Location": resource_uri,
        }
        log.info("Battle server machine %s has been registered on public ip %s",
                 machine_id, args.get("public_ip"))

        heartbeat_period, heartbeat_timeout = get_machine_heartbeat_config()
        return {"machine_id": machine_id,
                "url": resource_uri,
                "next_heartbeat_seconds": heartbeat_period,
                "heartbeat_timeout": utcnow() + datetime.timedelta(seconds=heartbeat_timeout),
                }, None, response_header


@bp.route('/<int:machine_id>', endpoint='entry')
class MachineAPI(MethodView):
    """
    Information about specific machines
    """

    @requires_roles("service")
    def get(self, machine_id):
        """
        Find machine by ID

        Get information about a single battle server machine.
        Just dumps out the DB row as json
        """
        row = g.db.query(Machine).get(machine_id)
        if not row:
            log.warning("Requested a non-existant machine: %s", machine_id)
            abort(http_client.NOT_FOUND, description="Machine not found")
        record = row.as_dict()
        record["url"] = url_for("machines.entry", machine_id=machine_id, _external=True)
        record["servers_url"] = url_for("servers.list", machine_id=machine_id, _external=True)
        record["matches_url"] = url_for("matches.list", machine_id=machine_id, _external=True)

        log.debug("Returning info for battle server machine %s", machine_id)

        return jsonify(record)

    @requires_roles("service")
    @bp.arguments(MachinePutRequestSchema)
    @bp.response(http_client.OK, MachinePutResponseSchema)
    def put(self, args, machine_id):
        """
        Update machine

        Heartbeat and update the machine reference
        """
        row = g.db.query(Machine).get(machine_id)
        if not row:
            abort(http_client.NOT_FOUND, description="Machine not found")

        now = utcnow()
        heartbeat_period, heartbeat_timeout = get_machine_heartbeat_config()
        last_heartbeat = row.heartbeat_date
        if last_heartbeat + datetime.timedelta(seconds=heartbeat_timeout) < now:
            msg = "Heartbeat timeout. Last heartbeat was at {} and now we are at {}" \
                .format(last_heartbeat, now)
            log.info(msg)
            abort(http_client.NOT_FOUND, message=msg)

        row.heartbeat_date = now
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
        return {
            "last_heartbeat": last_heartbeat,
            "this_heartbeat": row.heartbeat_date,
            "next_heartbeat": row.heartbeat_date + datetime.timedelta(seconds=heartbeat_period),
            "next_heartbeat_seconds": heartbeat_period,
            "heartbeat_timeout": now + datetime.timedelta(seconds=heartbeat_timeout),
            "heartbeat_timeout_seconds": heartbeat_timeout,
        }


@endpoints.register
def endpoint_info(*args):
    ret = {"machines": url_for("machines.list", _external=True)}
    return ret
