import logging

from six.moves import http_client

from flask import request, url_for, jsonify
from flask.views import MethodView
import marshmallow as ma
from flask_restx import reqparse
from flask_smorest import Blueprint

from drift.core.extensions.urlregistry import Endpoints
from drift.core.extensions.jwt import current_user

from driftbase.utils import verify_log_request

log = logging.getLogger(__name__)
bp = Blueprint(
    "clientlogs", __name__, url_prefix="/clientlogs", description="Client Logs"
)
endpoints = Endpoints()

clientlogger = logging.getLogger("clientlog")
eventlogger = logging.getLogger("eventlog")


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


@bp.route("/", endpoint="logs")
class ClientLogsAPI(MethodView):

    no_jwt_check = ["POST"]

    def post(self):
        """
        Public endpoint, called from the client for debug logging

        Example usage:

        POST http://localhost:10080/clientlogs

        [
            {"category": "BuildingDatabase",
             "message": "Missing building data",
             "level": "Error",
             "timestamp": "2015-01-01T10:00:00.000Z"
            }
        ]

        """
        verify_log_request(request)
        args = request.json
        if not isinstance(args, list):
            args = [args]
        player_id = current_user["player_id"] if current_user else None

        for event in args:
            event["player_id"] = player_id
            clientlogger.info("clientlog", extra={"extra": event})

        if request.headers.get("Accept") == "application/json":
            return jsonify(status="OK"), http_client.CREATED
        else:
            return "OK", http_client.CREATED


@endpoints.register
def endpoint_info(*args):
    return {"clientlogs": url_for("clientlogs.logs", _external=True)}
