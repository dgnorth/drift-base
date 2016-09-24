# -*- coding: utf-8 -*-

import os
from os.path import abspath, join
config_file = abspath(join(__file__, "..", "..", "..", "config", "config.json"))
os.environ.setdefault("drift_CONFIG", config_file)

import httplib
import unittest
from mock import patch
from drift.systesthelper import setup_tenant, remove_tenant, DriftBaseTestCase


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


class MachineGroupsTest(DriftBaseTestCase):
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
                      expected_status_code=httplib.CREATED)
        # ensure that the data made it in ok
        machinegroup_url = r.json()["url"]
        machinegroup_id = r.json()["machinegroup_id"]
        r = self.get(machinegroup_url)
        for k, v in data.iteritems():
            self.assertEquals(v, r.json()[k])

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
                      expected_status_code=httplib.CREATED)
        # ensure that the data made it in ok
        machinegroup_url = r.json()["url"]
        runconfig_id = 1
        data = {"runconfig_id": runconfig_id}
        r = self.patch(machinegroup_url, data)

        r = self.get(machinegroup_url)
        self.assertEquals(r.json()["runconfig_id"], runconfig_id)
        # make sure the patch didn't screw up other data
        for k, v in data.iteritems():
            self.assertEquals(v, r.json()[k])


if __name__ == '__main__':
    unittest.main()
