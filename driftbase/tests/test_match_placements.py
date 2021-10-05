import http.client as http_client

from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import match_placements, lobbies, flexmatch
from drift.utils import get_config
import uuid
import contextlib

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
