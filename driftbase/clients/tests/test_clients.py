# -*- coding: utf-8 -*-

import os
from os.path import abspath, join
config_file = abspath(join(__file__, "..", "..", "..", "config", "config.json"))
os.environ.setdefault("drift_CONFIG", config_file)

import httplib
import unittest, responses, mock
import json, requests, httplib
import datetime
from mock import patch
from drift.systesthelper import setup_tenant, remove_tenant, service_username, service_password, local_password, uuid_string, DriftBaseTestCase


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


class ClientsTest(DriftBaseTestCase):
    """
    Tests for the /clients endpoint
    """
    def test_clients(self):
        self.auth()
        clients_url = self.endpoints["clients"]
        resp = self.get(clients_url)
        self.assertTrue(isinstance(resp.json(), list))

        r = self.get(self.endpoints["my_user"])
        self.assertEqual(r.json()["client_id"], None)

        data = {
            "client_type": "client_type",
            "build": "build",
            "platform_type": "platform_type",
            "app_guid": "app_guid",
            "version": "version"
        }
        r = self.post(clients_url, data=data, expected_status_code=httplib.CREATED)
        client_id = r.json()["client_id"]
        self.headers["Authorization"] = "JTI %s" % r.json()["jti"]

        r = self.get(self.endpoints["my_user"])
        self.assertEqual(r.json()["client_id"], client_id)

        r = self.get("/")
        self.assertIsNotNone(r.json()["endpoints"]["my_client"])

    def test_heartbeat(self):
        self.auth()
        clients_uri = self.endpoints["clients"]
        data = {
            "client_type": "client_type",
            "build": "build",
            "platform_type": "platform_type",
            "app_guid": "app_guid",
            "version": "version"

        }
        r = self.post(clients_uri, data=data, expected_status_code=httplib.CREATED)
        client_uri = r.json()["url"]
        r = self.get(client_uri)
        self.assertEqual(r.json()["num_heartbeats"], 1)
        r = self.put(client_uri)
        self.assertEqual(r.json()["num_heartbeats"], 2)

        with patch("driftbase.clients.handlers.utcnow") as mock_date:
            mock_date.return_value = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
            r = self.put(client_uri, expected_status_code=httplib.NOT_FOUND)

    def test_platform(self):
        self.auth()
        clients_uri = self.endpoints["clients"]
        platform_info = {"memory": "stuff", "video_card": "stuffz"}
        platform_version = "1.20.22"
        data = {
            "client_type": "client_type",
            "build": "build",
            "platform_type": "platform_type",
            "app_guid": "app_guid",
            "version": "version",
            "platform_version": platform_version,
            "platform_info": platform_info,
        }
        r = self.post(clients_uri, data=data, expected_status_code=httplib.CREATED)
        client_url = r.json()["url"]
        r = self.get(client_url)
        self.assertEqual(r.json()["platform_info"]["memory"], "stuff")
        self.assertEqual(r.json()["platform_version"], platform_version)

    def test_clients_usurp(self):
        self.auth()
        clients_uri = self.endpoints["clients"]
        platform_info = {"memory": "stuff", "video_card": "stuffz"}
        platform_version = "1.20.22"
        data = {
            "client_type": "client_type",
            "build": "build",
            "platform_type": "platform_type",
            "app_guid": "app_guid",
            "version": "version",
            "platform_version": platform_version,
            "platform_info": json.dumps(platform_info),
        }
        r = self.post(clients_uri, data=data, expected_status_code=httplib.CREATED)
        # update our authorization to a client session
        jti = r.json()["jti"]
        self.headers["Authorization"] = "JTI %s" % jti

        # We have the latest client session so we have access to the players endpoint
        r = self.get(self.endpoints["players"])

        # Register a new client session but do not update the auth headers
        r = self.post(clients_uri, data=data, expected_status_code=httplib.CREATED)
        new_jti = r.json()["jti"]

        # Our old session no longer has access to the players endpoint
        r = self.get(self.endpoints["players"], expected_status_code=httplib.FORBIDDEN)
        self.assertIn("error", r.json())
        self.assertIn("client_session_terminated", r.json()["error"]["code"])
        self.assertIn("usurped", r.json()["error"]["reason"])

        # Our new session has access to the endpoint
        self.headers["Authorization"] = "JTI %s" % new_jti
        r = self.get(self.endpoints["players"], expected_status_code=httplib.OK)

    def test_clients_delete(self):
        self.auth()
        clients_uri = self.endpoints["clients"]
        platform_info = {"memory": "stuff", "video_card": "stuffz"}
        platform_version = "1.20.22"
        data = {
            "client_type": "client_type",
            "build": "build",
            "platform_type": "platform_type",
            "app_guid": "app_guid",
            "version": "version",
            "platform_version": platform_version,
            "platform_info": json.dumps(platform_info),
        }
        r = self.post(clients_uri, data=data, expected_status_code=httplib.CREATED)
        client_url = r.json()["url"]

        # update our authorization to a client session
        jti = r.json()["jti"]
        self.headers["Authorization"] = "JTI %s" % jti

        r = self.get("/")
        self.assertEquals(client_url, r.json()["endpoints"]["my_client"])

        self.delete(client_url)
        self.get(client_url, expected_status_code=httplib.NOT_FOUND)


if __name__ == '__main__':
    unittest.main()
