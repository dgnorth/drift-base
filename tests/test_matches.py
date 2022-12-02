from collections import defaultdict

import http.client as http_client

from drift.test_helpers.systesthelper import uuid_string
from driftbase.utils.test_utils import BaseMatchTest


class MatchesTest(BaseMatchTest):
    """
    Tests for the /matches service endpoints
    """
    def test_access(self):

        self.auth()

        resp = self.get("/matches/1", expected_status_code=http_client.FORBIDDEN)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

        resp = self.post("/matches", expected_status_code=http_client.FORBIDDEN)
        self.assertIn("You do not have access", resp.json()["error"]["description"])

        resp = self.put("/matches/1", expected_status_code=http_client.FORBIDDEN)
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

    def test_get_matches_pagination(self):
        self.auth_service()
        resp = self.get("/matches", params={"use_pagination": True})
        resp_json = resp.json()

        self.assertTrue(isinstance(resp_json, dict))

        self.assertIn("items", resp_json)
        self.assertIn("total", resp_json)
        self.assertIn("page", resp_json)
        self.assertIn("pages", resp_json)
        self.assertIn("per_page", resp_json)

        # create a few matches
        num_matches = 10
        for _ in range(num_matches):
            self._create_match()

        # Get exact number of matches created
        resp = self.get("/matches", params={"use_pagination": True, "per_page": num_matches})
        resp_json = resp.json()

        self.assertTrue(len(resp_json["items"]) >= num_matches)
        self.assertTrue(resp_json["total"] >= num_matches)
        self.assertEqual(resp_json["page"], 1)
        self.assertEqual(resp_json["per_page"], num_matches)

        match = resp_json["items"][0]
        self.assertIn("url", match)
        self.assertIn("matchplayers_url", match)
        self.assertIn("teams_url", match)
        self.assertNotIn("players", match)
        self.assertNotIn("teams", match)

        # Get fewer matches than created
        fewer_matches = num_matches // 2
        resp = self.get("/matches", params={"use_pagination": True, "per_page": fewer_matches})
        resp_json = resp.json()

        self.assertEqual(len(resp_json["items"]), fewer_matches)
        self.assertTrue(resp_json["total"] >= num_matches)
        self.assertEqual(resp_json["page"], 1)
        self.assertEqual(resp_json["per_page"], fewer_matches)
        self.assertTrue(resp_json["pages"] >= num_matches // fewer_matches)

        # Get include players
        resp = self.get("/matches", params={"use_pagination": True, "include_match_players": True})
        resp_json = resp.json()

        match = resp_json["items"][0]
        self.assertIn("url", match)
        self.assertIn("matchplayers_url", match)
        self.assertIn("teams_url", match)
        self.assertIn("players", match)
        self.assertIn("teams", match)


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

    def test_create_match_num_teams(self):
        self.auth_service()
        machine = self._create_machine()
        server = self._create_server(machine["machine_id"])
        server_id = server["server_id"]

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

    def test_create_match_team_names(self):
        self.auth_service()
        machine = self._create_machine()
        server = self._create_server(machine["machine_id"])
        server_id = server["server_id"]

        # create a match with some predefined teams
        team_names = ["team1", "team2", "team3"]
        data = {"server_id": server_id,
                "status": "active",
                "map_name": "map_name",
                "game_mode": "game_mode",
                "team_names": team_names
                }
        resp = self.post("/matches", data=data, expected_status_code=http_client.CREATED)
        resp = self.get(resp.json()["url"])
        self.assertEqual(len(resp.json()["teams"]), len(team_names))

        for team in resp.json()["teams"]:
            self.assertIn(team["name"], team_names)

    def test_create_match_num_teams_and_team_names(self):
        self.auth_service()
        machine = self._create_machine()
        server = self._create_server(machine["machine_id"])
        server_id = server["server_id"]

        # create a match with some predefined teams
        team_names = ["team1", "team2", "team3"]
        data = {"server_id": server_id,
                "status": "active",
                "map_name": "map_name",
                "game_mode": "game_mode",
                "team_names": team_names,
                "num_teams": len(team_names)
                }

        self.post("/matches", data=data, expected_status_code=http_client.BAD_REQUEST)

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
        resp = self.get(match_url).json()

        matchplayers_url = resp["matchplayers_url"]

        resp = self.post(teams_url, data={}, expected_status_code=http_client.CREATED).json()
        team_id = resp["team_id"]
        resp = self.get(teams_url).json()

        data = {"player_id": player_id,
                "team_id": team_id
                }
        resp = self.post(matchplayers_url, data=data, expected_status_code=http_client.CREATED).json()

        resp = self.get(match_url).json()
        self.assertEqual(len(resp["teams"]), 1)
        self.assertIsNotNone(resp["start_date"])
        self.assertEqual(resp["num_players"], 1)

        resp = self.get(teams_url).json()
        team_url = resp[0]["url"]
        self.get(team_url)

        resp = self.get(matchplayers_url).json()

        matchplayer_url = resp[0]["matchplayer_url"]
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

    def test_update_player_in_match(self):
        # Create player and match
        self.auth()
        player_id = self.player_id
        self.auth_service()
        match = self._create_match()
        teams_url = match["teams_url"]
        matchplayers_url = match["matchplayers_url"]

        # Create match team
        response = self.post(teams_url, data={}, expected_status_code=http_client.CREATED)
        team_id = response.json()["team_id"]
        data = {"player_id": player_id, "team_id": team_id }

        # Create match player
        response = self.post(matchplayers_url, data=data, expected_status_code=http_client.CREATED)
        matchplayer_created_response = response.json()
        matchplayer_url = matchplayer_created_response["url"]

        # Verify details doesn't exist for the match player
        self.assertTrue("details" not in matchplayer_created_response)

        # Update match player details
        new_details = {"foo": "bar"}

        response = self.patch(matchplayer_url, data={"details": new_details}, expected_status_code=http_client.OK)
        matchplayer_update_response = response.json()

        # Verify details exists for the match player
        self.assertDictEqual(matchplayer_update_response["details"], new_details)

        # Verify getter returns the same details
        response = self.get(matchplayer_url, expected_status_code=http_client.OK)
        matchplayer_update_response = response.json()

        self.assertDictEqual(matchplayer_update_response, response.json())

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
        data1 = {
            "player_id": player1_id,
            "team_id": team_id
            }
        resp = self.post(matchplayers_url, data=data1, expected_status_code=http_client.CREATED)
        matchplayer1_url = resp.json()["url"]
        resp = self.get(match_url)
        match_start = resp.json()["start_date"]

        data2 = {
            "player_id": player2_id,
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
        for i in range(3):
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

    def test_unique_match(self):
        self.auth_service()
        # Create a match with a unique_key
        match = self._create_match(unique_key="123")
        match_url_a = match["url"]

        resp = self.get(match_url_a)
        self.assertEqual(resp.json()["unique_key"], "123")

        # It should not be possible to create another match with the same unique key
        match = self._create_match(expected_status_code=http_client.CONFLICT, unique_key="123")
        self.assertIsNone(match)

        # Creating another match with another unique_key is OK
        match = self._create_match(unique_key="456")
        match_url_b = match["url"]

        resp = self.get(match_url_b)
        self.assertEqual(resp.json()["unique_key"], "456")

        # Creating another match with the same unique_key is possible if existing ones have completed
        self.put(match_url_b, {"status": "completed"}, expected_status_code=http_client.OK)

        match = self._create_match(unique_key="456")
        match_url_c = match["url"]

        # Check that we actually got a new match
        self.assertNotEqual(match_url_b, match_url_c)

        resp = self.get(match_url_c)
        self.assertEqual(resp.json()["unique_key"], "456")

    def test_unique_match_updates(self):
        self.auth_service()
        # Create a match without a unique key
        match = self._create_match()
        match_url_a = match["url"]

        resp = self.get(match_url_a)
        self.assertIsNone(resp.json().get("unique_key"))

        # Set the unique key
        self.put(match_url_a, {"status": "idle", "unique_key": "abc"}, expected_status_code=http_client.OK)

        match = self._create_match()
        match_url_b = match["url"]

        # Check that another match can't be changed to the same unique key
        self.put(match_url_b, {"status": "idle", "unique_key": "abc"}, expected_status_code=http_client.CONFLICT)

        # Check that the unique key cannot be changed if not empty
        self.put(match_url_a, {"status": "idle", "unique_key": "efg"}, expected_status_code=http_client.CONFLICT)
