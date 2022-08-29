import http.client as http_client

from driftbase.systesthelper import DriftTestCase


class MachineGroupsTest(DriftTestCase):
    """
    Tests for the /machines service endpoints
    """

    def test_machinegroup_create(self):
        self.auth_service()
        data = {
            "name": "machinegroup name",
            "description": "This is a description"
        }
        r = self.post(self.endpoints["machinegroups"], data=data,
                      expected_status_code=http_client.CREATED)
        # ensure that the data made it in ok
        machinegroup_url = r.json()["url"]
        machinegroup_id = r.json()["machinegroup_id"]
        r = self.get(machinegroup_url)
        for k, v in data.items():
            self.assertEqual(v, r.json()[k])

        r = self.get(self.endpoints["machinegroups"])
        self.assertTrue(len(r.json()) >= 1)
        self.assertIn(machinegroup_id, [c["machinegroup_id"] for c in r.json()])

    def test_machinegroup_runconfig(self):
        self.auth_service()
        data = {
            "name": "machinegroup name",
            "description": "This is a description"
        }
        r = self.post(self.endpoints["machinegroups"], data=data,
                      expected_status_code=http_client.CREATED)
        # ensure that the data made it in ok
        machinegroup_url = r.json()["url"]
        runconfig_id = 1
        data = {"runconfig_id": runconfig_id}
        r = self.patch(machinegroup_url, data)

        r = self.get(machinegroup_url)
        self.assertEqual(r.json()["runconfig_id"], runconfig_id)
        # make sure the patch didn't screw up other data
        for k, v in data.items():
            self.assertEqual(v, r.json()[k])
