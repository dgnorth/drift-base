"""
    These are endpoints for battleserver run configurations
"""

import http.client as http_client
import logging
import marshmallow as ma
from flask import url_for, g, jsonify
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from drift.core.extensions.jwt import requires_roles
from drift.core.extensions.urlregistry import Endpoints
from driftbase.models.db import MachineGroup

log = logging.getLogger(__name__)

bp = Blueprint("machinegroups", __name__, url_prefix="/machinegroups",
               description="Battleserver machine instance groups")
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


class MachineGroupsPostRequestArgs(ma.Schema):
    name = ma.fields.Str(required=True)
    description = ma.fields.Str()
    runconfig_id = ma.fields.Integer()


class MachineGroupsPatchRequestArgs(ma.Schema):
    name = ma.fields.Str()
    description = ma.fields.Str()
    runconfig_id = ma.fields.Integer()


class MachineGroupsGetQuerySchema(ma.Schema):
    name = ma.fields.String()
    rows = ma.fields.Integer()


@bp.route('/', endpoint='list')
class MachineGroupsAPI(MethodView):

    @bp.arguments(MachineGroupsGetQuerySchema, location='query')
    @requires_roles("service")
    def get(self, args):
        """
        Get a list of machine groups
        """
        num_rows = args.get("rows") or 100
        query = g.db.query(MachineGroup)
        if args.get("name"):
            query = query.filter(MachineGroup.name == args["name"])
        query = query.order_by(-MachineGroup.machinegroup_id)
        query = query.limit(num_rows)
        rows = query.all()
        ret = []
        for row in rows:
            record = row.as_dict()
            record["url"] = url_for("machinegroups.entry",
                                    machinegroup_id=row.machinegroup_id, _external=True)
            ret.append(record)

        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(MachineGroupsPostRequestArgs)
    def post(self, args):
        """
        Create machine group
        """
        log.info("creating a new machine group")

        machinegroup = MachineGroup(name=args.get("name"),
                                    description=args.get("description"),
                                    runconfig_id=args.get("runconfig_id"),
                                    )
        g.db.add(machinegroup)
        g.db.commit()
        machinegroup_id = machinegroup.machinegroup_id
        resource_uri = url_for("machinegroups.entry", machinegroup_id=machinegroup_id,
                               _external=True)
        response_header = {
            "Location": resource_uri,
        }
        log.info("Machine Group %s has been created with name '%s'",
                 machinegroup_id, args.get("name"))

        return jsonify({"machinegroup_id": machinegroup_id,
                        "url": resource_uri
                        }), http_client.CREATED, response_header


@bp.route('/<int:machinegroup_id>', endpoint='entry')
class MachineGroupAPI(MethodView):
    """
    Information about specific machines
    """

    @requires_roles("service")
    def get(self, machinegroup_id):
        """
        Find machine group by ID

        Get information about a single battle server machine.
        Just dumps out the DB row as json
        """
        row = g.db.query(MachineGroup).get(machinegroup_id)
        if not row:
            log.warning("Requested a non-existant machine group %s", machinegroup_id)
            abort(http_client.NOT_FOUND, description="Machine Group not found")
        record = row.as_dict()
        record["url"] = url_for("machinegroups.entry", machinegroup_id=machinegroup_id,
                                _external=True)

        log.info("Returning info for run config %s", machinegroup_id)

        return jsonify(record)

    @requires_roles("service")
    @bp.arguments(MachineGroupsPatchRequestArgs)
    def patch(self, args, machinegroup_id):
        """
        Update machine group
        """
        machinegroup = g.db.query(MachineGroup).get(machinegroup_id)
        if args.get("name"):
            machinegroup.name = args["name"]
        if args.get("description"):
            machinegroup.description = args["description"]
        if args.get("runconfig_id"):
            machinegroup.runconfig_id = args["runconfig_id"]
        g.db.commit()
        return "OK"


@endpoints.register
def endpoint_info(*args):
    ret = {
        "machinegroups": url_for("machinegroups.list", _external=True),
    }
    return ret
