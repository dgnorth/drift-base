import datetime
import http.client as http_client
import json
from mock import patch

from driftbase.utils.test_utils import BaseCloudkitTest


class ClientsTest(BaseCloudkitTest):
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
        r = self.post(clients_url, data=data, expected_status_code=http_client.CREATED)
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
        r = self.post(clients_uri, data=data, expected_status_code=http_client.CREATED)
        client_uri = r.json()["url"]
        r = self.get(client_uri)
        self.assertEqual(r.json()["num_heartbeats"], 1)
        r = self.put(client_uri)
        self.assertEqual(r.json()["num_heartbeats"], 2)

        with patch("driftbase.api.clients.utcnow") as mock_date:
            mock_date.return_value = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
            r = self.put(client_uri, expected_status_code=http_client.NOT_FOUND)

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
        r = self.post(clients_uri, data=data, expected_status_code=http_client.CREATED)
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
        r = self.post(clients_uri, data=data, expected_status_code=http_client.CREATED)
        # update our authorization to a client session
        jti = r.json()["jti"]
        self.headers["Authorization"] = "JTI %s" % jti

        # We have the latest client session so we have access to the players endpoint
        r = self.get(self.endpoints["players"])

        # Register a new client session but do not update the auth headers
        r = self.post(clients_uri, data=data, expected_status_code=http_client.CREATED)
        new_jti = r.json()["jti"]

        # Our old session no longer has access to the players endpoint
        r = self.get(self.endpoints["players"], expected_status_code=http_client.FORBIDDEN)
        self.assertIn("error", r.json())
        self.assertIn("client_session_terminated", r.json()["error"]["code"])
        self.assertIn("usurped", r.json()["error"]["reason"])

        # Our new session has access to the endpoint
        self.headers["Authorization"] = "JTI %s" % new_jti
        r = self.get(self.endpoints["players"], expected_status_code=http_client.OK)

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
        r = self.post(clients_uri, data=data, expected_status_code=http_client.CREATED)
        client_url = r.json()["url"]

        # update our authorization to a client session
        jti = r.json()["jti"]
        self.headers["Authorization"] = "JTI %s" % jti

        r = self.get("/")
        self.assertEqual(client_url, r.json()["endpoints"]["my_client"])

        self.delete(client_url)
        self.get(client_url, expected_status_code=http_client.NOT_FOUND)

    def test_clients_delete_leave_party(self):
        # Setup party
        g1_name = self.make_player()
        g1_id = self.player_id

        host_name = self.make_player()
        host_id = self.player_id

        # Invite g1 to a new party
        self.post(self.endpoints["party_invites"], data={'player_id': g1_id}, expected_status_code=http_client.CREATED)

        # Accept the g1 invite
        self.auth(g1_name)
        g1_notification, g1_message_number = notification, _ = self.get_player_notification("party_notification",
                                                                                            "invite")
        self.patch(g1_notification['invite_url'], data={'inviter_id': host_id}, expected_status_code=http_client.OK)

        # Assert host in party
        self.auth(host_name)

        self.get(self.endpoints["parties"], expected_status_code=http_client.OK)

        # Setup host client
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
        r = self.post(clients_uri, data=data, expected_status_code=http_client.CREATED)
        client_url = r.json()["url"]

        # update our authorization to a client session
        jti = r.json()["jti"]
        self.headers["Authorization"] = "JTI %s" % jti

        r = self.get("/")
        self.assertEqual(client_url, r.json()["endpoints"]["my_client"])

        # Delete host client
        self.delete(client_url)

        # Assert host no longer in party
        self.get(self.endpoints["parties"], expected_status_code=http_client.NOT_FOUND)
