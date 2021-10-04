import http.client as http_client
import copy
import typing

from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import flexmatch, lobbies, parties
from drift.utils import get_config
import uuid
import contextlib

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
class TestLobbiesAPI(BaseCloudkitTest):
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

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # Unauthorized
            get_player_lobby_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.get(lobbies_url, expected_status_code=http_client.UNAUTHORIZED)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

    # post
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

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

# /lobbies/<lobby_id>
class TestLobbyAPI(BaseCloudkitTest):
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

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # Unauthorized
            get_player_lobby_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.get(lobby_url, expected_status_code=http_client.UNAUTHORIZED)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

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

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # Invalid data
            update_lobby_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.patch(lobby_url, expected_status_code=http_client.BAD_REQUEST)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # Unauthorized
            update_lobby_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.patch(lobby_url, expected_status_code=http_client.UNAUTHORIZED)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

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

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

# /lobbies/<lobby_id>/members
class TestLobbyMembersAPI(BaseCloudkitTest):
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

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # Invalid data
            join_lobby_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.post(lobby_members_url, expected_status_code=http_client.BAD_REQUEST)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

# /lobbies/<lobby_id>/members/<member_id>
class TestLobbyMemberAPI(BaseCloudkitTest):
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

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # Invalid data
            update_lobby_member_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.put(lobby_member_url, expected_status_code=http_client.BAD_REQUEST)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

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

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # Invalid data
            leave_lobby_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.delete(my_lobby_member_url, expected_status_code=http_client.BAD_REQUEST)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

        # Kick member
        with patch.object(lobbies, "kick_member") as kick_member_mock:
            lobby_member_url = self.endpoints["lobbies"] + f"123456/members/1337"

            # Valid
            response = self.delete(my_lobby_member_url, expected_status_code=http_client.NO_CONTENT)

            self.assertEqual(response.text, "")

            # Not found
            kick_member_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.delete(lobby_member_url, expected_status_code=http_client.NOT_FOUND)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # Invalid data
            kick_member_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.delete(lobby_member_url, expected_status_code=http_client.BAD_REQUEST)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

"""
Lobby implementation
"""

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

    def join_lobby(self, lobby_url: str):
        response = self.post(lobby_url, expected_status_code=http_client.CREATED)
        self._extract_lobby(response.json())

    def leave_lobby(self):
        self.delete(self.lobby_url, expected_status_code=http_client.NO_CONTENT)

    def load_player_lobby(self):
        response = self.get(self.endpoints["lobbies"], expected_status_code=http_client.OK)
        self._extract_lobby(response.json())

    def _extract_lobby(self, lobby: dict):
        self.lobby = lobby
        self.lobby_id = lobby["lobby_id"]
        self.lobby_url = lobby["lobby_url"]
        self.lobby_members_url = lobby["lobby_members_url"]
        self.lobby_member_url = lobby["lobby_member_url"]

class LobbiesTest(BaseCloudkitTest):
    # Get lobby

    def test_get_player_lobby(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        post_data = {
            "team_capacity": 4,
            "team_names": ["1", "2"],
        }

        # Create lobby
        response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.CREATED)
        created_lobby = response.json()

        # Get player lobby
        response = self.get(lobbies_url, expected_status_code=http_client.OK)
        get_lobby = response.json()

        self.assertDictEqual(created_lobby, get_lobby)
        self.assertIn("lobby_url", get_lobby)

        # Get specific lobby
        response = self.get(get_lobby["lobby_url"], expected_status_code=http_client.OK)
        get_specific_lobby = response.json()

        self.assertDictEqual(get_specific_lobby, get_lobby)

    def test_get_player_lobby_not_in_lobby(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        response = self.get(lobbies_url, expected_status_code=http_client.NOT_FOUND)

        self.assertIn("message", response.json())

    def test_get_player_lobby_not_in_specific_lobby(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        post_data = {
            "team_capacity": 4,
            "team_names": ["1", "2"],
        }

        # Create lobby
        self.post(lobbies_url, data=post_data, expected_status_code=http_client.CREATED)

        # Get bogus lobby
        response = self.get(lobbies_url + "nope", expected_status_code=http_client.UNAUTHORIZED)

        self.assertIn("message", response.json())

    def test_get_player_lobby_started_spectator(self):
        # TODO: Figure out how to mock the lobby status to starting and a bogus connection string
        pass

    def test_get_player_lobby_started_team_member(self):
        # TODO: Figure out how to mock the lobby status to starting and a bogus connection string
        pass

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

        # Create lobby
        response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.CREATED)
        lobby = response.json()

        self.assertIn("lobby_url", lobby)
        self.assertIn("lobby_members_url", lobby)
        self.assertIn("lobby_member_url", lobby)

        self.assertEqual(lobby["team_capacity"], post_data["team_capacity"])
        self.assertEqual(lobby["team_names"], post_data["team_names"])
        self.assertEqual(lobby["lobby_name"], post_data["lobby_name"])
        self.assertEqual(lobby["map_name"], post_data["map_name"])
        self.assertEqual(lobby["custom_data"], post_data["custom_data"])
        self.assertEqual(len(lobby["members"]), 1)

        player_member = lobby["members"][0]
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

            self.assertIn("message", response.json())

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

            self.assertIn("message", response.json())

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
        lobbies_url = self.endpoints["lobbies"]

        post_data = {
            "team_capacity": 4,
            "team_names": ["1", "2"],
        }

        # Create lobby
        response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.CREATED)
        created_lobby = response.json()

        lobby_url = created_lobby["lobby_url"]

        # Empty update
        self.patch(lobby_url, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertDictEqual(created_lobby, lobby)

        # Update only team capacity
        new_team_capacity = 8
        self.patch(lobby_url, data={"team_capacity": new_team_capacity}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["team_capacity"], new_team_capacity)
        self.assertNotEqual(lobby["team_capacity"], created_lobby["team_capacity"])
        self.assertEqual(lobby["team_names"], created_lobby["team_names"])

        # Update only team names
        new_team_names = ["3", "4"]
        self.patch(lobby_url, data={"team_names": new_team_names}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["team_names"], new_team_names)
        self.assertNotEqual(lobby["team_names"], created_lobby["team_names"])
        self.assertEqual(lobby["team_capacity"], new_team_capacity)

        # Update only team names
        new_team_names = ["3", "4"]
        self.patch(lobby_url, data={"team_names": new_team_names}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["team_names"], new_team_names)
        self.assertNotEqual(lobby["team_names"], created_lobby["team_names"])
        self.assertEqual(lobby["team_capacity"], new_team_capacity)

        # Update only lobby name
        new_lobby_name = "New Lobby Name"
        self.patch(lobby_url, data={"lobby_name": new_lobby_name}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["lobby_name"], new_lobby_name)
        self.assertNotEqual(lobby["lobby_name"], created_lobby["lobby_name"])
        self.assertEqual(lobby["team_capacity"], new_team_capacity)
        self.assertEqual(lobby["team_names"], new_team_names)

        # Update only map name
        new_map_name = "New Map Name"
        self.patch(lobby_url, data={"map_name": new_map_name}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["map_name"], new_map_name)
        self.assertNotEqual(lobby["map_name"], created_lobby["map_name"])
        self.assertEqual(lobby["team_capacity"], new_team_capacity)
        self.assertEqual(lobby["team_names"], new_team_names)
        self.assertEqual(lobby["lobby_name"], new_lobby_name)

        # Update only custom data
        new_custom_data = "New Custom Data"
        self.patch(lobby_url, data={"custom_data": new_custom_data}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertEqual(lobby["custom_data"], new_custom_data)
        self.assertNotEqual(lobby["custom_data"], created_lobby["custom_data"])
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
        self.patch(lobby_url, data=update_data, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(lobby_url, expected_status_code=http_client.OK)
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

        self.assertIn("message", response.json())

    def test_update_lobby_not_the_host(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        post_data = {
            "team_capacity": 4,
            "team_names": ["1", "2"],
        }

        # Create lobby
        response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.CREATED)
        lobby = response.json()

        # Switch players
        self.make_player()

        # Join lobby
        self.post(lobby["lobby_members_url"], expected_status_code=http_client.CREATED)

        # Update attempt
        response = self.patch(lobby["lobby_url"], data={"team_capacity": 8}, expected_status_code=http_client.BAD_REQUEST)

        self.assertIn("message", response.json())

    def test_update_lobby_match_started(self):
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        post_data = {
            "team_capacity": 4,
            "team_names": ["1", "2"],
        }

        # Create lobby
        response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.CREATED)
        lobby = response.json()

        with patch.object(lobbies, "_lobby_match_initiated", return_value=True):
            # Update attempt
            response = self.patch(lobby["lobby_url"], data={"team_capacity": 8}, expected_status_code=http_client.BAD_REQUEST)

            self.assertIn("message", response.json())

    def test_update_lobby_team_over_capacity(self):
        """
        If the team capacity is reduced, then teams that are over capacity will kick members out of the team
        """
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        post_data = {
            "team_capacity": 4,
            "team_names": ["1", "2"],
        }

        # Create lobby
        response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.CREATED)
        lobby = response.json()
        lobby_url = lobby["lobby_url"]

        # Assign team
        self.put(lobby["lobby_member_url"], data={"team_name": "1"}, expected_status_code=http_client.NO_CONTENT)

        # Update team capacity to 0
        self.patch(lobby_url, data={"team_capacity": 0}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertIsNone(lobby["members"][0]["team_name"])

    def test_update_lobby_team_becomes_invalid(self):
        """
        If a team is removed, kick members out of the team
        """
        self.make_player()
        lobbies_url = self.endpoints["lobbies"]

        post_data = {
            "team_capacity": 4,
            "team_names": ["1", "2"],
        }

        # Create lobby
        response = self.post(lobbies_url, data=post_data, expected_status_code=http_client.CREATED)
        lobby = response.json()
        lobby_url = lobby["lobby_url"]

        # Assign team
        self.put(lobby["lobby_member_url"], data={"team_name": "1"}, expected_status_code=http_client.NO_CONTENT)

        # Update team names
        self.patch(lobby_url, data={"team_names": ["yes", "no"]}, expected_status_code=http_client.NO_CONTENT)

        # Get lobby
        response = self.get(lobby_url, expected_status_code=http_client.OK)
        lobby = response.json()

        self.assertIsNone(lobby["members"][0]["team_name"])
