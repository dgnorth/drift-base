"""
    These are endpoints for battleserver run configurations
    Note: This is still not used and is work in progress
"""

import http.client as http_client
import logging
import marshmallow as ma
from flask import url_for, g, jsonify
from flask.views import MethodView
from drift.blueprint import Blueprint, abort

from drift.core.extensions.jwt import requires_roles
from drift.core.extensions.urlregistry import Endpoints
from driftbase.models.db import RunConfig

log = logging.getLogger(__name__)

bp = Blueprint("runconfigs", __name__, url_prefix="/runconfigs")
endpoints = Endpoints()


def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)
    endpoints.init_app(app)


class RunConfigsPostSchema(ma.Schema):
    name = ma.fields.String(required=True)
    repository = ma.fields.String(required=True)
    ref = ma.fields.String(required=True)
    build = ma.fields.String(required=True)
    num_processes = ma.fields.Integer()
    command_line = ma.fields.String()
    details = ma.fields.Dict()


class RunConfigsGetQuerySchema(ma.Schema):
    name = ma.fields.String()
    rows = ma.fields.Integer()


@bp.route('', endpoint='list')
class RunConfigsAPI(MethodView):

    @requires_roles("service")
    @bp.arguments(RunConfigsGetQuerySchema, location='query')
    def get(self, args):
        num_rows = args.get("rows") or 100
        query = g.db.query(RunConfig)
        if args.get("name"):
            query = query.filter(RunConfig.name == args["name"])
        query = query.order_by(-RunConfig.runconfig_id)
        query = query.limit(num_rows)
        rows = query.all()
        ret = []
        for row in rows:
            record = row.as_dict()
            record["url"] = url_for("runconfig.entry", runconfig_id=row.runconfig_id,
                                    _external=True)
            ret.append(record)

        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(RunConfigsPostSchema)
    def post(self, args):
        log.info("creating a new runconfig")

        rows = g.db.query(RunConfig).filter(RunConfig.name.ilike(args["name"])).all()
        if rows:
            abort(http_client.BAD_REQUEST, message="Run Config '%s' already exists" % args["name"])

        runconfig = RunConfig(name=args.get("name"),
                              repository=args.get("repository"),
                              ref=args.get("ref"),
                              build=args.get("build"),
                              num_processes=args.get("num_processes"),
                              command_line=args.get("command_line"),
                              details=args.get("details"),
                              )
        g.db.add(runconfig)
        g.db.commit()
        runconfig_id = runconfig.runconfig_id
        resource_uri = url_for("runconfigs.entry", runconfig_id=runconfig_id, _external=True)
        response_header = {
            "Location": resource_uri,
        }
        log.info("Run Configuration %s has been registered with name '%s'",
                 runconfig_id, args.get("name"))

        return jsonify({"runconfig_id": runconfig_id,
                        "url": resource_uri
                        }), http_client.CREATED, response_header


@bp.route('/<int:runconfig_id>', endpoint='entry')
class RunConfigAPI(MethodView):
    """
    Information about specific machines
    """

    @requires_roles("service")
    def get(self, runconfig_id):
        """
        Get information about a single battle server machine.
        Just dumps out the DB row as json
        """
        row = g.db.query(RunConfig).get(runconfig_id)
        if not row:
            log.warning("Requested a non-existant run config: %s", runconfig_id)
            abort(http_client.NOT_FOUND, description="Run Config not found")
        record = row.as_dict()
        record["url"] = url_for("runconfigs.entry", runconfig_id=runconfig_id, _external=True)

        log.info("Returning info for run config %s", runconfig_id)

        return jsonify(record)


@endpoints.register
def endpoint_info(*args):
    ret = {"runconfigs": url_for("runconfigs.list", _external=True)}
    return ret
