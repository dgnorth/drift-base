# -*- coding: utf-8 -*-

import os, sys, copy, json, types, datetime
from os.path import abspath, join
config_file = abspath(join(__file__, "..", "..", "..", "config", "config.json"))
os.environ.setdefault("drift_CONFIG", config_file)

import httplib
import unittest
from mock import patch

from drift.systesthelper import setup_tenant, remove_tenant, DriftBaseTestCase, db_name
from drift.tenant import get_connection_string

from driftbase.utils.test_utils import BaseCloudkitTest
import driftbase.matchqueue
import driftbase.tasks

def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


def get_mock_tenants():
    t = {"name": os.environ.get("drift_test_database"),
         "db_server": "localhost",
         "redis_server": "localhost",
         "heartbeat_timeout": 0,
         }
    conn_string = get_connection_string(t, None, tier_name="DEVNORTH")
    t["conn_string"] = conn_string
    return [t]

@patch("driftbase.tasks.get_tenants", get_mock_tenants)
class CeleryBeatTest(BaseCloudkitTest):
    """
    Tests for celery scheduled tasks
    """
    def test_celery_utility(self):
        tenants = driftbase.tasks.get_tenants()
        self.assertTrue(isinstance(tenants, types.ListType))
        self.assertIn("db_server", tenants[0])
        self.assertIn("redis_server", tenants[0])
        self.assertIn("conn_string", tenants[0])
        self.assertIn("name", tenants[0])

    def test_celery_update_online_statistics(self):
        # make a new player and heartbeat once
        self.make_player()
        self.put(self.endpoints["my_client"])
        driftbase.tasks.update_online_statistics()
        # verify that the counter now exists
        r = self.get(self.endpoints["counters"])
        self.assertIn("backend.numonline", [row["name"] for row in r.json()])

    def test_celery_flush_request_statistics(self):
        # call the function before and after adding a new player
        driftbase.tasks.flush_request_statistics()
        self.make_player()
        driftbase.tasks.flush_request_statistics()

    def test_celery_flush_counters(self):
        # Note: flush_counters doesn't currently do anything since counters are
        # written into the db straight away. That will be refactored and this test
        # will need to reflect it
        self.make_player()
        counter_name = "test_celery_flush_counters"
        # verify that the new counter has not been added to the list of counters
        r = self.get(self.endpoints["counters"])
        self.assertNotIn(counter_name, [row["name"] for row in r.json()])

        r = self.get(self.endpoints["my_player"])
        counter_url = r.json()["counter_url"]
        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)
        data = [{"name": counter_name, "value": 1.23,
                 "timestamp": timestamp.isoformat(),
                 "counter_type": "count"}]
        r = self.patch(counter_url, data=data)
        # the counter should now be in the list
        r = self.get(self.endpoints["counters"])
        self.assertIn(counter_name, [row["name"] for row in r.json()])
        counterstats_url = None
        for row in r.json():
            if row["name"] == counter_name:
                counterstats_url = row["url"]

        r = self.get(counterstats_url)

        driftbase.tasks.flush_counters()

        r = self.get(counterstats_url)

    def test_celery_timeout_clients(self):
        self.make_player()
        driftbase.tasks.timeout_clients()

    def test_celery_cleanup_orphaned_matchqueues(self):
        self.make_player()
        # TODO: Need to extend this test with orphaned matchqueues to clean up.
        driftbase.matchqueue.cleanup_orphaned_matchqueues()

if __name__ == '__main__':
    unittest.main()
