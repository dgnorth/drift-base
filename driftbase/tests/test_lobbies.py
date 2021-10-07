import http.client as http_client
import copy
import typing
import datetime

from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import flexmatch, lobbies, parties

MOCK_LOBBY = {
    "create_date": "2021-09-24T16:15:08.758448",
    "custom_data": None,
    "lobby_id": "123456",
    "lobby_name": "MockLobby",
    "map_name": "MockMap",
    "members": [
        {
            "host": True,
            "player_id": 1337,
            "player_name": "MockPlayer",
            "ready": False,
            "team_name": None
        }
    ],
    "start_date": None,
    "status": "idle",
    "team_capacity": 4,
    "team_names": [
        "MockTeam1",
        "MockTeam2"
    ]
}

MOCK_ERROR = "Some error"

class _BaseLobbyTest(BaseCloudkitTest):
    lobby = None
    lobby_id = None
    lobby_url = None
    lobby_members_url = None
    lobby_member_url = None

    def create_lobby(self, lobby_data: typing.Optional[dict] = None):
        if not lobby_data:
            lobby_data = {
                "team_capacity": 4,
                "team_names": ["1", "2"],
            }

        response = self.post(self.endpoints["lobbies"], data=lobby_data, expected_status_code=http_client.CREATED)
        self._extract_lobby(response.json())

    def join_lobby(self, lobby_members_url: str):
        response = self.post(lobby_members_url, expected_status_code=http_client.CREATED)
        self._extract_lobby(response.json())

    def delete_lobby(self):
        self.delete(self.lobby_url, expected_status_code=http_client.NO_CONTENT)

    def leave_lobby(self):
        self.delete(self.lobby_member_url, expected_status_code=http_client.NO_CONTENT)

    def kick_lobby_member(self, lobby_member_url: str):
        self.delete(lobby_member_url, expected_status_code=http_client.NO_CONTENT)

    def load_player_lobby(self):
        response = self.get(self.endpoints["lobbies"], expected_status_code=http_client.OK)
        self._extract_lobby(response.json())

    def get_lobby_member(self, player_id: typing.Optional[int] = None):
        if not player_id:
            player_id = self.player_id
        return next((member for member in self.lobby["members"] if member["player_id"] == player_id), None)

    def _extract_lobby(self, lobby: dict):
        self.lobby = lobby
        self.lobby_id = lobby["lobby_id"]
        self.lobby_url = lobby["lobby_url"]
        self.lobby_members_url = lobby["lobby_members_url"]
        self.lobby_member_url = lobby["lobby_member_url"]

    def _assert_error(self, response, expected_description=None):
        response_json = response.json()

        self.assertIn("error", response_json)
        self.assertIsInstance(response_json["error"], dict)
        self.assertIn("description" ,response_json["error"])

        if expected_description:
            self.assertEqual(response_json["error"]["description"], expected_description)

"""
Lobby API
"""

class TestLobbies(BaseCloudkitTest):
    def test_lobbies(self):
        self.make_player()
        self.assertIn("lobbies", self.endpoints)

    def test_my_lobby(self):
        with patch.object(lobbies, "get_player_lobby", return_value=MOCK_LOBBY):
            self.make_player()
            self.assertIn("my_lobby", self.endpoints)
            self.assertIn("my_lobby_members", self.endpoints)
            self.assertIn("my_lobby_member", self.endpoints)


# /lobbies
class TestLobbiesAPI(_BaseLobbyTest):
    # Get
    def test_get_api(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        with patch.object(lobbies, "get_player_lobby", return_value=MOCK_LOBBY) as get_player_lobby_mock:
            # Valid - not starting
            response = self.get(lobbies_url, expected_status_code=http_client.OK)
            response_json = response.json()

            self.assertIn("lobby_url", response_json)
            self.assertIn("lobby_members_url", response_json)
            self.assertIn("lobby_member_url", response_json)

            self.assertIn("members", response_json)
            for member in response_json["members"]:
                self.assertIn("lobby_member_url", member)

            # Valid - starting
            starting_lobby = copy.deepcopy(MOCK_LOBBY)
            starting_lobby["status"] = "starting"
            starting_lobby["placement_id"] = "something"
            get_player_lobby_mock.return_value = starting_lobby

            response = self.get(lobbies_url, expected_status_code=http_client.OK)

            self.assertIn("lobby_match_placement_url", response.json())

            # Not found
            get_player_lobby_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.get(lobbies_url, expected_status_code=http_client.NOT_FOUND)

            self._assert_error(response, expected_description=MOCK_ERROR)

            # Unauthorized
            get_player_lobby_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.get(lobbies_url, expected_status_code=http_client.UNAUTHORIZED)

            self._assert_error(response, expected_description=MOCK_ERROR)

    # Post
    def test_post_api(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]
        post_data = {
            "team_capacity": 4,
            "team_names": ["1", "2"],
        }

        # Invalid schema
        self.post(lobbies_url, data={}, expected_status_code=http_client.UNPROCESSABLE_ENTITY)

        with patch.object(lobbies, "create_lobby", return_value=MOCK_LOBBY) as create_lobby_mock:
            # Valid
            response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.CREATED)
            response_json = response.json()

            self.assertIn("lobby_url", response_json)
            self.assertIn("lobby_members_url", response_json)
            self.assertIn("lobby_member_url", response_json)

            self.assertIn("members", response_json)
            for member in response_json["members"]:
                self.assertIn("lobby_member_url", member)

            # Invalid data
            create_lobby_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response, expected_description=MOCK_ERROR)

# /lobbies/<lobby_id>
class TestLobbyAPI(_BaseLobbyTest):
    # Get
    def test_get_api(self):
        self.make_player()
        lobby_url = self.endpoints["lobbies"] + "123456"

        with patch.object(lobbies, "get_player_lobby", return_value=MOCK_LOBBY) as get_player_lobby_mock:
            # Valid
            response = self.get(lobby_url, expected_status_code=http_client.OK)
            response_json = response.json()

            self.assertIn("lobby_url", response_json)
            self.assertIn("lobby_members_url", response_json)
            self.assertIn("lobby_member_url", response_json)

            self.assertIn("members", response_json)
            for member in response_json["members"]:
                self.assertIn("lobby_member_url", member)

            # Not found
            get_player_lobby_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.get(lobby_url, expected_status_code=http_client.NOT_FOUND)

            self._assert_error(response, expected_description=MOCK_ERROR)

            # Unauthorized
            get_player_lobby_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.get(lobby_url, expected_status_code=http_client.UNAUTHORIZED)

            self._assert_error(response, expected_description=MOCK_ERROR)

    # Patch
    def test_patch_api(self):
        self.make_player()
        lobby_url = self.endpoints["lobbies"] + "123456"

        with patch.object(lobbies, "update_lobby") as update_lobby_mock:
            # Valid
            response = self.patch(lobby_url, data={}, expected_status_code=http_client.NO_CONTENT)

            self.assertEqual(response.text, "")

            # Not found
            update_lobby_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.patch(lobby_url, expected_status_code=http_client.NOT_FOUND)

            self._assert_error(response, expected_description=MOCK_ERROR)

            # Invalid data
            update_lobby_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.patch(lobby_url, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response, expected_description=MOCK_ERROR)

            # Unauthorized
            update_lobby_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.patch(lobby_url, expected_status_code=http_client.UNAUTHORIZED)

            self._assert_error(response, expected_description=MOCK_ERROR)

    # Delete
    def test_delete_api(self):
        self.make_player()
        lobby_url = self.endpoints["lobbies"] + "123456"

        with patch.object(lobbies, "delete_lobby") as update_lobby_mock:
            # Valid
            response = self.delete(lobby_url, data={}, expected_status_code=http_client.NO_CONTENT)

            self.assertEqual(response.text, "")

            # Not found
            update_lobby_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.delete(lobby_url, expected_status_code=http_client.NO_CONTENT)

            self.assertEqual(response.text, "")

            # Invalid data
            update_lobby_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.delete(lobby_url, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response, expected_description=MOCK_ERROR)

# /lobbies/<lobby_id>/members
class TestLobbyMembersAPI(_BaseLobbyTest):
    # Post
    def test_post_api(self):
        self.make_player()
        lobby_members_url = self.endpoints["lobbies"] + "123456/members"

        with patch.object(lobbies, "join_lobby", return_value=MOCK_LOBBY) as join_lobby_mock:
            # Valid
            response = self.post(lobby_members_url, expected_status_code=http_client.CREATED)
            response_json = response.json()

            self.assertIn("lobby_url", response_json)
            self.assertIn("lobby_members_url", response_json)
            self.assertIn("lobby_member_url", response_json)

            self.assertIn("members", response_json)
            for member in response_json["members"]:
                self.assertIn("lobby_member_url", member)

            # Not found
            join_lobby_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.post(lobby_members_url, expected_status_code=http_client.NOT_FOUND)

            self._assert_error(response, expected_description=MOCK_ERROR)

            # Invalid data
            join_lobby_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.post(lobby_members_url, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response, expected_description=MOCK_ERROR)

# /lobbies/<lobby_id>/members/<member_id>
class TestLobbyMemberAPI(_BaseLobbyTest):
    # Put
    def test_put_api(self):
        self.make_player()
        lobby_member_url = self.endpoints["lobbies"] + "123456/members/1337"

        with patch.object(lobbies, "update_lobby_member", return_value=MOCK_LOBBY) as update_lobby_member_mock:
            # Valid
            response = self.put(lobby_member_url, expected_status_code=http_client.NO_CONTENT)

            self.assertEqual(response.text, "")

            # Not found
            update_lobby_member_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.put(lobby_member_url, expected_status_code=http_client.NOT_FOUND)

            self._assert_error(response, expected_description=MOCK_ERROR)

            # Invalid data
            update_lobby_member_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.put(lobby_member_url, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response, expected_description=MOCK_ERROR)

    # Delete
    def test_delete_api(self):
        self.make_player()

        # Leave lobby
        with patch.object(lobbies, "leave_lobby", return_value=MOCK_LOBBY) as leave_lobby_mock:
            my_lobby_member_url = self.endpoints["lobbies"] + f"123456/members/{self.player_id}"

            # Valid
            response = self.delete(my_lobby_member_url, expected_status_code=http_client.NO_CONTENT)

            self.assertEqual(response.text, "")

            # Not found
            leave_lobby_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.delete(my_lobby_member_url, expected_status_code=http_client.NOT_FOUND)

            self._assert_error(response, expected_description=MOCK_ERROR)

            # Invalid data
            leave_lobby_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.delete(my_lobby_member_url, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response, expected_description=MOCK_ERROR)

        # Kick member
        with patch.object(lobbies, "kick_member") as kick_member_mock:
            lobby_member_url = self.endpoints["lobbies"] + f"123456/members/1337"

            # Valid
            response = self.delete(lobby_member_url, expected_status_code=http_client.NO_CONTENT)

            self.assertEqual(response.text, "")

            # Not found
            kick_member_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.delete(lobby_member_url, expected_status_code=http_client.NOT_FOUND)

            self._assert_error(response, expected_description=MOCK_ERROR)

            # Invalid data
            kick_member_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.delete(lobby_member_url, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response, expected_description=MOCK_ERROR)

"""
Lobby implementation
"""

class LobbiesTest(_BaseLobbyTest):
    # Get lobby

    def test_get_player_lobby(self):
        self.make_player()
        self.create_lobby()

        # Get player lobby
        response = self.get(self.endpoints["lobbies"], expected_status_code=http_client.OK)
        get_lobby = response.json()

        self.assertDictEqual(self.lobby, get_lobby)
        self.assertIn("lobby_url", get_lobby)

        # Get specific lobby
        response = self.get(get_lobby["lobby_url"], expected_status_code=http_client.OK)
        get_specific_lobby = response.json()

        self.assertDictEqual(get_specific_lobby, get_lobby)

    def test_get_player_lobby_not_in_lobby(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        response = self.get(lobbies_url, expected_status_code=http_client.NOT_FOUND)

        self._assert_error(response)

    def test_get_player_lobby_not_in_specific_lobby(self):
        self.make_player()
        self.create_lobby()
        lobbies_url = self.endpoints["lobbies"]

        # Get bogus lobby
        response = self.get(lobbies_url + "nope", expected_status_code=http_client.UNAUTHORIZED)

        self._assert_error(response)

    def test_get_player_lobby_started_spectator(self):
        self.make_player()
        self.create_lobby()

        with patch.object(lobbies, "_LockedLobby", _MockLockedLobby) as mocked_lobby_lock:
            mocked_lobby = copy.deepcopy(self.lobby)
            mocked_lobby["status"] = "started"
            mocked_lobby["connection_string"] = "1.1.1.1:1337"
            mocked_lobby_lock.mocked_lobby = mocked_lobby

            self.load_player_lobby()

            self.assertIn("connection_options", self.lobby)
            self.assertEqual(self.lobby["connection_options"], "SpectatorOnly=1")

    def test_get_player_lobby_started_team_member(self):
        self.make_player()
        self.create_lobby()

        # Assign team
        self.put(self.lobby_member_url, data={"team_name": "1"}, expected_status_code=http_client.NO_CONTENT)
        self.load_player_lobby()

        with patch.object(lobbies, "_LockedLobby", _MockLockedLobby) as mocked_lobby_lock:
            mocked_lobby = copy.deepcopy(self.lobby)
            mocked_lobby["status"] = "started"
            mocked_lobby["connection_string"] = "1.1.1.1:1337"
            mocked_lobby_lock.mocked_lobby = mocked_lobby

            mocked_player_session_id = "PlayerSession=123456"
            with patch.object(lobbies, "_ensure_player_session", return_value=mocked_player_session_id):
                self.load_player_lobby()

                self.assertIn("connection_options", self.lobby)
                self.assertTrue(self.lobby["connection_options"].startswith("PlayerSessionId"))

    # Create lobby

    def test_create_lobby(self):
        self.make_player("Player #1")
        lobbies_url = self.endpoints["lobbies"]

        post_data = {
            "team_capacity": 4,
            "team_names": ["1", "2"],
            "lobby_name": "test lobby",
            "map_name": "test map",
            "custom_data": "whatevs",
        }

        self.create_lobby(post_data)

        # Create lobby
        self.post(lobbies_url, data=post_data, expected_status_code=http_client.CREATED)

        self.assertIn("lobby_url", self.lobby)
        self.assertIn("lobby_members_url", self.lobby)
        self.assertIn("lobby_member_url", self.lobby)

        self.assertEqual(self.lobby["team_capacity"], post_data["team_capacity"])
        self.assertEqual(self.lobby["team_names"], post_data["team_names"])
        self.assertEqual(self.lobby["lobby_name"], post_data["lobby_name"])
        self.assertEqual(self.lobby["map_name"], post_data["map_name"])
        self.assertEqual(self.lobby["custom_data"], post_data["custom_data"])
        self.assertEqual(len(self.lobby["members"]), 1)

        player_member = self.lobby["members"][0]
        self.assertIsNotNone(player_member, None)

        self.assertEqual(player_member["player_id"], self.player_id)
        self.assertEqual(player_member["player_name"], self.player_name)
        self.assertIsNone(player_member["team_name"])
        self.assertFalse(player_member["ready"])
        self.assertTrue(player_member["host"])
        self.assertIn("join_date", player_member)

    def test_create_lobby_while_in_a_party(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        post_data = {
            "team_capacity": 4,
            "team_names": ["1", "2"],
        }

        with patch.object(parties, "get_player_party", return_value=1):
            # Create lobby
            response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response)

    def test_create_lobby_while_matchmaking(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        post_data = {
            "team_capacity": 4,
            "team_names": ["1", "2"],
        }

        with patch.object(flexmatch, "get_player_ticket", return_value={"ticket_id": "bla", "Status": "QUEUED"}):
            # Create lobby
            response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response)

    def test_create_lobby_while_in_a_lobby(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        post_data = {
            "team_capacity": 4,
            "team_names": ["1", "2"],
        }

        # Create first lobby
        response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.CREATED)
        first_lobby = response.json()

        # Get player lobby
        response = self.get(lobbies_url, expected_status_code=http_client.OK)
        player_lobby = response.json()

        self.assertDictEqual(first_lobby, player_lobby)

        # Create second lobby
        response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.CREATED)
        second_lobby = response.json()

        # Lobbies should be different. Note: assertDictNotEqual doesn't exist, use == operator
        self.assertFalse(first_lobby == second_lobby)

        # Get player lobby
        response = self.get(lobbies_url, expected_status_code=http_client.OK)
        player_lobby = response.json()

        self.assertDictEqual(player_lobby, second_lobby)

    # Update lobby

    def test_update_lobby(self):
        self.make_player()
        self.create_lobby()

        # Empty update
        self.patch(self.lobby_url, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(self.lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertDictEqual(self.lobby, lobby)

        # Update only team capacity
        new_team_capacity = 8
        self.patch(self.lobby_url, data={"team_capacity": new_team_capacity}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(self.lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["team_capacity"], new_team_capacity)
        self.assertNotEqual(lobby["team_capacity"], self.lobby["team_capacity"])
        self.assertEqual(lobby["team_names"], self.lobby["team_names"])

        # Update only team names
        new_team_names = ["3", "4"]
        self.patch(self.lobby_url, data={"team_names": new_team_names}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(self.lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["team_names"], new_team_names)
        self.assertNotEqual(lobby["team_names"], self.lobby["team_names"])
        self.assertEqual(lobby["team_capacity"], new_team_capacity)

        # Update only team names
        new_team_names = ["3", "4"]
        self.patch(self.lobby_url, data={"team_names": new_team_names}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(self.lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["team_names"], new_team_names)
        self.assertNotEqual(lobby["team_names"], self.lobby["team_names"])
        self.assertEqual(lobby["team_capacity"], new_team_capacity)

        # Update only lobby name
        new_lobby_name = "New Lobby Name"
        self.patch(self.lobby_url, data={"lobby_name": new_lobby_name}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(self.lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["lobby_name"], new_lobby_name)
        self.assertNotEqual(lobby["lobby_name"], self.lobby["lobby_name"])
        self.assertEqual(lobby["team_capacity"], new_team_capacity)
        self.assertEqual(lobby["team_names"], new_team_names)

        # Update only map name
        new_map_name = "New Map Name"
        self.patch(self.lobby_url, data={"map_name": new_map_name}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(self.lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["map_name"], new_map_name)
        self.assertNotEqual(lobby["map_name"], self.lobby["map_name"])
        self.assertEqual(lobby["team_capacity"], new_team_capacity)
        self.assertEqual(lobby["team_names"], new_team_names)
        self.assertEqual(lobby["lobby_name"], new_lobby_name)

        # Update only custom data
        new_custom_data = "New Custom Data"
        self.patch(self.lobby_url, data={"custom_data": new_custom_data}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(self.lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["custom_data"], new_custom_data)
        self.assertNotEqual(lobby["custom_data"], self.lobby["custom_data"])
        self.assertEqual(lobby["team_capacity"], new_team_capacity)
        self.assertEqual(lobby["team_names"], new_team_names)
        self.assertEqual(lobby["lobby_name"], new_lobby_name)
        self.assertEqual(lobby["map_name"], new_map_name)

        # Update everything
        update_data = {
            "team_capacity": 12,
            "team_names": ["10", "20"],
            "lobby_name": "Some lobby name",
            "map_name": "Some map name",
            "custom_data": "Some custom data",
        }
        self.patch(self.lobby_url, data=update_data, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(self.lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["custom_data"], update_data["custom_data"])
        self.assertEqual(lobby["team_capacity"], update_data["team_capacity"])
        self.assertEqual(lobby["team_names"], update_data["team_names"])
        self.assertEqual(lobby["lobby_name"], update_data["lobby_name"])
        self.assertEqual(lobby["map_name"], update_data["map_name"])

    def test_update_lobby_not_in_the_lobby(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        # Update bogus lobby
        response = self.patch(lobbies_url + "123456", data={"team_capacity": 8}, expected_status_code=http_client.UNAUTHORIZED)

        self._assert_error(response)

    def test_update_lobby_not_host(self):
        self.make_player()
        self.create_lobby()

        # Switch players
        self.make_player()

        # Join lobby
        self.post(self.lobby_members_url, expected_status_code=http_client.CREATED)

        # Update attempt
        response = self.patch(self.lobby_url, data={"team_capacity": 8}, expected_status_code=http_client.UNAUTHORIZED)

        self._assert_error(response)

    def test_update_lobby_match_started(self):
        self.make_player()
        self.create_lobby()

        with patch.object(lobbies, "_lobby_match_initiated", return_value=True):
            # Update attempt
            response = self.patch(self.lobby_url, data={"team_capacity": 8}, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response)

    def test_update_lobby_team_over_capacity(self):
        """
        If the team capacity is reduced, then teams that are over capacity will kick members out of the team
        """
        self.make_player()
        self.create_lobby()

        # Assign team
        self.put(self.lobby_member_url, data={"team_name": "1"}, expected_status_code=http_client.NO_CONTENT)

        # Update team capacity to 0
        self.patch(self.lobby_url, data={"team_capacity": 0}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(self.lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertIsNone(lobby["members"][0]["team_name"])

    def test_update_lobby_team_becomes_invalid(self):
        """
        If a team is removed, kick members out of the team
        """
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]
        self.create_lobby()

        # Assign team
        self.put(self.lobby_member_url, data={"team_name": "1"}, expected_status_code=http_client.NO_CONTENT)

        # Update team names
        self.patch(self.lobby_url, data={"team_names": ["yes", "no"]}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(self.lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertIsNone(lobby["members"][0]["team_name"])

    def test_update_lobby_message_queue(self):
        self.auth("Player 1")
        self.create_lobby()

        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        self.auth("Player 1")

        # Empty update
        self.patch(self.lobby_url, expected_status_code=http_client.NO_CONTENT)

        # Assert message queue for player 1
        notification, _ = self.get_player_notification("lobby", "LobbyUpdated")
        self.assertIsNone(notification)

        # Assert message queue for player 2
        self.auth("Player 2")
        notification, _ = self.get_player_notification("lobby", "LobbyUpdated")
        self.assertIsNone(notification)

        self.auth("Player 1")

        # Update everything
        update_data = {
            "team_capacity": 12,
            "team_names": ["10", "20"],
            "lobby_name": "Some lobby name",
            "map_name": "Some map name",
            "custom_data": "Some custom data",
        }
        self.patch(self.lobby_url, data=update_data, expected_status_code=http_client.NO_CONTENT)

        self.load_player_lobby()

        # Assert message queue for player 1
        notification, _ = self.get_player_notification("lobby", "LobbyUpdated")
        notification_data = notification["data"]
        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["lobby_id"], self.lobby_id)
        self.assertEqual(notification_data["lobby_name"], self.lobby["lobby_name"])
        self.assertEqual(notification_data["map_name"], self.lobby["map_name"])
        self.assertEqual(notification_data["custom_data"], self.lobby["custom_data"])
        self.assertEqual(notification_data["team_names"], self.lobby["team_names"])
        self.assertEqual(notification_data["team_capacity"], self.lobby["team_capacity"])

        # Assert message queue for player 2
        self.auth("Player 2")
        self.load_player_lobby()
        notification, _ = self.get_player_notification("lobby", "LobbyUpdated")
        self.assertDictEqual(notification_data, notification["data"])

    # Delete lobby

    def test_delete_lobby(self):
        # Host creates lobby
        self.auth("Player 1")
        self.create_lobby()

        # Member joins lobby
        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        # Host deletes lobby
        self.auth("Player 1")
        self.delete_lobby()

        # Verify host no longer in lobby

        # Assert not in lobby
        response = self.get(self.endpoints["lobbies"], expected_status_code=http_client.NOT_FOUND)

        self._assert_error(response)

        # Assert lobby doesn't exist
        response = self.get(self.lobby_url, expected_status_code=http_client.NOT_FOUND)

        self._assert_error(response)

        # Assert message queue for player 1
        notification, _ = self.get_player_notification("lobby", "LobbyDeleted")
        self.assertIsNone(notification)  # Shouldn't have any notification since the player knows whether or not it succeeded
        # TODO: Brainstorm and figure out if this is the best approach

        # Assert member no longer in lobby

        self.auth("Player 2")

        # Assert not in lobby
        response = self.get(self.endpoints["lobbies"], expected_status_code=http_client.NOT_FOUND)

        self._assert_error(response)

        # Assert lobby doesn't exist
        response = self.get(self.lobby_url, expected_status_code=http_client.NOT_FOUND)

        self._assert_error(response)

        # Assert message queue for player 2
        notification, _ = self.get_player_notification("lobby", "LobbyDeleted")
        notification_data = notification["data"]

        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["lobby_id"], self.lobby_id)

    def test_delete_lobby_no_lobby(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        # Verify not in lobby
        self.get(lobbies_url, expected_status_code=http_client.NOT_FOUND)

        # Some bogus lobby id
        response = self.delete(lobbies_url + "123456", expected_status_code=http_client.UNAUTHORIZED)

        self._assert_error(response)

    def test_delete_lobby_not_host(self):
        self.make_player()
        self.create_lobby()

        # Switch players
        self.make_player()

        # Join lobby
        self.join_lobby(self.lobby_members_url)

        # Delete lobby while not host
        self.delete(self.lobby_url, expected_status_code=http_client.UNAUTHORIZED)

        # Verify still in lobby
        response = self.get(self.endpoints["lobbies"], expected_status_code=http_client.OK)

        self.assertDictEqual(self.lobby, response.json())

    def test_delete_lobby_not_in_lobby(self):
        self.make_player()
        self.create_lobby()
        lobbies_url = self.endpoints["lobbies"]

        # Delete some other lobby
        self.delete(lobbies_url + "123456", expected_status_code=http_client.UNAUTHORIZED)

        # Verify still in lobby
        response = self.get(lobbies_url, expected_status_code=http_client.OK)

        self.assertDictEqual(self.lobby, response.json())

    # Leave lobby

    def test_leave_lobby(self):
        # Host creates lobby
        self.auth("Player 1")
        self.create_lobby()

        left_player_id = self.player_id

        # Member joins lobby
        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        # Host leaves lobby
        self.auth("Player 1")
        self.load_player_lobby()

        self.assertEqual(len(self.lobby["members"]), 2)

        self.leave_lobby()

        # Assert host no longer in lobby

        # Assert not in lobby
        response = self.get(self.endpoints["lobbies"], expected_status_code=http_client.NOT_FOUND)

        self._assert_error(response)

        # Assert lobby doesn't exist for host
        response = self.get(self.lobby_url, expected_status_code=http_client.NOT_FOUND)

        self._assert_error(response)

        # Assert message queue for player 1
        notification, _ = self.get_player_notification("lobby", "LobbyMemberLeft")
        notification_data = notification["data"]

        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["lobby_id"], self.lobby_id)
        self.assertEqual(len(notification_data["members"]), 1)
        self.assertEqual(notification_data["left_player_id"], left_player_id)

        # Assert member is now lobby host

        self.auth("Player 2")
        self.load_player_lobby()

        self.assertEqual(len(self.lobby["members"]), 1)
        self.assertEqual(self.lobby["members"][0]["player_id"], self.player_id)
        self.assertTrue(self.lobby["members"][0]["host"])

        # Assert message queue for player 2
        notification, _ = self.get_player_notification("lobby", "LobbyMemberLeft")

        self.assertDictEqual(notification["data"], notification_data)

    def test_leave_lobby_no_lobby(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        # Verify not in lobby
        self.get(lobbies_url, expected_status_code=http_client.NOT_FOUND)

        # Some bogus lobby id
        response = self.delete(lobbies_url + f"123456/members/{self.player_id}", expected_status_code=http_client.UNAUTHORIZED)

        self._assert_error(response)

    def test_leave_lobby_not_in_lobby(self):
        self.make_player()
        self.create_lobby()
        lobbies_url = self.endpoints["lobbies"]

        # Leave some other lobby
        response = self.delete(lobbies_url + f"123456/members/{self.player_id}", expected_status_code=http_client.UNAUTHORIZED)

        self._assert_error(response)

        # Verify still in lobby
        response = self.get(lobbies_url, expected_status_code=http_client.OK)

        self.assertDictEqual(self.lobby, response.json())

    def test_leave_lobby_starting_before_leave_lock(self):
        self.make_player()
        self.create_lobby()

        with patch.object(lobbies, "_LockedLobby", _MockLockedLobby) as mocked_lobby_lock:
            mocked_lobby = copy.deepcopy(self.lobby)
            mocked_lobby["status"] = "starting"
            mocked_lobby["placement_date"] = datetime.datetime.utcnow().isoformat()
            mocked_lobby_lock.mocked_lobby = mocked_lobby

            response = self.delete(self.lobby_member_url, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response)

    def test_leave_lobby_starting_after_leave_lock(self):
        self.make_player()
        self.create_lobby()

        with patch.object(lobbies, "_LockedLobby", _MockLockedLobby) as mocked_lobby_lock:
            mocked_lobby = copy.deepcopy(self.lobby)
            mocked_lobby["status"] = "starting"
            mocked_lobby["placement_date"] = datetime.datetime.min.isoformat()
            mocked_lobby_lock.mocked_lobby = mocked_lobby

            self.delete(self.lobby_member_url, expected_status_code=http_client.NO_CONTENT)

    # Kick lobby member

    def test_kick_lobby_member(self):
        # Host creates lobby
        self.auth("Player 1")
        self.create_lobby()

        # Member joins lobby
        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        kicked_player_id = self.player_id

        lobby_member_url = self.lobby_member_url

        # Host kicks member
        self.auth("Player 1")
        self.load_player_lobby()

        self.assertEqual(len(self.lobby["members"]), 2)

        self.kick_lobby_member(lobby_member_url)
        self.load_player_lobby()

        self.assertEqual(len(self.lobby["members"]), 1)
        self.assertEqual(self.lobby["members"][0]["player_id"], self.player_id)
        self.assertTrue(self.lobby["members"][0]["host"])

        # Assert message queue for player 1
        notification, _ = self.get_player_notification("lobby", "LobbyMemberKicked")
        notification_data = notification["data"]

        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["lobby_id"], self.lobby_id)
        self.assertEqual(len(notification_data["members"]), len(self.lobby["members"]))
        self.assertEqual(notification_data["kicked_player_id"], kicked_player_id)

        # Verify member no longer in lobby

        self.auth("Player 2")

        # Verify not in lobby
        response = self.get(self.endpoints["lobbies"], expected_status_code=http_client.NOT_FOUND)

        self._assert_error(response)

        # Verify lobby doesn't exist for member
        response = self.get(self.lobby_url, expected_status_code=http_client.NOT_FOUND)

        self._assert_error(response)

        # Assert message queue for player 2
        notification, _ = self.get_player_notification("lobby", "LobbyMemberKicked")

        self.assertDictEqual(notification["data"], notification_data)

    def test_kick_lobby_member_different_lobbies(self):
        # Player 1 creates lobby
        self.auth("Player 1")
        self.create_lobby()

        # Player 2 joins lobby
        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        lobby_member_url = self.lobby_member_url

        # Player 2 creates lobby, leaving the lobby
        self.create_lobby()

        self.auth("Player 1")
        self.load_player_lobby()

        # Kick member who is now in another lobby
        response = self.delete(lobby_member_url, expected_status_code=http_client.BAD_REQUEST)

        self._assert_error(response)

    def test_kick_lobby_member_not_host(self):
        # Host creates lobby
        self.auth("Player 1")
        self.create_lobby()

        host_lobby_member_url = self.lobby_member_url

        # Member joins lobby
        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        self.assertEqual(len(self.lobby["members"]), 2)

        # Member attempts to kick host
        response = self.delete(host_lobby_member_url, expected_status_code=http_client.UNAUTHORIZED)

        self._assert_error(response)

        # Verify lobby is still intact
        self.load_player_lobby()

        self.assertEqual(len(self.lobby["members"]), 2)

    # Join lobby

    def test_join_lobby(self):
        self.auth("Player 1")
        self.create_lobby()

        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        # Verify get lobby returns joined lobby
        response = self.get(self.endpoints["lobbies"], expected_status_code=http_client.OK)

        self.assertDictEqual(self.lobby, response.json())

        self.assertEqual(len(self.lobby["members"]), 2)

        lobby_member = next((member for member in self.lobby["members"] if member["player_id"] == self.player_id), None)

        self.assertIsNotNone(lobby_member)
        self.assertFalse(lobby_member["host"])

        # Assert message queue for player 2
        notification, _ = self.get_player_notification("lobby", "LobbyMemberJoined")
        self.assertIsNone(notification)  # Shouldn't have any notification since the player knows whether or not it succeeded
        # TODO: Brainstorm and figure out if this is the best approach

        # Switch to player 1
        self.auth("Player 1")
        self.load_player_lobby()

        # Assert message queue for player 2
        notification, _ = self.get_player_notification("lobby", "LobbyMemberJoined")
        notification_data = notification["data"]

        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["lobby_id"], self.lobby_id)
        self.assertEqual(len(notification_data["members"]), len(self.lobby["members"]))

    def test_join_lobby_in_lobby(self):
        self.auth("Player 1")
        self.create_lobby()

        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        # Join lobby again
        self.join_lobby(self.lobby_members_url)

        self.assertEqual(len(self.lobby["members"]), 2)

        lobby_member = self.get_lobby_member()

        self.assertIsNotNone(lobby_member)
        self.assertFalse(lobby_member["host"])

    def test_join_lobby_in_another_lobby(self):
        self.auth("Player 1")
        self.create_lobby()

        old_lobby_id = self.lobby_id

        self.auth("Player 2")
        self.create_lobby()

        self.auth("Player 1")
        self.join_lobby(self.lobby_members_url)

        self.assertNotEqual(self.lobby_id, old_lobby_id)
        self.assertEqual(len(self.lobby["members"]), 2)

        lobby_member = self.get_lobby_member()
        self.assertIsNotNone(lobby_member)
        self.assertFalse(lobby_member["host"])

    def test_join_lobby_not_exists(self):
        self.make_player()

        response = self.post(self.endpoints["lobbies"] + "123456/members", expected_status_code=http_client.NOT_FOUND)

        self._assert_error(response)

    # Update lobby member

    def test_update_lobby_member(self):
        self.make_player()
        self.create_lobby()

        # Empty update
        self.put(self.lobby_member_url, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(self.lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertDictEqual(self.lobby, lobby)

        # Update only team name
        new_team_name = "1"
        self.put(self.lobby_member_url, data={"team_name": new_team_name}, expected_status_code=http_client.NO_CONTENT)

        self.load_player_lobby()
        lobby_member = self.get_lobby_member()

        self.assertEqual(lobby_member["team_name"], new_team_name)
        self.assertFalse(lobby_member["ready"])

        # Update only ready status
        self.put(self.lobby_member_url, data={"ready": True}, expected_status_code=http_client.NO_CONTENT)

        self.load_player_lobby()
        lobby_member = self.get_lobby_member()

        self.assertIsNone(lobby_member["team_name"])
        self.assertFalse(lobby_member["ready"]) # Can only be ready if you're in a team

        # Empty update
        self.put(self.lobby_member_url, expected_status_code=http_client.NO_CONTENT)

        self.load_player_lobby()
        lobby_member = self.get_lobby_member()

        self.assertIsNone(lobby_member["team_name"])
        self.assertFalse(lobby_member["ready"])

        # Update both team name ready status
        self.put(self.lobby_member_url, data={"team_name": new_team_name, "ready": True}, expected_status_code=http_client.NO_CONTENT)

        self.load_player_lobby()
        lobby_member = self.get_lobby_member()

        self.assertEqual(lobby_member["team_name"], new_team_name)
        self.assertFalse(lobby_member["ready"]) # Cannot join a team and set ready to true in same request

        # Update both team name ready status
        self.put(self.lobby_member_url, data={"team_name": new_team_name, "ready": True}, expected_status_code=http_client.NO_CONTENT)

        self.load_player_lobby()
        lobby_member = self.get_lobby_member()

        self.assertEqual(lobby_member["team_name"], new_team_name)
        self.assertTrue(lobby_member["ready"])

    def test_update_lobby_member_not_in_lobby(self):
        self.make_player()

        # Empty update
        response = self.put(self.endpoints["lobbies"] + f"123456/members/{self.player_id}", expected_status_code=http_client.UNAUTHORIZED)

        self._assert_error(response)

    def test_update_lobby_member_host(self):
        self.auth("Player 1")
        self.create_lobby()

        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        member_lobby_member_url = self.lobby_member_url
        member_player_id = self.player_id

        self.auth("Player 1")

        # Update other member
        new_team_name = "1"
        self.put(member_lobby_member_url, data={"team_name": new_team_name}, expected_status_code=http_client.NO_CONTENT)

        self.load_player_lobby()
        lobby_member = self.get_lobby_member(member_player_id)

        self.assertEqual(lobby_member["team_name"], new_team_name)

    def test_update_lobby_member_not_host(self):
        self.auth("Player 1")
        self.create_lobby()

        host_lobby_member_url = self.lobby_member_url
        host_player_id = self.player_id

        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        # Update other member
        new_team_name = "1"
        response = self.put(host_lobby_member_url, data={"team_name": new_team_name}, expected_status_code=http_client.UNAUTHORIZED)

        self._assert_error(response)

        self.load_player_lobby()
        host = self.get_lobby_member(host_player_id)

        self.assertIsNone(host["team_name"])

    def test_update_lobby_member_match_initiated(self):
        self.make_player()
        self.create_lobby()

        with patch.object(lobbies, "_lobby_match_initiated", return_value=True):
            # Empty update
            response = self.put(self.lobby_member_url, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response)

    def test_update_lobby_member_invalid_team(self):
        self.make_player()
        self.create_lobby()

        invalid_team_name = "bingo"
        response = self.put(self.lobby_member_url, data={"team_name": invalid_team_name}, expected_status_code=http_client.BAD_REQUEST)

        self._assert_error(response)

    def test_update_lobby_member_message_queue(self):
        self.auth("Player 1")
        self.create_lobby()

        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        self.auth("Player 1")

        # Empty update
        self.put(self.lobby_member_url, expected_status_code=http_client.NO_CONTENT)

        # Assert message queue for player 1
        notification, _ = self.get_player_notification("lobby", "LobbyUpdated")
        self.assertIsNone(notification)

        # Assert message queue for player 2
        self.auth("Player 2")
        notification, _ = self.get_player_notification("lobby", "LobbyUpdated")
        self.assertIsNone(notification)

        self.auth("Player 1")

        # Update only team name
        new_team_name = "1"
        self.put(self.lobby_member_url, data={"team_name": new_team_name}, expected_status_code=http_client.NO_CONTENT)

        self.load_player_lobby()

        # Assert message queue for player 1
        notification, _ = self.get_player_notification("lobby", "LobbyMemberUpdated")
        notification_data = notification["data"]

        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["lobby_id"], self.lobby_id)
        self.assertEqual(len(notification_data["members"]), len(self.lobby["members"]))

        # Assert message queue for player 2
        self.auth("Player 2")
        self.load_player_lobby()

        notification, _ = self.get_player_notification("lobby", "LobbyMemberUpdated")
        notification_data = notification["data"]

        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["lobby_id"], self.lobby_id)
        self.assertIn("members", notification_data)

class _MockLockedLobby(object):
    mocked_lobby = None

    def __init__(self, key):
        self._key = key

    @property
    def lobby(self):
        return self.mocked_lobby

    @lobby.setter
    def lobby(self, new_lobby):
        self.mocked_lobby = new_lobby

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
