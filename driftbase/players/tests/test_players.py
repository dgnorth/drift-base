# -*- coding: utf-8 -*-
import datetime
from six.moves import http_client
from mock import patch

from drift.systesthelper import uuid_string, big_number
from driftbase.utils.test_utils import BaseCloudkitTest


class PlayersTest(BaseCloudkitTest):
    """
    Tests for the /players endpoints
    """
    def test_players_online(self):
        # create a new user and client
        self.make_player()
        r = self.get(self.endpoints["my_player"])
        self.assertTrue(r.json()["is_online"])

        # mock out the utcnow call so that we can put the players 'offline'
        with patch("driftbase.db.models.utcnow") as mock_date:
            mock_date.return_value = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)
            r = self.get(self.endpoints["my_player"])
            self.assertFalse(r.json()["is_online"])

        # make a new player but never log him in. Make sure he is correctly reported as offline
        self.auth(username="Player with no client")
        r = self.get(self.endpoints["my_player"])
        self.assertFalse(r.json()["is_online"])

    def test_players_urls(self):
        self.make_player()
        r = self.get(self.endpoints["my_player"])
        js = r.json()
        urls = ["player_url", "gamestates_url", "journal_url", "user_url",
                "messagequeue_url", "messages_url",
                "summary_url", "countertotals_url", "counter_url", "tickets_url"]

        # make sure the urls in the list are in the response and non-empty
        for url in urls:
            self.assertIn(url, js)
            self.assertIsNotNone(js[url])

    def test_players(self):

        # Create three players for test
        self.auth(username="Number one user")
        p1 = self.player_id
        self.assertGreater(p1, 0)
        self.auth(username="Number two user")
        p2 = self.player_id
        self.assertGreater(p2, 0)
        self.auth(username="Number three user")
        player_id = self.player_id
        player_info = self.get(self.endpoints["my_player"]).json()
        self.assertIsInstance(player_info, dict)

        # Should have at least three player records. Let's ask for two.
        players = self.get(self.endpoints["players"] + "?rows=2").json()
        self.assertIsInstance(players, list)
        self.assertEqual(len(players), 2)

        # Filter a query on a particular player ID
        players = self.get(self.endpoints["players"] + "?player_id=%s" % player_id).json()
        self.assertTrue(len(players) == 1)
        self.assertEqual(players[0], player_info)

        # Let's not find a particular player
        self.get(self.endpoints["players"] + "/{}".format(big_number),
                 expected_status_code=http_client.NOT_FOUND)

    def test_change_name(self):
        self.auth()
        player_url = self.endpoints["my_player"]
        r = self.get(player_url)
        old_name = r.json()["player_name"]
        self.patch(player_url, data={"name": ""}, expected_status_code=http_client.METHOD_NOT_ALLOWED)
        self.patch(player_url, data={"name": "a" * 100},
                   expected_status_code=http_client.METHOD_NOT_ALLOWED)
        self.patch(self.endpoints["players"] + "/9999999", data={"name": "a" * 100},
                   expected_status_code=http_client.METHOD_NOT_ALLOWED)

        self.assertEqual(self.get(player_url).json()["player_name"], old_name)

        new_name = "new name %s" % uuid_string()
        r = self.patch(player_url, data={"name": new_name})
        self.assertEqual(r.json()["player_name"], new_name)
        self.assertEqual(self.get(player_url).json()["player_name"], new_name)

    def test_change_name_put(self):
        # verify that the temporary put versions of the patch endpoints work
        self.auth()
        player_url = self.endpoints["my_player"]
        r = self.get(player_url)
        new_name = "new name %s" % uuid_string()
        r = self.put(player_url, data={"name": new_name})
        self.assertEqual(r.json()["player_name"], new_name)
        self.assertEqual(self.get(player_url).json()["player_name"], new_name)

    def test_root_endpoints(self):
        # Verify that my_xxx endpoints are populated after authentication
        r = self.get("/")
        endpoints = r.json()["endpoints"]
        for name, endpoint in endpoints.iteritems():
            if name.startswith("my_"):
                self.assertIsNone(endpoint)

        self.auth()
        r = self.get("/")
        endpoints = r.json()["endpoints"]
        for name, endpoint in endpoints.iteritems():
            if name.startswith("my_") and name != "my_client":
                self.assertIsNotNone(endpoint)

    def test_players_keys(self):
        # make sure only the requested keys are returned
        self.make_player()
        url = self.endpoints["players"] + "?key=player_id&key=is_online"

        r = self.get(url)
        self.assertIn("player_id", r.json()[0])
        self.assertIn("is_online", r.json()[0])
        self.assertEqual(len(r.json()[0]), 2)

        # if the key is not found it will be returned as None
        url = self.endpoints["players"] + "?key=player_id&key=is_online&key=invalid"
        r = self.get(url)
        self.assertIsNone(r.json()[0]["invalid"])

        # player_id should always be returned
        url = self.endpoints["players"] + "?key=player_name"
        r = self.get(url)
        self.assertIsNotNone(r.json()[0]["player_id"])
        self.assertIsNotNone(r.json()[0]["player_name"])
