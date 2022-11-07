import datetime
import http.client as http_client

from drift.systesthelper import setup_tenant, remove_tenant, uuid_string
from driftbase.systesthelper import DriftBaseTestCase


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


class CountersTest(DriftBaseTestCase):
    """
    Tests for the /counters endpoint
    """

    def test_counters_put(self):
        # verify that the temporary put versions of the patch endpoints work
        self.auth(username=uuid_string())
        name = "my_put_counter"
        player_url = self.endpoints["my_player"]
        r = self.get(player_url)
        counter_url = r.json()["counter_url"]
        countertotals_url = r.json()["countertotals_url"]
        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)
        val = 666
        data = [{"name": name, "value": val, "timestamp": timestamp.isoformat(),
                 "counter_type": "count"}]
        r = self.put(counter_url, data=data)
        r = self.get(countertotals_url)

        self.assertEqual(len(r.json()), 1)
        self.assertIn(name, r.json())
        self.assertEqual(r.json()[name], val)

    def test_counters_positions(self):
        name = "my_leaderboard_counter"
        num_players = 5
        players = []
        for i in range(num_players):
            self.auth(username=uuid_string())
            player_url = self.endpoints["my_player"]
            self.patch(player_url, {"name": "Player %s" % i})
            r = self.get(player_url)
            counter_url = r.json()["counter_url"]
            countertotals_url = r.json()["countertotals_url"]
            r = self.get(counter_url)
            timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)
            val = 500 + i
            data = [{"name": name, "value": val, "timestamp": timestamp.isoformat(),
                     "counter_type": "count"}]
            r = self.patch(counter_url, data=data)
            r = self.get(countertotals_url)

            self.assertEqual(len(r.json()), 1)
            self.assertIn(name, r.json())
            self.assertEqual(r.json()[name], val)

            players.append((self.player_id, player_url, val))

        url = self.endpoints["counters"]
        r = self.get(url)
        self.assertIn(name, [c["name"] for c in r.json()])
        counter_url = None
        for c in r.json():
            if c["name"] == name:
                counter_url = c["url"]
        r = self.get(counter_url)
        self.assertEqual(len(r.json()), num_players)

        # verify that the leaderboard is sorted correctly with the
        # player with the highest score at the top
        for i, pl in enumerate(reversed(players)):
            player_id, player_url, val = pl
            self.assertEqual(r.json()[i]["position"], i + 1)
            self.assertEqual(r.json()[i]["total"], val)
            self.assertEqual(r.json()[i]["player_id"], player_id)

    def test_counters_include(self):
        # create some counters
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        self.patch(player_url, {"name": "Something"})
        r = self.get(player_url)
        counter_url = r.json()["counter_url"]
        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)

        data = [
            {"name": "first_counter", "value": 12, "timestamp": timestamp.isoformat()},
            {"name": "second_counter", "value": 22, "timestamp": timestamp.isoformat()},
            {"name": "third_counter", "value": 32, "timestamp": timestamp.isoformat()}
        ]
        r = self.patch(counter_url, data=data)

        # take a look at the counters 'leaderboard' base endpoint
        url = self.endpoints["counters"]
        r = self.get(url)
        counter_ids = []
        counter_leaderboard_url = None
        for c in r.json():
            if c["name"] == "first_counter":
                counter_leaderboard_url = c["url"]
            elif c["name"] in ("second_counter", "third_counter"):
                counter_ids.append(c["counter_id"])

        # look up the first counter we made and make sure we don't have any included counters
        r = self.get(counter_leaderboard_url)
        self.assertEqual(len(r.json()[0]["include"]), 0)

        # ask for the second and third counter to be included and ensure that they are
        include_string = ""
        for counter_id in counter_ids:
            include_string += "include=%s&" % counter_id
        url = counter_leaderboard_url + "?%s" % include_string
        r = self.get(url)
        self.assertEqual(len(r.json()[0]["include"]), len(counter_ids))
        for included_counter in r.json()[0]["include"]:
            self.assertTrue(included_counter["counter_id"] in counter_ids)

    def test_counters_filters(self):
        # create some counters
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        first_player_id = self.player_id
        self.patch(player_url, {"name": "Something"})
        r = self.get(player_url)
        counter_url = r.json()["counter_url"]
        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)

        data = [
            {"name": "first_counter", "value": 12, "timestamp": timestamp.isoformat()},
            {"name": "second_counter", "value": 22, "timestamp": timestamp.isoformat()},
            {"name": "third_counter", "value": 32, "timestamp": timestamp.isoformat()}
        ]
        r = self.patch(counter_url, data=data)

        # another player also posts counter
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        second_player_id = self.player_id
        self.patch(player_url, {"name": "Something"})
        r = self.get(player_url)
        counter_url = r.json()["counter_url"]
        r = self.patch(counter_url, data=data)

        # take a look at the counters 'leaderboard' base endpoint
        url = self.endpoints["counters"]
        r = self.get(url)
        counter_ids = []
        counter_leaderboard_url = None
        for c in r.json():
            if c["name"] == "first_counter":
                counter_leaderboard_url = c["url"]
            elif c["name"] in ("second_counter", "third_counter"):
                counter_ids.append(c["counter_id"])

        r = self.get(counter_leaderboard_url)
        player_ids = [c["player_id"] for c in r.json()]
        self.assertIn(first_player_id, player_ids)
        self.assertIn(second_player_id, player_ids)

        r = self.get(counter_leaderboard_url + "?player_id=9999999")
        player_ids = [c["player_id"] for c in r.json()]
        self.assertEqual(r.json(), [])

        r = self.get(counter_leaderboard_url + "?player_id=%s" % second_player_id)
        player_ids = [c["player_id"] for c in r.json()]
        self.assertIn(second_player_id, player_ids)
        self.assertNotIn(first_player_id, player_ids)

        # Test player_group
        pg_url = self.endpoints["my_player_groups"].replace('{group_name}', 'second_player')
        self.put(pg_url, data={'player_ids': [second_player_id]}, expected_status_code=http_client.OK)
        r = self.get(counter_leaderboard_url + "?player_group=second_player")
        player_ids = [c["player_id"] for c in r.json()]
        self.assertIn(second_player_id, player_ids)
        self.assertNotIn(first_player_id, player_ids)

    def test_counters_reverse(self):
        counter_name = "my_reverse_counter"

        # create some counters
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        self.patch(player_url, {"name": "First Player"})
        r = self.get(player_url)
        counter_url = r.json()["counter_url"]
        timestamp = datetime.datetime(2016, 1, 1, 10, 2, 2)

        data = [
            {"name": counter_name, "value": 100, "timestamp": timestamp.isoformat()}
        ]
        r = self.patch(counter_url, data=data)

        # another player also posts counter
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        self.patch(player_url, {"name": "First Player"})
        r = self.get(player_url)
        counter_url = r.json()["counter_url"]
        data = [
            {"name": counter_name, "value": 200, "timestamp": timestamp.isoformat()}
        ]
        r = self.patch(counter_url, data=data)

        # take a look at the counters 'leaderboard' base endpoint
        url = self.endpoints["counters"]
        r = self.get(url)

        counter_leaderboard_url = None
        for c in r.json():
            if c["name"] == counter_name:
                counter_leaderboard_url = c["url"]

        r = self.get(counter_leaderboard_url)
        self.assertEqual(len(r.json()), 2)
        self.assertTrue(r.json()[0]["total"] > r.json()[1]["total"])

        r = self.get(counter_leaderboard_url + "?reverse=true")
        self.assertEqual(len(r.json()), 2)
        self.assertTrue(r.json()[0]["total"] < r.json()[1]["total"])
