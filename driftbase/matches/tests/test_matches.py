# -*- coding: utf-8 -*-
from collections import defaultdict

from six.moves import http_client

from drift.systesthelper import uuid_string
from driftbase.utils.test_utils import BaseMatchTest


class MatchesTest(BaseMatchTest):
    """
    Tests for the /matches service endpoints
    """
    def test_access(self):

        self.auth()
        resp = self.get("/matches", expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

        resp = self.get("/matches/1", expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

        resp = self.post("/matches", expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

        resp = self.put("/matches/1", expected_status_code=http_client.UNAUTHORIZED)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

    def test_get_matches(self):
        self.auth_service()
        resp = self.get("/matches")
        self.assertTrue(isinstance(resp.json(), list))
        resp = self.get("/matches?server_id=1")
        self.assertTrue(isinstance(resp.json(), list))

        resp = self.get("/matches/999999", expected_status_code=http_client.NOT_FOUND)
        resp = self.put("/matches/999999", data={"status": "bla"},
                        expected_status_code=http_client.NOT_FOUND)

    def test_create_match(self):
        self.auth_service()
        match = self._create_match()
        match_url = match["url"]
        server_id = match["server_id"]

        resp = self.get(match_url)
        self.assertEqual(resp.json()["num_players"], 0)
        self.assertEqual(resp.json()["teams"], [])
        self.assertEqual(resp.json()["players"], [])
        self.assertEqual(resp.json()["status"], "idle")
        self.assertEqual(resp.json()["server_id"], server_id)
        self.assertIsNone(resp.json()["start_date"])

        # create a match with some predefined teams
        num_teams = 3
        data = {"server_id": server_id,
                "status": "active",
                "map_name": "map_name",
                "game_mode": "game_mode",
                "num_teams": num_teams
                }
        resp = self.post("/matches", data=data, expected_status_code=http_client.CREATED)
        resp = self.get(resp.json()["url"])
        self.assertEqual(len(resp.json()["teams"]), num_teams)

    def test_create_team(self):
        self.auth_service()
        match = self._create_match()
        match_id = match["match_id"]
        teams_url = match["teams_url"]
        resp = self.get(teams_url)
        self.assertTrue(isinstance(resp.json(), list))

        resp = self.post(teams_url, data={}, expected_status_code=http_client.CREATED)
        team_url = resp.json()["url"]

        resp = self.get(team_url)
        self.assertTrue(isinstance(resp.json()["players"], list))
        self.assertEqual(len(resp.json()["players"]), 0)
        resp = self.get("/matches/%s/teams/99999" % match_id,
                        expected_status_code=http_client.NOT_FOUND)

        new_name = "new name"

        resp = self.put("/matches/%s/teams/99999" % match_id, data={"name": new_name},
                        expected_status_code=http_client.NOT_FOUND)

        resp = self.put(team_url, data={"name": new_name})
        resp = self.get(team_url)
        self.assertEqual(resp.json()["name"], new_name)

    def test_add_player_to_match(self):
        self.auth()
        player_id = self.player_id
        team_id = 0

        self.auth_service()
        match = self._create_match()
        match_id = match["match_id"]
        match_url = match["url"]
        teams_url = match["teams_url"]
        resp = self.get(match_url)

        matchplayers_url = resp.json()["matchplayers_url"]

        resp = self.post(teams_url, data={}, expected_status_code=http_client.CREATED)
        team_id = resp.json()["team_id"]
        self.get(teams_url)

        data = {"player_id": player_id,
                "team_id": team_id
                }
        self.post(matchplayers_url, data=data, expected_status_code=http_client.CREATED)

        resp = self.get(match_url)
        self.assertEqual(len(resp.json()["teams"]), 1)
        self.assertIsNotNone(resp.json()["start_date"])
        self.assertEqual(resp.json()["num_players"], 1)

        resp = self.get(teams_url)
        team_url = resp.json()[0]["url"]
        self.get(team_url)

        resp = self.get(matchplayers_url)

        matchplayer_url = resp.json()[0]["matchplayer_url"]
        self.get(matchplayer_url)

        self.get("/matches/%s/players/9999999" % match_id, expected_status_code=http_client.NOT_FOUND)

    def test_active_matches(self):
        self.auth(username=uuid_string())
        player_id = self.player_id
        team_id = 0

        self.auth(username=uuid_string())
        other_player_id = self.player_id
        team_id = 0

        self.auth_service()

        match = self._create_match(max_players=3)
        match_url = match["url"]
        teams_url = match["teams_url"]
        resp = self.get(match_url)

        matchplayers_url = resp.json()["matchplayers_url"]

        resp = self.post(teams_url, data={}, expected_status_code=http_client.CREATED)
        team_id = resp.json()["team_id"]
        resp = self.get(teams_url)

        data = {"player_id": player_id,
                "team_id": team_id
                }
        self.post(matchplayers_url, data=data, expected_status_code=http_client.CREATED)

        data = {"player_id": other_player_id,
                "team_id": team_id
                }
        self.post(matchplayers_url, data=data, expected_status_code=http_client.CREATED)

        resp = self.get(match_url)
        self.assertEqual(len(resp.json()["teams"]), 1)
        resp = self.get(teams_url)
        team_url = resp.json()[0]["url"]
        resp = self.get(team_url)

        resp = self.get(matchplayers_url)

        matchplayer_url = resp.json()[0]["matchplayer_url"]
        self.get(matchplayer_url)

        resp = self.get(self.endpoints["active_matches"])
        players = resp.json()[0]["players"]
        self.assertEqual(len(players), 2)
        self.assertEqual(players[0]["player_id"], player_id)

        resp = self.get(self.endpoints["active_matches"] + "?player_id=9999999&player_id=9999998")
        self.assertEqual(len(resp.json()), 0)

        resp = self.get(self.endpoints["active_matches"] + "?player_id=9999999&player_id=%s" %
                        other_player_id)
        self.assertEqual(len(resp.json()), 1)
        players = resp.json()[0]["players"]
        self.assertEqual(players[1]["player_id"], other_player_id)

    def players_by_status(self, players):
        ret = defaultdict(list)
        for player in players:
            ret[player["status"]].append(player)
        return ret

    def test_remove_player_from_match(self):
        self.auth()
        player_id = self.player_id
        self.auth_service()
        match = self._create_match()
        match_url = match["url"]
        teams_url = match["teams_url"]

        matchplayers_url = match["matchplayers_url"]
        resp = self.post(teams_url, data={}, expected_status_code=http_client.CREATED)
        team_id = resp.json()["team_id"]
        data = {"player_id": player_id,
                "team_id": team_id
                }
        resp = self.post(matchplayers_url, data=data, expected_status_code=http_client.CREATED)
        matchplayer_url = resp.json()["url"]
        resp = self.get(match_url)
        self.assertEqual(resp.json()["num_players"], 1)

        self.delete(matchplayer_url)
        resp = self.get(match_url)
        self.assertEqual(resp.json()["num_players"], 1)
        pbs = self.players_by_status(resp.json()["players"])
        self.assertEqual(len(pbs["active"]), 0)
        self.assertEqual(len(pbs["quit"]), 1)

        # you cannot quit twice
        self.delete(matchplayer_url, expected_status_code=http_client.BAD_REQUEST)
        resp = self.get(match_url)
        self.assertEqual(resp.json()["num_players"], 1)
        pbs = self.players_by_status(resp.json()["players"])
        self.assertEqual(len(pbs["active"]), 0)
        self.assertEqual(len(pbs["quit"]), 1)

        # join the fight again
        self.post(matchplayers_url, data=data, expected_status_code=http_client.CREATED)
        resp = self.get(match_url)
        self.assertEqual(resp.json()["num_players"], 1)
        pbs = self.players_by_status(resp.json()["players"])
        self.assertEqual(len(pbs["active"]), 1)
        self.assertEqual(len(pbs["quit"]), 0)

        # now you can quit again
        self.delete(matchplayer_url)

    def test_match_start_date_is_set_when_first_player_joins(self):
        self.auth("player_1")
        player1_id = self.player_id
        self.auth("player_2")
        player2_id = self.player_id

        self.auth_service()
        match = self._create_match()
        match_url = match["url"]
        teams_url = match["teams_url"]
        resp = self.get(match_url)
        self.assertEqual(resp.json()["start_date"], None)

        matchplayers_url = match["matchplayers_url"]
        resp = self.post(teams_url, data={}, expected_status_code=http_client.CREATED)
        team_id = resp.json()["team_id"]
        data1 = {"player_id": player1_id,
                "team_id": team_id
                }
        resp = self.post(matchplayers_url, data=data1, expected_status_code=http_client.CREATED)
        matchplayer1_url = resp.json()["url"]
        resp = self.get(match_url)
        match_start = resp.json()["start_date"]

        data2 = {"player_id": player2_id,
                "team_id": team_id
                }
        resp = self.post(matchplayers_url, data=data2, expected_status_code=http_client.CREATED)
        matchplayer2_url = resp.json()["url"]
        resp = self.get(match_url)
        self.assertEqual(match_start, resp.json()["start_date"])

        self.delete(matchplayer1_url)
        self.delete(matchplayer2_url)
        resp = self.get(match_url)
        self.assertEqual(match_start, resp.json()["start_date"])

        self.post(matchplayers_url, data=data1, expected_status_code=http_client.CREATED)
        resp = self.get(match_url)
        self.assertEqual(match_start, resp.json()["start_date"])

    def test_change_match(self):
        self.auth_service()
        match = self._create_match()
        match_url = match["url"]
        self.put(match_url, data={"status": "new_status"})

        self.put(match_url, data={"status": "started"})

        self.put(match_url, data={"status": "completed"})
        resp = self.put(match_url, data={"status": "active"},
                        expected_status_code=http_client.BAD_REQUEST)
        self.assertIn("already been completed", resp.json()["error"]["description"])

    def test_max_players(self):
        player_ids = []
        for i in xrange(3):
            self.auth(username="user_%s" % i)
            player_ids.append(self.player_id)

        self.auth_service()
        match = self._create_match(num_teams=2)
        matchplayers_url = match["matchplayers_url"]

        match_url = match["url"]
        resp = self.get(match_url)
        team_id = resp.json()["teams"][0]["team_id"]
        for player_id in player_ids[0:2]:
            data = {"player_id": player_id,
                    "team_id": team_id
                    }
            resp = self.post(matchplayers_url, data=data, expected_status_code=http_client.CREATED)

        data = {"player_id": player_ids[-1],
                "team_id": team_id
                }
        self.post(matchplayers_url, data=data, expected_status_code=http_client.BAD_REQUEST)

    def test_active_matches_depend_on_match_status(self):
        self.auth_service()

        match = self._create_match(max_players=4)
        match_url = match["url"]
        match_id = match["match_id"]
        server_id = match["server_id"]

        resp = self.get(self.endpoints["active_matches"])
        self.assertEqual(len(self._filter_matches(resp, [match_id])), 1)

        self.put(match_url, data={"status": "ended"})
        resp = self.get(self.endpoints["active_matches"])
        self.assertEqual(len(self._filter_matches(resp, [match_id])), 0)

        match = self._create_match(max_players=4, server_id=server_id)
        match_url = match["url"]
        self.put(match_url, data={"status": "completed"})
        resp = self.get(self.endpoints["active_matches"])
        self.assertEqual(len(self._filter_matches(resp, [match_id])), 0)

    def test_active_matches_depend_on_server_status(self):
        self.auth_service()

        match = self._create_match(max_players=4)
        match_id = match["match_id"]
        server_url = match["server_url"]

        resp = self.get(self.endpoints["active_matches"])
        self.assertEqual(len(self._filter_matches(resp, [match_id])), 1)

        self.put(server_url, data={"status": "quit"})
        resp = self.get(self.endpoints["active_matches"])
        self.assertEqual(len(self._filter_matches(resp, [match_id])), 0)
