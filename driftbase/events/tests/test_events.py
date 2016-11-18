# -*- coding: utf-8 -*-

import os
from os.path import abspath, join
config_file = abspath(join(__file__, "..", "..", "..", "config", "config.json"))
os.environ.setdefault("drift_CONFIG", config_file)

import httplib
import unittest, responses, mock
import json, requests, datetime
from drift.systesthelper import setup_tenant, remove_tenant, DriftBaseTestCase, user_payload
from drift.auth.jwtchecker import current_user


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


class EventsTest(DriftBaseTestCase):
    """
    Tests for the /events and /clientlogs endpoint
    """
    def test_events(self):
        self.auth()
        self.assertIn("eventlogs", self.endpoints)
        endpoint = self.endpoints["eventlogs"]
        self.post(endpoint, expected_status_code=httplib.METHOD_NOT_ALLOWED)
        self.post(endpoint, data=[], expected_status_code=httplib.METHOD_NOT_ALLOWED)
        self.post(endpoint, data=["test"], expected_status_code=httplib.METHOD_NOT_ALLOWED)

        r = self.post(endpoint, data=[{"hello": "world"}],
                      expected_status_code=httplib.METHOD_NOT_ALLOWED)
        self.assertIn("'event_name'", r.json()["error"]["description"])

        r = self.post(endpoint, data=[{"hello": "world", "event_name": "dummy"}],
                      expected_status_code=httplib.METHOD_NOT_ALLOWED)
        self.assertIn("'timestamp'", r.json()["error"]["description"])

        r = self.post(endpoint, data=[{"hello": "world", "event_name": "dummy",
                                       "timestamp": "dummy"}],
                      expected_status_code=httplib.METHOD_NOT_ALLOWED)
        self.assertIn("Invalid timestamp", r.json()["error"]["description"])

        ts = datetime.datetime.utcnow().isoformat() + "Z"
        r = self.post(endpoint, data=[{"hello": "world", "event_name": "dummy", "timestamp": ts}],
                      expected_status_code=httplib.CREATED)

        # only authenticated users can access this endpoint
        self.headers = {}
        r = self.post(endpoint, data=[{"hello": "world", "event_name": "dummy", "timestamp": ts}],
                      expected_status_code=httplib.UNAUTHORIZED)
    
    def test_events_from_server(self):
        # The event log API should enforce the player_id to the current player, unless 
        # the user has role "service" in which case it should only set the player_id if 
        # it's not passed in the event.

        def eventlog(message, extra):
            expect_player_id = self.expect_player_id or current_user['player_id']
            self.assertEqual(extra['player_id'], expect_player_id)

        with mock.patch('driftbase.events.handlers.eventlogger.info', eventlog):
            self.auth()
            endpoint = self.endpoints["eventlogs"]
            ts = datetime.datetime.utcnow().isoformat() + "Z"
            event = {"event_name": "dummy", "timestamp": ts}

            # Ommitting player_id, it should be pulled from current_user
            self.expect_player_id = None  # Expect value from current_user
            self.post(endpoint, data=[event], expected_status_code=httplib.CREATED)
            
            # Set player_id to 88888, but it should be ignored as we don't have role 'service'.
            event['player_id'] = 88888
            self.expect_player_id = None  # Expect value from current_user
            self.post(endpoint, data=[event], expected_status_code=httplib.CREATED)

            # Set player_id to 88888 and runs with role 'service'.
            self.auth_service()
            event['player_id'] = 88888
            self.expect_player_id = 88888
            self.post(endpoint, data=[event], expected_status_code=httplib.CREATED)

    def test_clientlogs(self):
        self.auth()
        self.assertIn("clientlogs", self.endpoints)
        endpoint = self.endpoints["clientlogs"]
        self.post(endpoint, expected_status_code=httplib.METHOD_NOT_ALLOWED)
        self.post(endpoint, data=[], expected_status_code=httplib.METHOD_NOT_ALLOWED)
        self.post(endpoint, data=["test"], expected_status_code=httplib.METHOD_NOT_ALLOWED)

        self.post(endpoint, data=[{"hello": "world"}], expected_status_code=httplib.CREATED)

        # if we do pass an auth header field it must be valid...
        self.headers["Authorization"] = self.headers["Authorization"] + "_"
        self.post(endpoint, data=[{"hello": "world"}], expected_status_code=httplib.UNAUTHORIZED)

        # but the auth field isn't required
        del self.headers["Authorization"]
        self.post(endpoint, data=[{"hello": "world"}], expected_status_code=httplib.CREATED)


if __name__ == '__main__':
    unittest.main()
