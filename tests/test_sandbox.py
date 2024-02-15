import datetime
import json
import threading
import http.client as http_client
import time
import unittest

from driftbase import flexmatch
from driftbase import sandbox
from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch

EVENTS_ROLE = "flexmatch_event"


class LockedGenerator:
    location_id = 0
    lock = threading.Lock()

    def __init__(self):
        pass

    def __iter__(self):
        return self

    def __next__(self):
        with self.lock:
            self.location_id += 1
            return self.location_id

location_id_gen = iter(LockedGenerator())

class SandboxTest(BaseCloudkitTest):

    @staticmethod
    def location_id():
        return next(location_id_gen)

    def test_access(self):
        self.auth()
        self.assertIn("sandbox", self.endpoints)
        self.get(self.endpoints["sandbox"], expected_status_code=http_client.FORBIDDEN)
        self.auth_service()
        self.get(self.endpoints["sandbox"], expected_status_code=http_client.OK)
        self.logout()
        self.get(self.endpoints["sandbox"], expected_status_code=http_client.UNAUTHORIZED)

    def test_put_new_placement(self):
        self.make_player()
        location_id = self.location_id()
        placement_id = f"SB-Experience-{location_id}"
        with patch.object(flexmatch, "start_game_session_placement", return_value={"placement_id": placement_id}):
            response = self.put(f"{self.endpoints['sandbox']}/{location_id}", expected_status_code=http_client.CREATED).json()
        self.assertIn(placement_id, response["placement_id"])
        self.assertTrue(response["placement_id"].endswith(placement_id))
        event = json.loads(MOCK_GAMELIFT_QUEUE_EVENT % dict(placement_id=placement_id, player_id=self.player_id,
                                                 event_type="PlacementFulfilled"))
        with patch.object(flexmatch, "_get_flexmatch_config_value",
                          return_value=f"arn:aws:iam::{event.get('account')}:role/dg-drift-flexmatch"):
            with self.as_bearer_token_user(EVENTS_ROLE):
                self.put(self.endpoints["flexmatch_queue"], data=event, expected_status_code=http_client.OK)
        notification, _ = self.get_player_notification("sandbox", "PlayerSessionReserved")
        data = notification['data']
        self.assertIn("game_session", data)
        self.assertIn("connection_info", data)


    #@unittest.skip
    def test_put_pending_placement(self):
        """NOTE:  This test is flaky as fuck since the threads may trample each other's auth headers"""
        # Create a placement but don't fulfill it
        self.make_player()
        location_id = self.location_id()
        placement_id = f"SB-Experience-{location_id}"
        with patch.object(flexmatch, "start_game_session_placement", return_value={"placement_id": placement_id}):
            response = self.put(f"{self.endpoints['sandbox']}/{location_id}", expected_status_code=http_client.CREATED).json()
        self.assertIn(placement_id, response["placement_id"])
        self.assertTrue(response["placement_id"].endswith(placement_id))

        # Try to put the same placement again in a separate thread
        thread_flag_result = dict(
            started = False,
            ended = False,
            result = None
        )
        def threaded_func(info_dict):
            game_sessions = MOCK_GAME_SESSIONS % dict(status="ACTIVE")
            with patch.object(flexmatch, "describe_game_sessions", return_value=json.loads(game_sessions)):
                player_sessions = MOCK_PLAYER_SESSIONS % dict(player_id=self.player_id, status="ACTIVE")
                with patch.object(flexmatch, "describe_player_sessions", return_value=json.loads(player_sessions)):
                    info_dict["started"] = datetime.datetime.utcnow() + datetime.timedelta(seconds=0.5) # Lie about when we started so that we can test the thread is blocked
                    try:
                        info_dict["result"] = self.put(f"{self.endpoints['sandbox']}/{location_id}",
                                            expected_status_code=http_client.CREATED).json()
                    except Exception as e:
                        print("Exception in thread: ", e)
                    finally:
                        info_dict["ended"] = datetime.datetime.utcnow()
        blocked_thread = threading.Thread(group=None, target=threaded_func, args=(thread_flag_result,))
        blocked_thread.start()
        # wait until thread starts and then check that the thread is blocked
        while thread_flag_result["started"] is False:
            time.sleep(0.01)
        self.assertTrue(blocked_thread.is_alive())  # if it ran and errored, or if it didn't block, catch it.
        if thread_flag_result["started"] > datetime.datetime.utcnow():
            time.sleep((thread_flag_result["started"] - datetime.datetime.utcnow()).seconds)

        # fulfill the placement
        time.sleep(0.2) # entering the ctxmgr too quickly after thread starts may trample the auth header of the thread
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.assertTrue(blocked_thread.is_alive())
            event = json.loads(MOCK_GAMELIFT_QUEUE_EVENT % dict(placement_id=placement_id, player_id=self.player_id,
                                                     event_type="PlacementFulfilled"))
            with patch.object(flexmatch, "_get_flexmatch_config_value",
                              return_value=f"arn:aws:iam::{event.get('account')}:role/dg-drift-flexmatch"):
                # patch the db-dipping call so that when thread unblocks, it won't recurse endlessly
                with patch.object(sandbox, "get_running_game_session",
                                  return_value="arn:aws:gamelift:eu-west-1::gamesession/fleet-938edf52-462b-465c-8e42-9856d9cc74b0/1941b6ae-dd29-4605-b0df-8c5ac8d37663"):
                    self.put(self.endpoints["flexmatch_queue"], data=event, expected_status_code=http_client.OK)
                    # yield to thread before un-patching
                    while thread_flag_result["ended"] is False:
                        time.sleep(0.1)
        blocked_thread.join()
        self.assertFalse(blocked_thread.is_alive())
        self.assertIsNotNone(thread_flag_result["result"])
        notification, _ = self.get_player_notification("sandbox", "PlayerSessionReserved")
        data = notification['data']
        self.assertIn("game_session", data)
        self.assertIn("connection_info", data)

    def test_failed_placement_posts_message_and_nukes_cache(self):
        username = self.make_player()
        location_id = self.location_id()
        placement_id = f"SB-Experience-{location_id}"
        event = json.loads(MOCK_GAMELIFT_QUEUE_EVENT % dict(placement_id=placement_id, player_id=self.player_id,
                                                 event_type="PlacementFailed"))
        with patch.object(flexmatch, "start_game_session_placement", return_value={"placement_id": placement_id}):
            response = self.put(f"{self.endpoints['sandbox']}/{location_id}",
                                expected_status_code=http_client.CREATED).json()
        self.assertIn(placement_id, response["placement_id"])
        self.assertTrue(response["placement_id"].endswith(placement_id))
        with patch.object(flexmatch, "_get_flexmatch_config_value",
                          return_value=f"arn:aws:iam::{event.get('account')}:role/dg-drift-flexmatch"):
            with self.as_bearer_token_user(EVENTS_ROLE):
                self.put(self.endpoints["flexmatch_queue"], data=event, expected_status_code=http_client.OK)
        # Re-auth
        self.auth(username)
        notification, _ = self.get_player_notification("sandbox", "SessionCreationFailed")
        self.assertIsNotNone(notification)
        # Check if still cached
        self.auth_service()
        placements = self.get(self.endpoints["sandbox"], expected_status_code=http_client.OK).json()
        self.assertIn("placements", placements)
        for placement in placements["placements"]:
            if placement.endswith(placement_id):
                self.fail(
                    f"Placement {placement_id} was not cleared from redis cached after failure message")

    def test_events_from_other_accounts_are_ignored(self):
        _ = self.make_player()
        location_id = self.location_id()
        placement_id = f"SB-Experience-{location_id}"
        wrong_account = "123456789012"
        event = json.loads(MOCK_GAMELIFT_QUEUE_EVENT % dict(placement_id=placement_id, player_id=self.player_id,
                                                 event_type="PlacementFailed"))
        with patch.object(flexmatch, "start_game_session_placement", return_value={"placement_id": placement_id}):
            response = self.put(f"{self.endpoints['sandbox']}/{location_id}",
                                expected_status_code=http_client.CREATED).json()
        self.assertIn(placement_id, response["placement_id"])
        self.assertTrue(response["placement_id"].endswith(placement_id))
        with self.as_bearer_token_user(EVENTS_ROLE):
            with patch.object(sandbox, "get_tenant_config_value",
                          return_value=f"arn:aws:iam::{wrong_account}:role/dg-drift-flexmatch"):
                self.put(self.endpoints["flexmatch_queue"], data=event, expected_status_code=http_client.OK)
        self.auth_service()
        placements = self.get(self.endpoints["sandbox"], expected_status_code=http_client.OK).json()
        self.assertIn("placements", placements)
        for placement in placements["placements"]:
            if placement.endswith(placement_id):
                break
        else:
            self.fail(f"Placement {placement_id} was wrongly nuked from cache after failure message from wrong account")


MOCK_GAMELIFT_QUEUE_EVENT = """{
   "version": "0",
   "detail-type": "GameLift Queue Placement Event",
   "account": "509899862212",
   "resources": [
      "arn:aws:gamelift:eu-west-1:509899862212:gamesessionqueue/default"
   ],
   "detail": {
      "placementId": "%(placement_id)s",
      "port": "1337",
      "gameSessionArn": "arn:aws:gamelift:eu-west-1::gamesession/fleet-938edf52-462b-465c-8e42-9856d9cc74b0/1941b6ae-dd29-4605-b0df-8c5ac8d37663",
      "ipAddress": "1.1.1.1",
      "placedPlayerSessions": [
         {
            "playerId": "%(player_id)s",
            "playerSessionId": "psess-3defcd9c-6953-577e-5e03-fffffe9a948a"
         }
      ],
      "customEventData": "Target-DriftDevStable-GameSessionQueue",
      "startTime": "2021-10-06T09:50:46.923Z",
      "endTime": "2021-10-06T09:50:55.245Z",
      "type": "%(event_type)s"
   }
}
"""

MOCK_GAME_SESSIONS = """{
   "GameSessions": [
      {
         "GameSessionId": "string",
         "IpAddress": "1.2.3.4",
         "Location": "string",
         "MatchmakerData": "string",
         "MaximumPlayerSessionCount": "number",
         "Name": "string",
         "PlayerSessionCreationPolicy": "string",
         "Port": "1234",
         "Status": "%(status)s",
         "StatusReason": "string",
         "TerminationTime": "number"
      }
   ],
   "NextToken": "string"
}"""

MOCK_PLAYER_SESSIONS = """{
   "NextToken": "string",
   "PlayerSessions": [
      {
         "IpAddress": "1.2.3.4",
         "PlayerData": "string",
         "PlayerId": "%(player_id)s",
         "PlayerSessionId": "string",
         "Port": "1234",
         "Status": "%(status)s",
         "TerminationTime": "number"
      }
   ]
}"""
