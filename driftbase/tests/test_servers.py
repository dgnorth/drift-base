import copy
import datetime
from unittest.mock import patch

from drift.systesthelper import DriftBaseTestCase
from six.moves import http_client

from driftbase.api.servers import ServersPostResponseSchema, ServerPutResponseSchema, ServerHeartbeatPutResponseSchema


class ServersTest(DriftBaseTestCase):
    """
    Tests for the /servers service endpoints
    """

    def test_access(self):
        self.auth()
        resp = self.get("/servers", expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

        resp = self.get("/servers/1", expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

        resp = self.post("/servers", expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

        resp = self.put("/servers/1", expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

    def test_get_list_basic(self):
        self.auth_service()
        resp = self.get("/servers")
        self.assertTrue(isinstance(resp.json(), list))
        resp = self.get("/servers?machine_id=1")
        self.assertTrue(isinstance(resp.json(), list))

        resp = self.get("/servers/999999", expected_status_code=http_client.NOT_FOUND)
        resp = self.put("/servers/999999", data={"status": "bla"},
                        expected_status_code=http_client.NOT_FOUND)

    def test_create_server_local(self):
        """Create a server instance without already having a machine_id.
        This is a scenario for local servers without a daemon running.
        """
        self.auth_service()
        resp = self.post("/servers", data={"status": "active"},
                         expected_status_code=http_client.BAD_REQUEST)
        self.assertIn("instance_name", resp.json()["error"]["description"])

        instance_name = "matti@borko"
        placement = "LAN 10.2"

        resp = self.post("/servers", data={"status": "active",
                                           "instance_name": instance_name,
                                           "placement": placement},
                         expected_status_code=http_client.CREATED)
        self.assertDictEqual(ServersPostResponseSchema().validate(resp.json()), {})
        url = resp.json()["url"]
        resp = self.get(url)
        machine_id = resp.json()["machine_id"]
        self.assertTrue(resp.json()["server_id"] >= 100000001)
        self.assertTrue(resp.json()["server_id"] < 200000000)
        self.assertTrue(resp.json()["machine_id"] >= 200000001)

        resp = self.get(resp.json()["machine_url"])
        self.assertEqual(resp.json()["realm"], "local")
        self.assertEqual(resp.json()["instance_name"], instance_name)
        self.assertEqual(resp.json()["placement"], placement)

        # create another server and ensure it ends up on the same machine
        resp = self.post("/servers", data={"status": "active",
                                           "instance_name": instance_name,
                                           "placement": placement},
                         expected_status_code=http_client.CREATED)
        url = resp.json()["url"]
        resp = self.get(url)
        self.assertEqual(resp.json()["machine_id"], machine_id)

    def _create_machine(self):
        data = {"realm": "aws",
                "instance_name": "awsinstance",
                "placement": "placement",
                "instance_type": "instance_type",
                "instance_id": "instance_id",
                "public_ip": "8.8.8.8",
                }
        resp = self.post("/machines", data=data, expected_status_code=http_client.CREATED)
        return resp.json()

    def _get_server_data(self, machine_id):
        data = {"machine_id": machine_id,
                "version": "version",
                "public_ip": "8.8.8.8",
                "port": 50000,
                "command_line": "command_line",
                "command_line_custom": "command_line_custom",
                "pid": 666,
                "status": "active",
                "image_name": "image_name",
                "branch": "develop",
                "commit_id": "commit_id",
                "version": "version",
                "process_info": {"process_info": "yes"},
                "details": {"details": "yes"},
                }
        return data

    def test_create_server_aws(self):
        """Create a server instance by first creating a machine
        This is a scenario for cloud instances where the daemon creates a machine resource
        """
        self.auth_service()
        js = self._create_machine()
        machine_url = js["url"]
        machine_id = js["machine_id"]

        data = self._get_server_data(machine_id)

        resp = self.post("/servers", data=data, expected_status_code=http_client.CREATED)
        self.assertDictEqual(ServersPostResponseSchema().validate(resp.json()), {})
        server_id = resp.json()["server_id"]
        self.assertEqual(machine_id, resp.json()["machine_id"])
        self.assertEqual(machine_url, resp.json()["machine_url"])

        # the new server should get returned
        resp = self.get("/servers?machine_id=%s" % machine_id)
        self.assertTrue(len(resp.json()) >= 1)
        self.assertIn(server_id, [s["server_id"] for s in resp.json()])

        # create another server and ensure they both show up
        resp = self.post("/servers", data=data, expected_status_code=http_client.CREATED)
        new_server_id = resp.json()["server_id"]
        self.assertEqual(machine_id, resp.json()["machine_id"])
        resp = self.get("/servers?machine_id=%s" % machine_id)
        self.assertTrue(len(resp.json()) >= 2)
        self.assertIn(server_id, [s["server_id"] for s in resp.json()])
        self.assertIn(new_server_id, [s["server_id"] for s in resp.json()])

    def test_change_server(self):
        self.auth_service()
        machine_id = self._create_machine()["machine_id"]
        data = self._get_server_data(machine_id)
        resp = self.post("/servers", data=data, expected_status_code=http_client.CREATED)
        server_id = resp.json()["server_id"]
        self.assertGreater(server_id, 0)
        url = resp.json()["url"]
        self.put(url, data={"bla": "ble"}, expected_status_code=http_client.UNPROCESSABLE_ENTITY)

        new_data = copy.copy(data)
        new_data["details"] = {"entirely_new_details": "yes"}
        resp = self.put(url, data=new_data)
        self.assertDictEqual(ServerPutResponseSchema().validate(resp.json()), {})
        resp = self.get(url)
        self.assertEqual(resp.json()["details"].keys(), new_data["details"].keys())

    def test_server_heartbeat(self):
        self.auth_service()
        machine_id = self._create_machine()["machine_id"]
        data = self._get_server_data(machine_id)
        resp = self.post("/servers", data=data, expected_status_code=http_client.CREATED).json()
        url = resp["url"]
        resp = self.get(url).json()
        self.assertEqual(resp["heartbeat_count"], 0)
        heartbeat_date = datetime.datetime.fromisoformat(resp["heartbeat_date"][:-1]) - datetime.timedelta(seconds=1)  # Insert fudge because of clock drift on vm's
        heartbeat_url = self.get(url).json()["heartbeat_url"]
        resp = self.put(heartbeat_url).json()
        self.assertDictEqual(ServerHeartbeatPutResponseSchema().validate(resp), {})

        resp = self.get(url).json()
        self.assertEqual(resp["heartbeat_count"], 1)
        new_heartbeat_date = datetime.datetime.fromisoformat(resp["heartbeat_date"][:-1])
        self.assertTrue(new_heartbeat_date > heartbeat_date)

    def test_server_heartbeat_timeout(self):
        self.auth_service()
        machine_id = self._create_machine()["machine_id"]
        data = self._get_server_data(machine_id)
        resp = self.post("/servers", data=data, expected_status_code=http_client.CREATED)
        url = resp.json()["url"]
        heartbeat_timeout = resp.json()["heartbeat_timeout"]
        heartbeat_url = self.get(url).json()["heartbeat_url"]
        with patch("driftbase.api.servers.utcnow") as mock_date:
            mock_date.return_value = datetime.datetime.fromisoformat(heartbeat_timeout) + datetime.timedelta(seconds=5)
            self.put(heartbeat_url, expected_status_code=http_client.NOT_FOUND)

    def test_newdaemoncommand(self):
        """
        Tests for the /servers/[server_id]/commands service endpoints
        """
        self.auth_service()
        js = self._create_machine()
        machine_id = js["machine_id"]

        data = self._get_server_data(machine_id)
        resp = self.post("/servers", data=data, expected_status_code=http_client.CREATED)
        server_id = resp.json()["server_id"]
        self.assertGreater(server_id, 0)
        server_url = resp.json()["url"]

        commands_url = resp.json()["commands_url"]

        command = "swim_around"
        arguments = {"c": 1, "d": 2}
        resp = self.post(commands_url, data={"command": command, "arguments": arguments},
                         expected_status_code=http_client.CREATED)
        command_url = resp.json()["url"]

        command = "dance_the_polka"
        arguments = {"a": 1, "b": 2}
        resp = self.post(commands_url, data={"command": command, "arguments": arguments},
                         expected_status_code=http_client.CREATED)
        command_url = resp.json()["url"]

        resp = self.get(command_url)
        self.assertEqual(command, resp.json()["command"])
        self.assertEqual(arguments, resp.json()["arguments"])
        self.assertEqual("pending", resp.json()["status"])
        self.assertIsNone(resp.json()["status_date"])

        resp = self.get(commands_url)
        self.assertEqual(len(resp.json()), 2)

        resp = self.get(server_url)
        self.assertEqual(len(resp.json()["pending_commands"]), 2)

    def test_setdaemoncommandstatus(self):
        """
        Tests for the /servers/[server_id]/commands service endpoints
        """
        self.auth_service()
        js = self._create_machine()
        machine_id = js["machine_id"]

        data = self._get_server_data(machine_id)
        resp = self.post("/servers", data=data, expected_status_code=http_client.CREATED)
        server_url = resp.json()["url"]

        commands_url = resp.json()["commands_url"]

        command = "dance_the_polka"
        arguments = {"a": 1, "b": 2}
        resp = self.post(commands_url, data={"command": command, "arguments": arguments},
                         expected_status_code=http_client.CREATED)
        command_url = resp.json()["url"]
        details = {"important": "stuff"}
        self.assertEqual(len(self.get(server_url).json()["pending_commands"]), 1)
        self.patch(command_url, {"status": "completed", "details": details})
        self.assertEqual(len(self.get(server_url).json()["pending_commands"]), 0)

        # try switching status with put, should temporarily behave the same as patch
        self.put(command_url, {"status": "pending"})
        self.assertEqual(len(self.get(server_url).json()["pending_commands"]), 1)
        self.put(command_url, {"status": "completed"})
        self.assertEqual(len(self.get(server_url).json()["pending_commands"]), 0)

        resp = self.get(command_url)
        self.assertEqual("completed", resp.json()["status"])
        self.assertIsNotNone(resp.json()["status_date"])
        self.assertEqual(details, resp.json()["details"])
