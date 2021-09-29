import http.client as http_client
import copy

from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import flexmatch, lobbies
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

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

            # Unauthorized
            get_player_lobby_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.get(lobbies_url, expected_status_code=http_client.UNAUTHORIZED)

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

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

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

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

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

            # Unauthorized
            get_player_lobby_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.get(lobby_url, expected_status_code=http_client.UNAUTHORIZED)

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

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

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

            # Invalid data
            update_lobby_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.patch(lobby_url, expected_status_code=http_client.BAD_REQUEST)

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

            # Unauthorized
            update_lobby_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.patch(lobby_url, expected_status_code=http_client.UNAUTHORIZED)

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

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

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

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

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

            # Invalid data
            join_lobby_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.post(lobby_members_url, expected_status_code=http_client.BAD_REQUEST)

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

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

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

            # Invalid data
            update_lobby_member_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.put(lobby_member_url, expected_status_code=http_client.BAD_REQUEST)

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

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

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

            # Invalid data
            leave_lobby_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.delete(my_lobby_member_url, expected_status_code=http_client.BAD_REQUEST)

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

        # Kick member
        with patch.object(lobbies, "kick_member") as kick_member_mock:
            lobby_member_url = self.endpoints["lobbies"] + f"123456/members/1337"

            # Valid
            response = self.delete(my_lobby_member_url, expected_status_code=http_client.NO_CONTENT)

            self.assertEqual(response.text, "")

            # Not found
            kick_member_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.delete(lobby_member_url, expected_status_code=http_client.NOT_FOUND)

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})

            # Invalid data
            kick_member_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.delete(lobby_member_url, expected_status_code=http_client.BAD_REQUEST)

            self.assertDictEqual(response.json(), {"error": MOCK_ERROR})
