# -*- coding: utf-8 -*-

import unittest
import datetime

from six.moves import http_client

from drift.systesthelper import setup_tenant, remove_tenant, service_username, service_password, local_password, uuid_string, DriftBaseTestCase, big_number


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


class CountersTests(DriftBaseTestCase):
    def test_counters_basic(self):
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        r = self.get(player_url)
        counter_url = r.json()["counter_url"]

        r = self.get(counter_url)
        self.assertTrue(len(r.json()) == 0)
        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)
        data = [{"name": "my_counter", "value": 1.23,
                 "timestamp": timestamp.isoformat(),
                 "counter_type": "count"}]
        r = self.patch(counter_url, data=data)
        r = self.get(counter_url)

        # verify that we have one value per period
        period_urls = r.json()[0]["periods"]
        value_per_period = {}
        for period, url in period_urls.items():
            if period == "all":
                continue
            r = self.get(url)
            self.assertTrue(len(r.json().values()) == 1)
            value_per_period[period] = list(r.json().values())[0]

    def test_counters_with_service_role(self):
        # Create this player and as a different player/user make sure we can modify its counters
        # with service role, but not without the service role.
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        r = self.get(player_url)
        counter_url = r.json()['counter_url']
        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)
        data = [{"name": "my_counter", "value": 1.23,
                 "timestamp": timestamp.isoformat(),
                 "counter_type": "count"}]

        # First fail with no service role
        self.auth(username=uuid_string())
        r = self.patch(counter_url, data=data, expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("Role 'service' is required for updating other players counters",
                      r.json()["error"]["description"])
        # Log on as a service and retry
        self.auth_service()
        r = self.patch(counter_url, data=data)

    @unittest.skip("Disabled because we are now using the servertime for the timestamp and "
                   "will therefore never get duplicate timestamps.")
    def test_counters_timestamp(self):

        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        r = self.get(player_url)
        counter_url = r.json()["counter_url"]

        r = self.get(counter_url)
        self.assertTrue(len(r.json()) == 0)
        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)
        data = [{"name": "my_counter", "value": 1.23,
                 "timestamp": timestamp.isoformat(),
                 "counter_type": "count"}]
        r = self.patch(counter_url, data=data)
        r = self.get(counter_url)

        # verify that we have one value per period
        period_urls = r.json()[0]["periods"]
        value_per_period = {}
        for period, url in period_urls.items():
            if period == "all":
                continue
            r = self.get(url)
            self.assertTrue(len(r.json().values()) == 1)
            value_per_period[period] = list(r.json().values())[0]

        # Send in the same data again and verify that things have not changed
        # r = self.patch(counter_url, data=data)

        # for period, url in period_urls.items():
        #     if period == "all": continue
        #     r = self.get(url)
        #     self.assertTrue(len(r.json().values()) == 1)
        #     self.assertTrue(value_per_period[period] == list(r.json().values())[0])

        # Send in data for the next day and make sure we have updated correctly
        timestamp += datetime.timedelta(days=1)
        data[0]["timestamp"] = timestamp.isoformat()
        r = self.patch(counter_url, data=data)

        r = self.get(period_urls["minute"])
        self.assertEqual(len(r.json().values()), 2)
        r = self.get(period_urls["hour"])
        self.assertEqual(len(r.json().values()), 2)
        r = self.get(period_urls["day"])
        self.assertEqual(len(r.json().values()), 2)
        r = self.get(period_urls["month"])
        self.assertEqual(len(r.json().values()), 1)
        r = self.get(period_urls["total"])
        self.assertEqual(len(r.json().values()), 1)
        self.assertEqual(float(list(r.json().values())[0]), 2 * data[0]["value"])

        data = [{"name": "my_counter",
                 "value": 1.23,
                 "timestamp": timestamp.isoformat(),
                 "counter_type": "count",
                 "context_id": 666}]
        r = self.patch(counter_url, data=data)

    def test_counters_absolute(self):
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        r = self.get(player_url)
        counter_url = r.json()["counter_url"]
        r = self.get(counter_url)
        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)
        val = 500
        data = [{"name": "my_absolute_counter",
                 "value": val,
                 "timestamp": timestamp.isoformat(),
                 "counter_type": "absolute"}]
        r = self.patch(counter_url, data=data)

        r = self.get(counter_url)
        period_urls = r.json()[0]["periods"]
        r = self.get(period_urls["total"])
        self.assertEqual(list(r.json().values())[0], val)

        # update the value and make sure it did not get added, but replaced
        val = 1666
        timestamp += datetime.timedelta(seconds=1)
        data = [{"name": "my_absolute_counter",
                 "value": val,
                 "timestamp": timestamp.isoformat(),
                 "counter_type": "absolute"}]
        r = self.patch(counter_url, data=data)

        r = self.get(period_urls["total"])
        self.assertEqual(list(r.json().values())[0], val)

        r = self.get(period_urls["day"])
        self.assertEqual(list(r.json().values())[0], val)

    def test_counters_totals(self):
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        r = self.get(player_url)
        counter_url = r.json()["counter_url"]
        countertotals_url = r.json()["countertotals_url"]
        r = self.get(counter_url)
        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)
        val = 500
        name = "my_counter"
        data = [{"name": name,
                 "value": val,
                 "timestamp": timestamp.isoformat(),
                 "counter_type": "count"}]
        r = self.patch(counter_url, data=data)
        r = self.get(countertotals_url)

        self.assertEqual(len(r.json()), 1)
        self.assertIn(name, r.json())
        self.assertEqual(r.json()[name], val)

    def test_counters_multiple(self):
        # test writing to the same counter more than once. The total count should upgade
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        r = self.get(player_url)
        counter_url = r.json()["counter_url"]
        countertotals_url = r.json()["countertotals_url"]
        r = self.get(counter_url)
        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)
        val = 500
        name = "my_counter"
        data = [{"name": name,
                 "value": val,
                 "timestamp": timestamp.isoformat(),
                 "counter_type": "count"}]
        r = self.patch(counter_url, data=data)

        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 3)
        second_val = 99
        name = "my_counter"
        data = [{"name": name,
                 "value": second_val,
                 "timestamp": timestamp.isoformat(),
                 "counter_type": "count"}]

        r = self.patch(counter_url, data=data)

        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)
        absolute_val = 666
        absolute_name = "my_absolute_counter"
        data = [{"name": absolute_name,
                 "value": absolute_val,
                 "timestamp": timestamp.isoformat(),
                 "counter_type": "absolute"}]

        r = self.patch(counter_url, data=data)

        r = self.get(countertotals_url)
        self.assertEqual(len(r.json()), 2)
        self.assertEqual(r.json()[name], val + second_val)
        self.assertEqual(r.json()[absolute_name], absolute_val)
