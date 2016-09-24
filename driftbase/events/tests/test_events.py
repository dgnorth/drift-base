# -*- coding: utf-8 -*-

import os
from os.path import abspath, join
config_file = abspath(join(__file__, "..", "..", "..", "config", "config.json"))
os.environ.setdefault("drift_CONFIG", config_file)

import httplib
import unittest, responses, mock
import json, requests, datetime
from mock import patch
from drift.systesthelper import setup_tenant, remove_tenant, service_username, service_password, local_password, uuid_string, DriftBaseTestCase, big_number


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
