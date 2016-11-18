# -*- coding: utf-8 -*-

import logging
import httplib
from dateutil import parser

from flask import Blueprint, request, url_for
from flask_restful import Api, Resource, abort

from drift.auth.jwtchecker import current_user
from drift.urlregistry import register_endpoints

log = logging.getLogger(__name__)
bp = Blueprint("events", __name__)
api = Api(bp)

clientlogger = logging.getLogger("clientlog")
eventlogger = logging.getLogger("eventlog")


def verify_log_request(request, required_keys=None):
    args = request.json
    if not isinstance(args, list):
        abort(httplib.METHOD_NOT_ALLOWED, message="This endpoint only accepts a list of dicts")
    if not args:
        log.warning("Invalid log request. No loglines.")
        abort(httplib.METHOD_NOT_ALLOWED, message="This endpoint only accepts a list of dicts")
    for event in args:
        if not isinstance(event, dict):
            log.warning("Invalid log request. Entry not dict: %s", event)
            abort(httplib.METHOD_NOT_ALLOWED, message="This endpoint only accepts a list of dicts")
        if required_keys:
            for key in required_keys:
                if key not in event:
                    log.warning("Invalid log request. Missing required key '%s' from %s",
                                key, event)
                    abort(httplib.METHOD_NOT_ALLOWED,
                          message="Required key, '%s' missing from event" % key)
        if "timestamp" in event:
            try:
                parser.parse(event["timestamp"])
            except ValueError:
                log.warning("Invalid log request. Timestamp %s could not be parsed for %s",
                            event["timestamp"], event)
                abort(httplib.METHOD_NOT_ALLOWED, message="Invalid timestamp, '%s' in event '%s'" %
                      (event["timestamp"], event["event_name"]))


class EventsAPI(Resource):

    def post(self):
        """
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

        return "OK", httplib.CREATED


class ClientLogsAPI(Resource):

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
            clientlogger.info("clientlog", extra=event)

        return "OK", httplib.CREATED


api.add_resource(EventsAPI, '/events', endpoint="events")
api.add_resource(ClientLogsAPI, '/clientlogs', endpoint="clientlogs")


@register_endpoints
def endpoint_info(*args):
    return {
        "eventlogs": url_for("events.events", _external=True),
        "clientlogs": url_for("events.clientlogs", _external=True),
    }
