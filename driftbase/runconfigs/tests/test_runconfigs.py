# -*- coding: utf-8 -*-

import os
from os.path import abspath, join
config_file = abspath(join(__file__, "..", "..", "..", "config", "config.json"))
os.environ.setdefault("drift_CONFIG", config_file)

import httplib
import unittest, responses, mock
import json, requests
from mock import patch
from drift.systesthelper import setup_tenant, remove_tenant, DriftBaseTestCase


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


class RunConfigsTest(DriftBaseTestCase):
    """
    Tests for the /machines service endpoints
    """
    def test_runconfig_create(self):
        self.auth_service()
        data = {
            "name": "runconfig name",
            "repository": "Test/Test",
            "ref": "test/test",
            "build": "HEAD"
        }
        r = self.post(self.endpoints["runconfigs"], data=data, expected_status_code=httplib.CREATED)
        # ensure that the data made it in ok
        runconfig_url = r.json()["url"]
        r = self.get(runconfig_url)
        for k, v in data.iteritems():
            self.assertEquals(v, r.json()[k])

        # you should not be able to create another run config with the same name
        self.post(self.endpoints["runconfigs"], data=data, expected_status_code=httplib.BAD_REQUEST)


if __name__ == '__main__':
    unittest.main()
