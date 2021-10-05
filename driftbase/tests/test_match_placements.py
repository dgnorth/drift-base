import http.client as http_client
import typing
import copy

from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import match_placements, lobbies, flexmatch
from driftbase.tests import test_lobbies

MOCK_PLACEMENT = {
    "placement_id": "123456"
}

MOCK_ERROR = "Some error"

"""
Match Placements API
"""

class TestMatchPlacements(BaseCloudkitTest):
    def test_match_placements(self):
        self.make_player()
        self.assertIn("match_placements", self.endpoints)

    def test_my_match_placement(self):
        with patch.object(match_placements, "get_player_match_placement", return_value=MOCK_PLACEMENT):
            self.make_player()
            self.assertIn("my_match_placement", self.endpoints)

# /match-placements
class TestMatchPlacementsAPI(BaseCloudkitTest):
    # Get
    def test_get_api(self):
        self.make_player()
        match_placements_url = self.endpoints["match_placements"]

        with patch.object(match_placements, "get_player_match_placement", return_value=MOCK_PLACEMENT) as get_player_match_placement_mock:
            # Valid
            response = self.get(match_placements_url, expected_status_code=http_client.OK)

            self.assertIn("match_placement_url", response.json())

            # Not found
            get_player_match_placement_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.get(match_placements_url, expected_status_code=http_client.NOT_FOUND)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # Unauthorized
            get_player_match_placement_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.get(match_placements_url, expected_status_code=http_client.UNAUTHORIZED)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

    # Post
    def test_post_api(self):
        self.make_player()
        match_placements_url = self.endpoints["match_placements"]

        post_data = {
            "lobby_id": "123456"
        }

        with patch.object(match_placements, "start_lobby_match_placement", return_value=MOCK_PLACEMENT) as start_lobby_match_placement_mock:
            # Valid
            response = self.post(match_placements_url, data=post_data, expected_status_code=http_client.CREATED)

            self.assertIn("match_placement_url", response.json())

            # Invalid data
            start_lobby_match_placement_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.post(match_placements_url, data=post_data, expected_status_code=http_client.BAD_REQUEST)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # GameLift failure
            start_lobby_match_placement_mock.side_effect = flexmatch.GameliftClientException(MOCK_ERROR, "")

            response = self.post(match_placements_url, data=post_data, expected_status_code=http_client.INTERNAL_SERVER_ERROR)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

# /match-placements/<match_placement_id>
class TestMatchPlacementAPI(BaseCloudkitTest):
    # Get
    def test_get_api(self):
        self.make_player()
        match_placement_url = self.endpoints["match_placements"] + "123456"

        with patch.object(match_placements, "get_player_match_placement", return_value=MOCK_PLACEMENT) as start_lobby_match_placement_mock:
            # Valid
            response = self.get(match_placement_url, expected_status_code=http_client.OK)

            self.assertIn("match_placement_url", response.json())

            # Not found
            start_lobby_match_placement_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.get(match_placement_url, expected_status_code=http_client.NOT_FOUND)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # Unauthorized
            start_lobby_match_placement_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.get(match_placement_url, expected_status_code=http_client.UNAUTHORIZED)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

    # Delete
    def test_delete_api(self):
        self.make_player()
        match_placement_url = self.endpoints["match_placements"] + "123456"

        with patch.object(match_placements, "stop_player_match_placement", return_value=MOCK_PLACEMENT) as stop_player_match_placement:
            # Valid
            response = self.delete(match_placement_url, expected_status_code=http_client.NO_CONTENT)

            self.assertEqual(response.text, "")

            # Not found
            stop_player_match_placement.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.delete(match_placement_url, expected_status_code=http_client.NO_CONTENT)

            self.assertEqual(response.text, "")

            # Invalid data
            stop_player_match_placement.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.delete(match_placement_url, expected_status_code=http_client.BAD_REQUEST)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # Unauthorized
            stop_player_match_placement.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.delete(match_placement_url, expected_status_code=http_client.UNAUTHORIZED)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

            # GameLift failure
            stop_player_match_placement.side_effect = flexmatch.GameliftClientException(MOCK_ERROR, "")

            response = self.delete(match_placement_url, expected_status_code=http_client.INTERNAL_SERVER_ERROR)

            self.assertDictEqual(response.json(), {"message": MOCK_ERROR})

"""
Match placement implementation
"""

class _BaseMatchPlacementTest(test_lobbies._BaseLobbyTest):
    match_placement = None
    match_placement_id = None
    match_placement_url = None

    def create_match_placement(self, match_placement_data: typing.Optional[dict] = None):
        if not match_placement_data:
            lobby_id = self.lobby_id or "123456"

            match_placement_data = {
                "lobby_id": lobby_id,
            }

        with patch.object(flexmatch, "get_player_latency_averages", return_value={}):
            with patch.object(flexmatch, "start_game_session_placement", return_value=MOCK_PLACEMENT):
                response = self.post(self.endpoints["match_placements"], data=match_placement_data, expected_status_code=http_client.CREATED)
                self._extract_match_placement(response.json())

    def delete_match_placement(self):
        with patch.object(flexmatch, "stop_game_session_placement", return_value={}):
            self.delete(self.match_placement_url, expected_status_code=http_client.NO_CONTENT)

    def load_player_match_placement(self):
        response = self.get(self.endpoints["match_placements"], expected_status_code=http_client.OK)
        self._extract_match_placement(response.json())

    def _extract_match_placement(self, match_placement: dict):
        self.match_placement = match_placement
        self.match_placement_id = match_placement["placement_id"]
        self.match_placement_url = match_placement["match_placement_url"]

class MatchPlacementsTest(_BaseMatchPlacementTest):
    # Get match placement

    def test_get_player_match_placement(self):
        self.make_player()
        self.create_lobby()
        self.create_match_placement()

        # Get player match placement
        response = self.get(self.endpoints["match_placements"], expected_status_code=http_client.OK)
        get_match_placement = response.json()

        self.assertDictEqual(self.match_placement, get_match_placement)
        self.assertIn("match_placement_url", get_match_placement)

        # Get specific match placement
        response = self.get(get_match_placement["match_placement_url"], expected_status_code=http_client.OK)
        get_specific_match_placement = response.json()

        self.assertDictEqual(get_specific_match_placement, get_match_placement)

    def test_get_match_placement_not_found(self):
        self.make_player()

        response = self.get(self.endpoints["match_placements"], expected_status_code=http_client.NOT_FOUND)

        self.assertIn("message", response.json())

    def test_get_match_placement_unauthorized(self):
        self.make_player()
        self.create_lobby()
        self.create_match_placement()

        # Bogus match placement
        response = self.get(self.endpoints["match_placements"] + "123456", expected_status_code=http_client.UNAUTHORIZED)

        self.assertIn("message", response.json())

    # Create match placement

    def test_create_match_placement(self):
        self.make_player()
        self.create_lobby()
        self.create_match_placement()

        response = self.get(self.endpoints["match_placements"], expected_status_code=http_client.OK)

        self.assertDictEqual(response.json(), self.match_placement)

    def test_create_match_placement_not_in_lobby(self):
        self.make_player()

        with patch.object(flexmatch, "get_player_latency_averages", return_value={}):
            with patch.object(flexmatch, "start_game_session_placement", return_value=MOCK_PLACEMENT):
                response = self.post(self.endpoints["match_placements"], data={"lobby_id": "123456"}, expected_status_code=http_client.UNAUTHORIZED)

                self.assertIn("message", response.json())

    def test_create_match_placement_not_lobby_host(self):
        self.auth("Player 1")
        self.create_lobby()

        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        with patch.object(flexmatch, "get_player_latency_averages", return_value={}):
            with patch.object(flexmatch, "start_game_session_placement", return_value=MOCK_PLACEMENT):
                response = self.post(self.endpoints["match_placements"], data={"lobby_id": self.lobby_id}, expected_status_code=http_client.BAD_REQUEST)

                self.assertIn("message", response.json())

    def test_create_match_placement_already_starting(self):
        self.make_player()
        self.create_lobby()

        with patch.object(match_placements, "_LockedLobby", test_lobbies._MockLockedLobby) as mocked_lobby_lock:
            mocked_lobby = copy.deepcopy(self.lobby)
            mocked_lobby["status"] = "starting"
            mocked_lobby_lock.mocked_lobby = mocked_lobby

            with patch.object(flexmatch, "get_player_latency_averages", return_value={}):
                with patch.object(flexmatch, "start_game_session_placement", return_value=MOCK_PLACEMENT):
                    response = self.post(self.endpoints["match_placements"], data={"lobby_id": self.lobby_id}, expected_status_code=http_client.BAD_REQUEST)

                    self.assertIn("message", response.json())

    # Delete match placement

    def test_delete_match_placement(self):
        self.make_player()
        self.create_lobby()
        self.create_match_placement()
        self.delete_match_placement()

        response = self.get(self.endpoints["match_placements"], expected_status_code=http_client.NOT_FOUND)

        self.assertIn("message", response.json())

    def test_delete_match_placement_unauthorized(self):
        self.make_player()

        # Bogus
        response = self.delete(self.endpoints["match_placements"] + "123456", expected_status_code=http_client.UNAUTHORIZED)

        self.assertIn("message", response.json())

    def test_delete_match_placement_not_pending(self):
        self.make_player()
        self.create_lobby()
        self.create_match_placement()

        with patch.object(match_placements, "_JsonLock", _MockJsonLock) as mocked_json_lock:
            mocked_match_placement = copy.deepcopy(self.match_placement)
            mocked_match_placement["status"] = "starting"
            mocked_json_lock.mocked_value = mocked_match_placement

            self.delete(self.match_placement_url, expected_status_code=http_client.BAD_REQUEST)

class _MockJsonLock(object):
    mocked_value = None

    def __init__(self, key):
        self._key = key

    @property
    def value(self):
        return self.mocked_value

    @value.setter
    def value(self, new_value):
        self.mocked_value = new_value

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
