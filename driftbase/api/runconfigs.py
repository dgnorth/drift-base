"""
    These are endpoints for battleserver run configurations
    Note: This is still not used and is work in progress
"""

import logging

from six.moves import http_client

from flask import request, url_for, g
from flask.views import MethodView
import marshmallow as ma
from flask_restplus import reqparse
from flask_rest_api import Api, Blueprint
from drift.core.extensions.urlregistry import Endpoints

from drift.core.extensions.schemachecker import simple_schema_request
from drift.core.extensions.jwt import requires_roles

from driftbase.models.db import RunConfig

log = logging.getLogger(__name__)

bp = Blueprint("runconfigs", "runconfigs", url_prefix="/runconfigs", description="Battleserver run configuration")
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


@bp.route('', endpoint='runconfigs')
class RunConfigsAPI(MethodView):
    get_args = reqparse.RequestParser()
    get_args.add_argument("name", type=str)
    get_args.add_argument("rows", type=int, required=False)

    @requires_roles("service")
    def get(self):
        args = self.get_args.parse_args()
        num_rows = args.get("rows") or 100
        query = g.db.query(RunConfig)
        if args["name"]:
            query = query.filter(RunConfig.name == args["name"])
        query = query.order_by(-RunConfig.runconfig_id)
        query = query.limit(num_rows)
        rows = query.all()
        ret = []
        for row in rows:
            record = row.as_dict()
            record["url"] = url_for("runconfig", runconfig_id=row.runconfig_id,
                                    _external=True)
            ret.append(record)

        return ret

    @requires_roles("service")
    @simple_schema_request({
        "name": {"type": "string", },
        "repository": {"type": "string", },
        "ref": {"type": "string", },
        "build": {"type": "string", },
        "num_processes": {"type": "number", },
        "command_line": {"type": "string", },
        "details": {"type": "object", },
    }, required=["name", "repository", "ref", "build"])
    def post(self):
        args = request.json
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
        resource_uri = url_for("runconfig", runconfig_id=runconfig_id, _external=True)
        response_header = {
            "Location": resource_uri,
        }
        log.info("Run Configuration %s has been registered with name '%s'",
                 runconfig_id, args.get("name"))

        return {"runconfig_id": runconfig_id,
                "url": resource_uri
                }, http_client.CREATED, response_header


@bp.route('/<int:runconfig_id>', endpoint='runconfig')
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
        record["url"] = url_for("runconfig", runconfig_id=runconfig_id, _external=True)

        log.info("Returning info for run config %s", runconfig_id)

        return record


@endpoints.register
def endpoint_info(*args):
    ret = {"runconfigs": url_for("runconfigs", _external=True)}
    return ret
