import logging

from six.moves import http_client

from flask import request, url_for
from flask.views import MethodView
import marshmallow as ma
from flask_restplus import reqparse
from flask_rest_api import Blueprint, abort

from drift.core.extensions.urlregistry import Endpoints
from drift.core.extensions.jwt import current_user

from driftbase.utils import verify_log_request

log = logging.getLogger(__name__)
bp = Blueprint("events", __name__, url_prefix="/events", description="Client Logs")
endpoints = Endpoints()

clientlogger = logging.getLogger("clientlog")
eventlogger = logging.getLogger("eventlog")


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


@bp.route('', endpoint='list')
class EventsAPI(MethodView):

    def post(self):
        """
        Create event

        Public endpoint, called from the client and other services to log an
        event into eventlog
        Used to document action flow such as authentication, client exit,
        battle enter, etc.

        Example usage:

        POST http://localhost:10080/events

        [{"event_name": "my_event", "timestamp": "2015-01-01T10:00:00.000Z"}]

        """
        required_keys = ["event_name", "timestamp"]

        verify_log_request(request, required_keys)

        args = request.json

        # The event log API should enforce the player_id to the current player, unless
        # the user has role "service" in which case it should only set the player_id if
        # it's not passed in the event.
        player_id = current_user['player_id']
        is_service = 'service' in current_user['roles']

        for event in args:
            if is_service:
                event.setdefault('player_id', player_id)
            else:
                event['player_id'] = player_id  # Always override!
            eventlogger.info("eventlog", extra=event)

        return "OK", http_client.CREATED


@endpoints.register
def endpoint_info(*args):
    return {
        "eventlogs": url_for("events.list", _external=True),
    }
