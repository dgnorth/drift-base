import http.client as http_client
import typing
import copy

from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import match_placements, lobbies, flexmatch
from tests import test_lobbies

MOCK_PLACEMENT = {
    "placement_id": "123456"
}

MOCK_GAME_SESSIONS = {
   "GameSessions": [
      {
         "CreationTime": "number",
         "CreatorId": "string",
         "CurrentPlayerSessionCount": "number",
         "DnsName": "string",
         "FleetArn": "string",
         "FleetId": "string",
         "GameProperties": [
            {
               "Key": "string",
               "Value": "string"
            }
         ],
         "GameSessionData": "string",
         "GameSessionId": "string",
         "IpAddress": "string",
         "Location": "string",
         "MatchmakerData": "string",
         "MaximumPlayerSessionCount": "number",
         "Name": "string",
         "PlayerSessionCreationPolicy": "string",
         "Port": "number",
         "Status": "string",
         "StatusReason": "string",
         "TerminationTime": "number"
      }
   ],
   "NextToken": "string"
}

MOCK_PLAYER_SESSIONS = {
   "NextToken": "string",
   "PlayerSessions": [
      {
         "CreationTime": "number",
         "DnsName": "string",
         "FleetArn": "string",
         "FleetId": "string",
         "GameSessionId": "string",
         "IpAddress": "string",
         "PlayerData": "string",
         "PlayerId": "string",
         "PlayerSessionId": "string",
         "Port": "number",
         "Status": "string",
         "TerminationTime": "number"
      }
   ]
}

MOCK_PLAYER_SESSION = {
   "PlayerSession": {
      "CreationTime": "",
      "DnsName": "string",
      "FleetArn": "string",
      "FleetId": "string",
      "GameSessionId": "string",
      "IpAddress": "string",
      "PlayerData": "string",
      "PlayerId": "string",
      "PlayerSessionId": "string",
      "Port": "7777",
      "Status": "string",
      "TerminationTime": ""
   }
}

MOCK_ERROR = "Some error"


class _BaseMatchPlacementTest(test_lobbies._BaseLobbyTest):
    match_placement = None
    match_placement_id = None
    match_placement_url = None

    def create_match_placement(self, match_placement_data: typing.Optional[dict] = None):
        if not match_placement_data:
            lobby_id = self.lobby_id or "123456"

            match_placement_data = {
                "queue": "some queue",
                "lobby_id": lobby_id,
            }

        with patch.object(flexmatch, "get_player_latency_averages", return_value={}):
            with patch.object(flexmatch, "start_game_session_placement", return_value=MOCK_PLACEMENT):
                with patch.object(flexmatch, "stop_game_session_placement", return_value=MOCK_PLACEMENT):
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


"""
Match Placements API
"""


class TestMatchPlacements(BaseCloudkitTest):
    def test_match_placements(self):
        self.make_player()
        self.assertIn("match_placements", self.endpoints)


# /match-placements
class TestMatchPlacementsAPI(_BaseMatchPlacementTest):
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

            self._assert_error(response, expected_description=MOCK_ERROR)

            # Unauthorized
            get_player_match_placement_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.get(match_placements_url, expected_status_code=http_client.UNAUTHORIZED)

            self._assert_error(response, expected_description=MOCK_ERROR)

    # Post
    def test_post_api(self):
        self.make_player()
        match_placements_url = self.endpoints["match_placements"]

        # Lobby

        post_data = {
            "queue": "yup",
            "lobby_id": "123456",
        }

        with patch.object(match_placements, "start_lobby_match_placement", return_value=MOCK_PLACEMENT) as start_lobby_match_placement_mock:
            # Valid
            response = self.post(match_placements_url, data=post_data, expected_status_code=http_client.CREATED)

            self.assertIn("match_placement_url", response.json())

            # Invalid data
            start_lobby_match_placement_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.post(match_placements_url, data=post_data, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response, expected_description=MOCK_ERROR)

            # GameLift failure
            start_lobby_match_placement_mock.side_effect = flexmatch.GameliftClientException(MOCK_ERROR, "")

            response = self.post(match_placements_url, data=post_data, expected_status_code=http_client.INTERNAL_SERVER_ERROR)

            self._assert_error(response, expected_description=MOCK_ERROR)

        # Custom

        post_data = {
            "queue": "yup",
            "identifier": "123456",
            "map_name": "map",
            "max_players": 2,
            "custom_data": "{\"foo\": \"bar\"}",
        }

        with patch.object(match_placements, "start_match_placement", return_value=MOCK_PLACEMENT) as start_match_placement_mock:
            # Valid
            response = self.post(match_placements_url, data=post_data, expected_status_code=http_client.CREATED)

            self.assertIn("match_placement_url", response.json())

            # Invalid data
            start_match_placement_mock.side_effect = lobbies.InvalidRequestException(MOCK_ERROR)

            response = self.post(match_placements_url, data=post_data, expected_status_code=http_client.BAD_REQUEST)

            self._assert_error(response, expected_description=MOCK_ERROR)

            # GameLift failure
            start_match_placement_mock.side_effect = flexmatch.GameliftClientException(MOCK_ERROR, "")

            response = self.post(match_placements_url, data=post_data, expected_status_code=http_client.INTERNAL_SERVER_ERROR)

            self._assert_error(response, expected_description=MOCK_ERROR)


# /match-placements/<match_placement_id>
class TestMatchPlacementAPI(_BaseMatchPlacementTest):
    # Get
    def test_get_api(self):
        self.make_player()
        match_placement_url = self.endpoints["match_placements"] + "123456"

        with patch.object(match_placements, "get_match_placement", return_value=MOCK_PLACEMENT) as start_lobby_match_placement_mock:
            # Valid
            response = self.get(match_placement_url, expected_status_code=http_client.OK)

            self.assertIn("match_placement_url", response.json())

            # Not found
            start_lobby_match_placement_mock.side_effect = lobbies.NotFoundException(MOCK_ERROR)

            response = self.get(match_placement_url, expected_status_code=http_client.NOT_FOUND)

            self._assert_error(response, expected_description=MOCK_ERROR)

            # Unauthorized
            start_lobby_match_placement_mock.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.get(match_placement_url, expected_status_code=http_client.UNAUTHORIZED)

            self._assert_error(response, expected_description=MOCK_ERROR)

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

            self._assert_error(response, expected_description=MOCK_ERROR)

            # Unauthorized
            stop_player_match_placement.side_effect = lobbies.UnauthorizedException(MOCK_ERROR)

            response = self.delete(match_placement_url, expected_status_code=http_client.UNAUTHORIZED)

            self._assert_error(response, expected_description=MOCK_ERROR)

            # GameLift failure
            stop_player_match_placement.side_effect = flexmatch.GameliftClientException(MOCK_ERROR, "")

            response = self.delete(match_placement_url, expected_status_code=http_client.INTERNAL_SERVER_ERROR)

            self._assert_error(response, expected_description=MOCK_ERROR)


"""
Match placement implementation
"""


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

        self._assert_error(response)

        self.create_lobby()
        self.create_match_placement()

        # Bogus match placement
        response = self.get(self.endpoints["match_placements"] + "123456",
                            expected_status_code=http_client.NOT_FOUND)
        self._assert_error(response)

    def test_get_match_placement_unauthorized(self):
        self.make_player()
        self.create_lobby()
        self.create_match_placement()
        match_placement_url = self.match_placement_url
        # Fetch first placement as another player who owns another placement
        self.make_player()
        self.lobby_id = None
        self.create_match_placement({
            "queue": "yup",
            "identifier": "123",
            "map_name": "map",
            "max_players": 2,
        })
        response = self.get(match_placement_url, expected_status_code=http_client.UNAUTHORIZED)

        self._assert_error(response)

    # Create match placement

    def test_create_lobby_match_placement(self):
        # Have player 1 create the lobby
        player_1_username = self.make_player()

        self.create_lobby()

        # Have player 2 join the lobby
        player_2_username = self.make_player()
        self.join_lobby(self.lobby_members_url)

        # Switch to player 1
        self.auth(player_1_username)

        # Create placement
        self.create_match_placement()

        # Get placement
        response = self.get(self.endpoints["match_placements"], expected_status_code=http_client.OK)

        self.assertDictEqual(response.json(), self.match_placement)

        # Assert message queue for player 1
        notification, _ = self.get_player_notification("lobby", "LobbyMatchStarting")
        self.assertIsNone(notification) # Shouldn't have any notification since the player knows whether or not it succeeded
        # TODO: Brainstorm and figure out if this is the best approach

        # Switch to player 2
        self.auth(player_2_username)

        # Assert message queue for player 2
        notification, _ = self.get_player_notification("lobby", "LobbyMatchStarting")
        notification_data = notification["data"]

        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["lobby_id"], self.lobby_id)
        self.assertEqual(notification_data["status"], "starting")

    def test_create_party_match_placement(self):
        # Create players
        player_1_username = self.make_player()
        player_1_id = self.player_id

        player_2_username = self.make_player()
        player_2_id = self.player_id

        self.auth(player_1_username)

        # Send party invite
        invite = self.post(self.endpoints["party_invites"], data={'player_id': player_2_id}, expected_status_code=http_client.CREATED).json()

        # Get invite
        self.auth(player_2_username)
        notification, _ = self.get_player_notification("party_notification", "invite")

        # Accept the invite
        accept = self.patch(notification["invite_url"], data={"inviter_id": player_1_id}).json()

        # Switch to player 1
        self.auth(player_1_username)

        # Create placement
        self.create_match_placement({
            "queue": "yup",
            "identifier": "123",
            "map_name": "map",
            "max_players": 2,
        })

        # Get placement
        response = self.get(self.endpoints["match_placements"], expected_status_code=http_client.OK)

        self.assertDictEqual(response.json(), self.match_placement)

        # Assert message queue for player 1
        notification, _ = self.get_player_notification("match_placements", "MatchPlacementIssued")
        self.assertIsNone(notification) # Shouldn't have any notification since the player knows whether or not it succeeded
        # TODO: Brainstorm and figure out if this is the best approach

        # Switch to player 2
        self.auth(player_2_username)

        # Assert message queue for player 2
        notification, _ = self.get_player_notification("match_placements", "MatchPlacementIssued")
        notification_data = notification["data"]

        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["placement_id"], self.match_placement_id)

    def test_create_match_placement(self):
        self.make_player()

        # Create placement
        self.create_match_placement({
            "queue": "yup",
            "identifier": "123",
            "map_name": "map",
            "max_players": 2,
        })

        # Get placement
        response = self.get(self.endpoints["match_placements"], expected_status_code=http_client.OK)

        self.assertDictEqual(response.json(), self.match_placement)

        # Assert message queue for player 1
        notification, _ = self.get_player_notification("match_placements", "MatchPlacementIssued")
        self.assertIsNone(notification)  # Shouldn't have any notification since the player knows whether it succeeded
        # TODO: Brainstorm and figure out if this is the best approach

    def test_create_public_match_placement(self):
        self.make_player()

        # Create placement
        self.create_match_placement({
            "queue": "yup",
            "identifier": "123",
            "map_name": "map",
            "max_players": 2,
            "is_public": True,
        })

        # Get placement
        response = self.get(self.endpoints["match_placements"], expected_status_code=http_client.OK)
        placement = response.json()

        self.assertDictEqual(placement, self.match_placement)
        placement_url = placement["match_placement_url"]
        # Fetch as another player
        self.make_player()
        placement = self.get(placement_url, expected_status_code=http_client.OK).json()
        self.assertDictEqual(placement, self.match_placement)

    def test_join_active_public_match_placement(self):
        self.make_player()
        self.create_match_placement({
            "queue": "yup",
            "identifier": "12345",
            "map_name": "map",
            "max_players": 2,
            "is_public": True,
        })
        player_1_id = self.player_id

        # Make the placement be fulfilled
        event = copy.deepcopy(MOCK_GAMELIFT_QUEUE_EVENT)
        event["detail"]["placementId"] = self.match_placement_id
        event["detail"]["placedPlayerSessions"] = [
            {
                "playerId": str(player_1_id),
                "playerSessionId": "psess-3defcd9c-6953-577e-5e03-fffffe9a948a"
            }
        ]
        with self.as_bearer_token_user("flexmatch_event"):
            self.put(self.endpoints["flexmatch_queue"], data=event, expected_status_code=http_client.OK)

        # Join as another player
        self.make_player()
        game_sessions = copy.deepcopy(MOCK_GAME_SESSIONS)
        game_sessions["GameSessions"][0]["Status"] = "ACTIVE"
        with patch.object(flexmatch, "describe_game_sessions", return_value=game_sessions):
            player_sessions = copy.deepcopy(MOCK_PLAYER_SESSIONS)
            player_sessions["PlayerSessions"][0]["PlayerId"] = str(player_1_id)
            player_sessions["PlayerSessions"][0]["Status"] = "RESERVED"
            with patch.object(flexmatch, "describe_player_sessions", return_value=player_sessions):
                with patch.object(flexmatch, "create_player_session", return_value=MOCK_PLAYER_SESSION):
                    response = self.post(self.match_placement_url, expected_status_code=http_client.CREATED).json()
        self.assertDictEqual(response, MOCK_PLAYER_SESSION["PlayerSession"])
        notification, _ = self.get_player_notification("match_placements", "MatchPlacementFulfilled")
        notification_data = notification["data"]
        self.assertIsInstance(notification_data, dict)
        self.assertIn("connection_string", notification_data)
        self.assertIn("connection_options", notification_data)

    def test_create_match_placement_not_in_lobby(self):
        self.make_player()

        post_data = {
            "queue": "yup",
            "lobby_id": "123456",
        }

        with patch.object(flexmatch, "get_player_latency_averages", return_value={}):
            with patch.object(flexmatch, "start_game_session_placement", return_value=MOCK_PLACEMENT):
                response = self.post(self.endpoints["match_placements"], data=post_data,
                                     expected_status_code=http_client.BAD_REQUEST)

                self._assert_error(response)

    def test_create_match_placement_not_lobby_host(self):
        self.auth("Player 1")
        self.create_lobby()

        self.auth("Player 2")
        self.join_lobby(self.lobby_members_url)

        post_data = {
            "queue": "yup",
            "lobby_id": self.lobby_id,
        }

        with patch.object(flexmatch, "get_player_latency_averages", return_value={}):
            with patch.object(flexmatch, "start_game_session_placement", return_value=MOCK_PLACEMENT):
                response = self.post(self.endpoints["match_placements"], data=post_data, expected_status_code=http_client.UNAUTHORIZED)

                self._assert_error(response)

    def test_create_match_placement_already_starting(self):
        self.make_player()
        self.create_lobby()

        post_data = {
            "queue": "yup",
            "lobby_id": self.lobby_id,
        }

        with patch.object(match_placements, "JsonLock", test_lobbies._MockJsonLock) as mocked_lobby_lock:
            mocked_lobby = copy.deepcopy(self.lobby)
            mocked_lobby["status"] = "starting"
            mocked_lobby_lock.mocked_value = mocked_lobby

            with patch.object(flexmatch, "get_player_latency_averages", return_value={}):
                with patch.object(flexmatch, "start_game_session_placement", return_value=MOCK_PLACEMENT):
                    response = self.post(self.endpoints["match_placements"], data=post_data, expected_status_code=http_client.BAD_REQUEST)

                    self._assert_error(response)

    # Delete match placement

    def test_delete_match_placement(self):
        self.make_player()
        self.create_lobby()
        self.create_match_placement()
        self.delete_match_placement()

        response = self.get(self.endpoints["match_placements"], expected_status_code=http_client.NOT_FOUND)

        self._assert_error(response)

    def test_delete_match_placement_unauthorized(self):
        self.make_player()

        # Bogus
        response = self.delete(self.endpoints["match_placements"] + "123456", expected_status_code=http_client.UNAUTHORIZED)

        self._assert_error(response)

    def test_delete_match_placement_not_pending(self):
        self.make_player()
        self.create_lobby()
        self.create_match_placement()

        with patch.object(match_placements, "JsonLock", test_lobbies._MockJsonLock) as mocked_json_lock:
            mocked_match_placement = copy.deepcopy(self.match_placement)
            mocked_match_placement["status"] = "starting"
            mocked_json_lock.mocked_value = mocked_match_placement

            self.delete(self.match_placement_url, expected_status_code=http_client.BAD_REQUEST)

    # GameLift queue events

    def test_match_placement_queue_event_fulfilled(self):
        player_username = self.make_player()
        self.create_lobby()
        self.create_match_placement()

        # Publish the queue event
        with self.as_bearer_token_user("flexmatch_event"):
            event = copy.deepcopy(MOCK_GAMELIFT_QUEUE_EVENT)
            event["detail"]["placementId"] = self.match_placement_id
            self.put(self.endpoints["flexmatch_queue"], data=event, expected_status_code=http_client.OK)

        # Re-auth
        self.auth(player_username)

        # Assert lobby, maybe move this somehow to lobby tests?
        self.load_player_lobby()
        self.assertIn("connection_string", self.lobby)
        self.assertIsNotNone(self.lobby["start_date"])
        self.assertEqual(self.lobby["status"], "started")

        # Assert match placement
        self.load_player_match_placement()
        self.assertEqual(self.match_placement["status"], "completed")

        # Game session ARN isn't in the response schema. Probably a good thing since the client doesn't need it
        # self.assertIn("game_session_arn", self.match_placement)

        # Assert message queue
        notification, _ = self.get_player_notification("lobby", "LobbyMatchStarted")
        notification_data = notification["data"]

        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["lobby_id"], self.lobby_id)
        self.assertEqual(notification_data["status"], "started")
        self.assertIn("connection_string", notification_data)
        self.assertIn("connection_options", notification_data)

    def test_match_placement_queue_event_cancelled(self):
        player_username = self.make_player()
        self.create_lobby()
        self.create_match_placement()

        # Publish the queue event
        with self.as_bearer_token_user("flexmatch_event"):
            event = copy.deepcopy(MOCK_GAMELIFT_QUEUE_EVENT)
            event["detail"]["placementId"] = self.match_placement_id
            event["detail"]["type"] = "PlacementCancelled"
            self.put(self.endpoints["flexmatch_queue"], data=event, expected_status_code=http_client.OK)

        # Re-auth
        self.auth(player_username)

        # Assert lobby, maybe move this somehow to lobby tests?
        self.load_player_lobby()
        self.assertNotIn("connection_string", self.lobby)
        self.assertIsNone(self.lobby["start_date"])
        self.assertEqual(self.lobby["status"], "cancelled")

        # Assert match placement
        self.load_player_match_placement()
        self.assertEqual(self.match_placement["status"], "cancelled")

        # Assert message queue
        notification, _ = self.get_player_notification("lobby", "LobbyMatchCancelled")
        notification_data = notification["data"]

        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["lobby_id"], self.lobby_id)
        self.assertEqual(notification_data["status"], "cancelled")

    def test_match_placement_queue_event_timed_out(self):
        player_username = self.make_player()
        self.create_lobby()
        self.create_match_placement()

        # Publish the queue event
        with self.as_bearer_token_user("flexmatch_event"):
            event = copy.deepcopy(MOCK_GAMELIFT_QUEUE_EVENT)
            event["detail"]["placementId"] = self.match_placement_id
            event["detail"]["type"] = "PlacementTimedOut"
            self.put(self.endpoints["flexmatch_queue"], data=event, expected_status_code=http_client.OK)

        # Re-auth
        self.auth(player_username)

        # Assert lobby, maybe move this somehow to lobby tests?
        self.load_player_lobby()
        self.assertNotIn("connection_string", self.lobby)
        self.assertIsNone(self.lobby["start_date"])
        self.assertEqual(self.lobby["status"], "timed_out")

        # Assert match placement
        self.load_player_match_placement()
        self.assertEqual(self.match_placement["status"], "timed_out")

        # Assert message queue
        notification, _ = self.get_player_notification("lobby", "LobbyMatchTimedOut")
        notification_data = notification["data"]

        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["lobby_id"], self.lobby_id)
        self.assertEqual(notification_data["status"], "timed_out")

    def test_match_placement_queue_event_failed(self):
        player_username = self.make_player()
        self.create_lobby()
        self.create_match_placement()

        # Publish the queue event
        with self.as_bearer_token_user("flexmatch_event"):
            event = copy.deepcopy(MOCK_GAMELIFT_QUEUE_EVENT)
            event["detail"]["placementId"] = self.match_placement_id
            event["detail"]["type"] = "PlacementFailed"
            self.put(self.endpoints["flexmatch_queue"], data=event, expected_status_code=http_client.OK)

        # Re-auth
        self.auth(player_username)

        # Assert lobby, maybe move this somehow to lobby tests?
        self.load_player_lobby()
        self.assertNotIn("connection_string", self.lobby)
        self.assertIsNone(self.lobby["start_date"])
        self.assertEqual(self.lobby["status"], "failed")

        # Assert match placement
        self.load_player_match_placement()
        self.assertEqual(self.match_placement["status"], "failed")

        # Assert message queue
        notification, _ = self.get_player_notification("lobby", "LobbyMatchFailed")
        notification_data = notification["data"]

        self.assertIsInstance(notification_data, dict)
        self.assertEqual(notification_data["lobby_id"], self.lobby_id)
        self.assertEqual(notification_data["status"], "failed")

    def test_match_placement_queue_event_match_placement_not_found(self):
        player_username = self.make_player()
        self.create_lobby()
        self.create_match_placement()
        self.load_player_lobby()

        old_lobby = copy.deepcopy(self.lobby)
        old_match_placement = copy.deepcopy(self.match_placement)

        # Publish the queue event
        with self.as_bearer_token_user("flexmatch_event"):
            event = copy.deepcopy(MOCK_GAMELIFT_QUEUE_EVENT)
            self.put(self.endpoints["flexmatch_queue"], data=event, expected_status_code=http_client.OK)

        # Re-auth
        self.auth(player_username)
        self.load_player_match_placement()
        self.load_player_lobby()

        self.assertDictEqual(self.lobby, old_lobby)
        self.assertDictEqual(self.match_placement, old_match_placement)

    def test_match_placement_queue_event_unknown_type(self):
        player_username = self.make_player()
        self.create_lobby()
        self.create_match_placement()
        self.load_player_lobby()

        old_lobby = copy.deepcopy(self.lobby)
        old_match_placement = copy.deepcopy(self.match_placement)

        # Publish the queue event
        with self.as_bearer_token_user("flexmatch_event"):
            event = copy.deepcopy(MOCK_GAMELIFT_QUEUE_EVENT)
            event["detail"]["type"] = "42"

            # AWS EventBridge always expects a 200 response. It will retry the event if it gets a 500.
            self.put(self.endpoints["flexmatch_queue"], data=event, expected_status_code=http_client.OK)

        # Re-auth
        self.auth(player_username)
        self.load_player_match_placement()
        self.load_player_lobby()

        self.assertDictEqual(self.lobby, old_lobby)
        self.assertDictEqual(self.match_placement, old_match_placement)


MOCK_GAMELIFT_QUEUE_EVENT = {
   "version": "0",
   "id": "93111702-4e98-8e1c-07d4-740ee173c4c0",
   "detail-type": "GameLift Queue Placement Event",
   "source": "aws.gamelift",
   "account": "420691337",
   "time": "2021-10-06T09:50:55Z",
   "region": "eu-west-1",
   "resources": [
      "arn:aws:gamelift:eu-west-1:509899862212:gamesessionqueue/default"
   ],
   "detail": {
      "placementId": "1941b6ae-dd29-4605-b0df-8c5ac8d37663",
      "port": "1337",
      "gameSessionArn": "arn:aws:gamelift:eu-west-1::gamesession/fleet-938edf52-462b-465c-8e42-9856d9cc74b0/1941b6ae-dd29-4605-b0df-8c5ac8d37663",
      "ipAddress": "1.1.1.1",
      "placedPlayerSessions": [
         {
            "playerId": "1",
            "playerSessionId": "psess-3defcd9c-6953-577e-5e03-fffffe9a948a"
         },
         {
            "playerId": "2",
            "playerSessionId": "psess-3defcd9c-6953-577e-5e03-fffffe9afda7"
         }
      ],
      "customEventData": "Target-DriftDevStable-GameSessionQueue",
      "dnsName": "ec2-1-1-1-1.eu-west-1.compute.amazonaws.com",
      "startTime": "2021-10-06T09:50:46.923Z",
      "endTime": "2021-10-06T09:50:55.245Z",
      "type": "PlacementFulfilled",
      "gameSessionRegion": "eu-west-1"
   }
}
