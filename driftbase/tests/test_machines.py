from six.moves import http_client
from drift.systesthelper import DriftBaseTestCase

from driftbase.api.machines import MachinesPostResponseSchema, MachinePutResponseSchema


class MachinesTest(DriftBaseTestCase):
    """
    Tests for the /machines service endpoints
    """
    def test_access(self):
        self.auth()
        resp = self.get("/machines?realm=local&instance_name=dummy",
                        expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

        resp = self.get("/machines/1", expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

        resp = self.post("/machines", expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

    def test_get_invalid(self):
        self.auth_service()
        resp = self.get("/machines?realm=ble", expected_status_code=http_client.BAD_REQUEST)
        resp = self.get("/machines?realm=ble&instance_name=instance-name",
                        expected_status_code=http_client.BAD_REQUEST)

        resp = self.get("/machines?realm=aws", expected_status_code=http_client.BAD_REQUEST)

        resp = self.get("/machines?realm=aws&instance_name=instance-name",
                        expected_status_code=http_client.BAD_REQUEST)
        self.assertIn("missing required", resp.json()["error"]["description"])

        resp = self.get("/machines/9999999", expected_status_code=http_client.NOT_FOUND)

    def test_update_machine(self):
        self.auth_service()

        data = {"realm": "local", "instance_name": "local"}
        resp = self.post("/machines", data=data, expected_status_code=http_client.CREATED)
        url = resp.json()["url"]
        resp = self.get(url)
        self.assertEqual(resp.json()["realm"], data["realm"])
        self.assertEqual(resp.json()["instance_name"], data["instance_name"])
        resp.json()["machine_id"]
        resp = self.put(url)
        self.assertDictEqual(MachinePutResponseSchema().validate(resp.json()), {})
        # ! TODO: System tests are currently offline. Will continue this later and add PUT tests

    def test_get_awsmachine(self):
        self.auth_service()
        resp = self.get("/machines?realm=aws&instance_name=test&instance_id=1&"
                        "instance_type=2&placement=3&public_ip=8.8.8.8")
        self.assertTrue(isinstance(resp.json(), list))
        self.assertEqual(len(resp.json()), 0)

    def test_get_localmachine(self):
        self.auth_service()
        resp = self.get("/machines?realm=local&instance_name=dummy")
        self.assertTrue(isinstance(resp.json(), list))
        self.assertEqual(len(resp.json()), 0)

    def test_create_localmachine(self):
        self.auth_service()

        data = {"realm": "local", "instance_name": "local"}
        resp = self.post("/machines", data=data, expected_status_code=http_client.CREATED)
        self.assertDictEqual(MachinesPostResponseSchema().validate(resp.json()), {})
        url = resp.json()["url"]
        resp = self.get(url)
        self.assertEqual(resp.json()["realm"], data["realm"])
        self.assertEqual(resp.json()["instance_name"], data["instance_name"])
        machine_id = resp.json()["machine_id"]

        resp = self.get("/machines?realm=local&instance_name=%s" % data["instance_name"])
        self.assertTrue(len(resp.json()) > 0)
        self.assertIn(machine_id, [r["machine_id"] for r in resp.json()])

    def test_create_awsmachine(self):
        self.auth_service()

        data = {"realm": "aws",
                "instance_name": "awsinstance",
                "placement": "placement",
                "instance_type": "instance_type",
                "instance_id": "instance_id",
                "public_ip": "8.8.8.8",
                }
        resp = self.post("/machines", data=data, expected_status_code=http_client.CREATED)
        self.assertDictEqual(MachinesPostResponseSchema().validate(resp.json()), {})
        url = resp.json()["url"]
        resp = self.get(url)
        self.assertEqual(resp.json()["realm"], data["realm"])
        self.assertEqual(resp.json()["instance_name"], data["instance_name"])
        machine_id = resp.json()["machine_id"]

        qry = ""
        for k, v in data.items():
            qry += "%s=%s&" % (k, v)
        url = "/machines?%s" % qry
        resp = self.get(url)
        self.assertTrue(len(resp.json()) > 0)
        self.assertIn(machine_id, [r["machine_id"] for r in resp.json()])
