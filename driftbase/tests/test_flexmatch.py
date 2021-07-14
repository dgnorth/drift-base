import http.client as http_client
from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import flexmatch
from drift.utils import get_config
import uuid
import contextlib
import copy

REGION = "eu-west-1"


class TestFlexMatchPlayerAPI(BaseCloudkitTest):
    def test_patch_api(self):
        self.make_player()
        flexmatch_url = self.endpoints["flexmatch"]
        with patch.object(flexmatch, 'update_player_latency', return_value=None):
            with patch.object(flexmatch, 'get_player_latency_averages', return_value={}):
                self.patch(flexmatch_url, expected_status_code=http_client.UNPROCESSABLE_ENTITY)
                self.patch(flexmatch_url, data={'latency_ms': 123, "region": REGION}, expected_status_code=http_client.OK)

    def test_post_api(self):
        self.make_player()
        flexmatch_url = self.endpoints["flexmatch"]
        with patch.object(flexmatch, 'upsert_flexmatch_ticket', return_value={}):
            self.post(flexmatch_url, expected_status_code=http_client.UNPROCESSABLE_ENTITY)
            response = self.post(flexmatch_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK)
            self.assertDictEqual(response.json(), {})

    def test_get_api(self):
        self.make_player()
        flexmatch_url = self.endpoints["flexmatch"]
        with patch.object(flexmatch, 'get_player_ticket', return_value={}):
            response = self.get(flexmatch_url, expected_status_code=http_client.OK)
            self.assertDictEqual(response.json(), {})

    def test_delete_api(self):
        self.make_player()
        flexmatch_url = self.endpoints["flexmatch"]
        with patch.object(flexmatch, 'cancel_player_ticket', return_value={}):
            self.delete(flexmatch_url, expected_status_code=http_client.NO_CONTENT)


class _BaseFlexmatchTest(BaseCloudkitTest):
    def _create_party(self, party_size=2):
        if party_size < 2:
            raise RuntimeError(f"Cant have a party of {party_size}")
        # Create all the players
        info = []
        for i in range(party_size):
            name = self.make_player()
            info.append({"name": name, "id": self.player_id})
        # last player created gets to play host and invites the others
        host_id = self.player_id
        for member in info[:-1]:
            self.post(self.endpoints["party_invites"], data={'player_id': member["id"]}, expected_status_code=http_client.CREATED)

        # The others accept the invite
        for member in info[:-1]:
            self.auth(username=member["name"])
            notification, _ = self.get_player_notification("party_notification", "invite")
            self.patch(notification['invite_url'], data={'inviter_id': host_id}, expected_status_code=http_client.OK)
        return info

    def _initiate_matchmaking(self, user_name=None):
        if user_name is None:  # else we assume a user has authenticated
            user_name = self.make_player()

        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            ticket = self.post(self.endpoints["flexmatch"], data={"matchmaker": "unittest"},
                               expected_status_code=http_client.OK).json()
        return user_name, ticket

    @staticmethod
    def _get_event_details(ticket_id, player_info):
        if not isinstance(player_info, list):
            players = [player_info]
        else:
            players = player_info
        return {
            "type": "",
            "matchId": "0a3eb4aa-ecdb-4595-81a0-ad2b2d61bd05",
            "gameSessionInfo": {
                "ipAddress": None,
                "port": None,
                "players": players
            },
            "tickets": [{
                "ticketId": ticket_id,
                "players": players
            }]
        }

    @contextlib.contextmanager
    def _managed_bearer_token_user(self):
        # FIXME: this whole thing is pretty much a c/p from test_jwt; consolidate.
        self._access_key = str(uuid.uuid4())[:12]
        self._user_name = "testuser_{}".format(self._access_key[:4])
        self._role_name = "flexmatch_event"
        try:
            self._setup_service_user_with_bearer_token()
            self.headers["Authorization"] = f"Bearer {self._access_key}"
            yield
        finally:
            self._remove_service_user_with_bearer_token()
            del self.headers["Authorization"]

    def _setup_service_user_with_bearer_token(self):
        # FIXME: Might be cleaner to use patching instead of populating the actual config. The upside with using config
        #  is that it exposes the intended use case more clearly
        conf = get_config()
        ts = conf.table_store
        # setup access roles
        ts.get_table("access-roles").add({
            "role_name": self._role_name,
            "deployable_name": conf.deployable["deployable_name"]
        })
        # Setup a user with an access key
        ts.get_table("users").add({
            "user_name": self._user_name,
            "password": self._access_key,
            "access_key": self._access_key,
            "is_active": True,
            "is_role_admin": False,
            "is_service": True,
            "organization_name": conf.organization["organization_name"]
        })
        # Associate the bunch.
        ts.get_table("users-acl").add({
            "organization_name": conf.organization["organization_name"],
            "user_name": self._user_name,
            "role_name": self._role_name,
            "tenant_name": conf.tenant["tenant_name"]
        })

    def _remove_service_user_with_bearer_token(self):
        conf = get_config()
        ts = conf.table_store
        ts.get_table("users-acl").remove({
            "organization_name": conf.organization["organization_name"],
            "user_name": self._user_name,
            "role_name": self._role_name,
            "tenant_name": conf.tenant["tenant_name"]
        })
        ts.get_table("users").remove({
            "user_name": self._user_name,
            "access_key": self._access_key,
            "is_active": True,
            "is_role_admin": False,
            "is_service": True,
            "organization_name": conf.organization["organization_name"]
        })
        ts.get_table("access-roles").remove({
            "role_name": self._role_name,
            "deployable_name": conf.deployable["deployable_name"],
            "description": "a throwaway test role"
        })
        delattr(self, '_access_key')
        delattr(self, '_user_name')
        delattr(self, '_role_name')


class FlexMatchTest(_BaseFlexmatchTest):
    # NOTE TO SELF:  The idea behind splitting the api tests from this class was to be able to test the flexmatch
    # module functions separately from the rest endpoints.  I've got a mocked application context with a fake redis
    # setup stashed away, allowing code like
    # with _mocked_redis(self):
    #    for i, latency in enumerate(latencies):
    #        flexmatch.update_player_latency(self.player_id, "best-region", latency)
    #        average_by_region = flexmatch.get_player_latency_averages(self.player_id)
    # but I keep it stashed away until I can spend time digging into RedisCache in drift as it extends some redis
    # operations which conflict with the fake redis setup I made.
    # Until then, this goes through the endpoints.
    def test_update_latency_returns_correct_averages(self):
        self.make_player()
        flexmatch_url = self.endpoints["flexmatch"]
        latencies = [1.0, 2.0, 3.0, 4.0, 5.0, 10.7]
        expected_avg = [1, 1, 2, 3, 4, 6]  # We expect integers representing the average of the last 3 values
        for i, latency in enumerate(latencies):
            response = self.patch(flexmatch_url, data={'latency_ms': latency, "region": REGION}, expected_status_code=http_client.OK)
            self.assertEqual(response.json()[REGION], expected_avg[i])

    def test_start_matchmaking(self):
        _, ticket = self._initiate_matchmaking()
        self.assertTrue(ticket["Status"] == "QUEUED")

    def test_start_matchmaking_doesnt_modify_ticket_if_same_player_reissues_request(self):
        _, ticket = self._initiate_matchmaking()
        first_id = ticket["TicketId"]
        flexmatch_url = self.endpoints["flexmatch"]
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            second_id = self.post(flexmatch_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()["TicketId"]
        self.assertEqual(first_id, second_id)

    def test_start_matchmaking_creates_event(self):
        _, ticket = self._initiate_matchmaking()
        notification, message_number = self.get_player_notification("matchmaking", "MatchmakingStarted")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["event"] == "MatchmakingStarted")

    def test_matchmaking_includes_party_members(self):
        member, host = self._create_party()
        # Let member start matchmaking, host should be included in the ticket
        self.auth(member["name"])
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            response = self.post(self.endpoints["flexmatch"], data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
            players = response["Players"]
            self.assertEqual(len(players), 2)
            expected_players = {member["id"], host["id"]}
            response_players = {int(e["PlayerId"]) for e in players}
            self.assertSetEqual(response_players, expected_players)

    def test_start_matchmaking_creates_event_for_party_members(self):
        member, host = self._create_party()
        # Let member start matchmaking, host should be included in the ticket
        self.auth(member["name"])
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            response = self.post(self.endpoints["flexmatch"], data={"matchmaker": "unittest"},
                                 expected_status_code=http_client.OK).json()
        # Check if party host got the message
        self.auth(host["name"])
        notification, message_number = self.get_player_notification("matchmaking", "MatchmakingStarted")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["event"] == "MatchmakingStarted")

    def test_delete_ticket(self):
        player_name = self.make_player()
        flexmatch_url = self.endpoints["flexmatch"]
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            # delete without a ticket, expect NOT_FOUND
            self.delete(flexmatch_url, expected_status_code=http_client.NOT_FOUND)
            # start the matchmaking and then stop it.  Expect OK back
            response = self.post(flexmatch_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
            self.assertTrue(response["Status"] == "QUEUED")
            # Check that we have a stored ticket
            response = self.get(flexmatch_url, expected_status_code=http_client.OK)
            self.assertIn("TicketId", response.json())
            self.delete(flexmatch_url, expected_status_code=http_client.NO_CONTENT)
            # Check that the ticket is indeed gone
            response = self.get(flexmatch_url, expected_status_code=http_client.OK)
            self.assertDictEqual(response.json(), {})
            # Test that a ticket in 'matched' state doesn't get deleted
            response = self.post(flexmatch_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
            events_url = self.endpoints["flexmatch"] + "events"
            data = copy.copy(_matchmaking_event_template)
            details = self._get_event_details(response["TicketId"], {"playerId": str(self.player_id), "team": "winners"})
            details["type"] = "PotentialMatchCreated"
            details["acceptanceRequired"] = True
            details["acceptanceTimeout"] = 123
            data["detail"] = details
            with self._managed_bearer_token_user():
                self.put(events_url, data=data, expected_status_code=http_client.OK)
            self.auth(player_name)
            response = self.delete(flexmatch_url, expected_status_code=http_client.OK).json()
            self.assertEqual(response["Status"], "REQUIRES_ACCEPTANCE")

    def test_delete_ticket_clears_cached_ticket_on_invalid_request(self):
        player_name = self.make_player()
        flexmatch_url = self.endpoints["flexmatch"]

        def _stop_matchmaking_with_error_response(self, **kwargs):
            response = {
                'Error': {
                    'Message': 'Matchmaking ticket is in COMPLETED status and cannot be canceled.',
                    'Code': 'InvalidRequestException'
                },
                'ResponseMetadata': {
                    'RequestId': 'f96151ae-8b36-46f4-a287-b4c903286a59',
                    'HTTPStatusCode': 400,
                    'HTTPHeaders': {
                        'x-amzn-requestid': 'f96151ae-8b36-46f4-a287-b4c903286a59',
                        'content-type': 'application/x-amz-json-1.1',
                        'content-length': '114',
                        'date': 'Tue, 13 Jul 2021 14:04:11 GMT',
                        'connection': 'close'
                    },
                    'RetryAttempts': 0
                },
                'Message': 'Matchmaking ticket is in COMPLETED status and cannot be canceled.'
            }
            from botocore.exceptions import ClientError
            raise ClientError(response, "stop_matchmaking")

        with patch.object(MockGameLiftClient, 'stop_matchmaking', _stop_matchmaking_with_error_response):
            with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
                response = self.post(flexmatch_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
                self.assertTrue(response["Status"] == "QUEUED")
                # Check that we have a stored ticket
                response = self.get(flexmatch_url, expected_status_code=http_client.OK).json()
                self.assertIn("TicketId", response)
                # Attempt to delete
                self.delete(flexmatch_url, expected_status_code=http_client.NO_CONTENT)
                # Ticket should be cleared
                response = self.get(flexmatch_url, expected_status_code=http_client.OK).json()
                self.assertNotIn("TicketId", response)
                # And there should be a message waiting
                notification, _ = self.get_player_notification("matchmaking", "MatchmakingStopped")
                self.assertTrue(notification["event"] == "MatchmakingStopped")

    def test_party_member_can_delete_ticket(self):
        member, host = self._create_party()
        # Host starts matchmaking
        self.auth(host["name"])
        flexmatch_url = self.endpoints["flexmatch"]
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            response = self.post(flexmatch_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
            # member then cancels
            self.auth(member["name"])
            self.delete(flexmatch_url, expected_status_code=http_client.NO_CONTENT)

    def test_party_members_get_notified_if_ticket_is_cancelled(self):
        member, host = self._create_party()
        self.auth(member["name"])
        flexmatch_url = self.endpoints["flexmatch"]
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            response = self.post(flexmatch_url, data={"matchmaker": "unittest"}, expected_status_code=http_client.OK).json()
            # host then cancels
            self.auth(username=host["name"])
            self.delete(flexmatch_url, expected_status_code=http_client.NO_CONTENT)
            # host should have a notification
            notification, _ = self.get_player_notification("matchmaking", "MatchmakingStopped")
            self.assertIsInstance(notification, dict)
            self.assertTrue(notification["event"] == "MatchmakingStopped")
            # member should have a notification
            self.auth(username=member["name"])
            notification, _ = self.get_player_notification("matchmaking", "MatchmakingStopped")
            self.assertIsInstance(notification, dict)
            self.assertTrue(notification["event"] == "MatchmakingStopped")

    def test_party_members_get_success_event(self):
        member, host = self._create_party(2)
        _, ticket = self._initiate_matchmaking(host["name"])
        events_url = self.endpoints["flexmatch"] + "events"
        with self._managed_bearer_token_user():
            data = copy.copy(_matchmaking_event_template)
            details = self._get_event_details(ticket["TicketId"], [
                {"playerId": player["id"], "playerSessionId": f"bleble-{player['id']}-flefle"}
                for player in (member, host)])
            details["type"] = "MatchmakingSucceeded"
            details["gameSessionInfo"]["ipAddress"] = "1.2.3.4"
            details["gameSessionInfo"]["port"] = "7780"
            data["detail"] = details
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        for guy in (member, host):
            self.auth(guy["name"])
            notification, _ = self.get_player_notification("matchmaking", "MatchmakingSuccess")
            self.assertIsInstance(notification, dict)
            self.assertEqual(f"PlayerSessionId=bleble-{guy['id']}-flefle?PlayerId={guy['id']}", notification["data"]["options"])


class FlexMatchEventTest(_BaseFlexmatchTest):
    def test_searching_event(self):
        user_name, ticket = self._initiate_matchmaking()
        events_url = self.endpoints["flexmatch"] + "events"
        with self._managed_bearer_token_user():
            details = self._get_event_details(ticket["TicketId"], {"playerId": str(self.player_id)})
            details["type"] = "MatchmakingSearching"
            data = copy.copy(_matchmaking_event_template)
            data["detail"] = details
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['Status'], "SEARCHING")
        notification, _ = self.get_player_notification("matchmaking", "MatchmakingSearching")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["event"] == "MatchmakingSearching")

    def test_potential_match_event(self):
        user_name, ticket = self._initiate_matchmaking()
        events_url = self.endpoints["flexmatch"] + "events"
        acceptance_timeout = 123
        data = copy.copy(_matchmaking_event_template)
        details = self._get_event_details(ticket["TicketId"], {"playerId": str(self.player_id), "team": "winners"})
        details["type"] = "PotentialMatchCreated"
        details["acceptanceRequired"] = False
        details["acceptanceTimeout"] = acceptance_timeout
        data["detail"] = details
        with self._managed_bearer_token_user():
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        # Verify state
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['Status'], "PLACING")
        self.assertEqual(r['MatchId'], details["matchId"])
        # Verify notification sent
        notification, _ = self.get_player_notification("matchmaking", "PotentialMatchCreated")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["event"] == "PotentialMatchCreated")
        self.assertSetEqual(set(notification["data"]["winners"]), {self.player_id})
        self.assertEqual(notification["data"]["match_id"], details["matchId"])
        # Test with acceptanceRequired as True
        with self._managed_bearer_token_user():
            data["detail"]["acceptanceRequired"] = True
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['Status'], "REQUIRES_ACCEPTANCE")
        self.assertEqual(r['MatchId'], details["matchId"])
        # Verify notification sent
        notification, _ = self.get_player_notification("matchmaking", "PotentialMatchCreated")
        self.assertTrue(notification["event"] == "PotentialMatchCreated")
        self.assertSetEqual(set(notification["data"]["winners"]), {self.player_id})
        self.assertTrue(notification["data"]["acceptance_required"])
        self.assertEqual(notification["data"]["acceptance_timeout"], acceptance_timeout)

    def test_matchmaking_succeeded(self):
        connection_ip = "1.2.3.4"
        connection_port = "7780"
        player_session_id = "psess-6f45ca3a-5522-4f6c-9293-7df04dc12cb6"
        user_name, ticket = self._initiate_matchmaking()
        events_url = self.endpoints["flexmatch"] + "events"
        data = copy.copy(_matchmaking_event_template)
        details = self._get_event_details(ticket["TicketId"], {"playerId": str(self.player_id), "playerSessionId": player_session_id})
        details["type"] = "MatchmakingSucceeded"
        details["gameSessionInfo"]["ipAddress"] = connection_ip
        details["gameSessionInfo"]["port"] = connection_port
        data["detail"] = details
        with self._managed_bearer_token_user():
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['Status'], "COMPLETED")
        self.assertTrue("GameSessionConnectionInfo" in r)
        session_info = r["GameSessionConnectionInfo"]
        self.assertEqual(session_info["ipAddress"], connection_ip)
        self.assertEqual(session_info["port"], connection_port)
        # Verify notification sent
        notification, _ = self.get_player_notification("matchmaking", "MatchmakingSuccess")
        self.assertTrue(notification["event"] == "MatchmakingSuccess")
        connection_data = notification["data"]
        self.assertEqual(connection_data["connection_string"], f"{connection_ip}:{connection_port}")
        self.assertEqual(connection_data["options"], f"PlayerSessionId={player_session_id}?PlayerId={self.player_id}")

    def test_matchmaking_cancelled(self):
        user_name, ticket = self._initiate_matchmaking()
        events_url = self.endpoints["flexmatch"] + "events"
        data = copy.copy(_matchmaking_event_template)
        details = self._get_event_details(ticket["TicketId"], {"playerId": str(self.player_id)})
        details["type"] = "MatchmakingCancelled"
        data["detail"] = details
        with self._managed_bearer_token_user():
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['Status'], "CANCELLED")
        notification, _ = self.get_player_notification("matchmaking", "MatchmakingCancelled")
        self.assertIsInstance(notification, dict)

    def test_matchmaking_backfill_ticket_cancel_updates_player_ticket(self):
        user_name, ticket = self._initiate_matchmaking()
        events_url = self.endpoints["flexmatch"] + "events"
        # Set ticket to 'COMPLETED'
        data = copy.copy(_matchmaking_event_template)
        details = self._get_event_details(ticket["TicketId"], {"playerId": str(self.player_id), "playerSessionId": "psess-123123", "team": "winners"})
        details["type"] = "MatchmakingSucceeded"
        details["gameSessionInfo"]["ipAddress"] = "1.2.3.4"
        details["gameSessionInfo"]["port"] = "1234"
        data["detail"] = details
        with self._managed_bearer_token_user():
            self.put(events_url, data=data, expected_status_code=http_client.OK)
            real_ticket_id = ticket["TicketId"]
            backfill_ticket_id = chr(ord(real_ticket_id[0]) + 1)
            # The backfill tickets are issued by the battleserver with a ticketId drift doesn't track
            details["tickets"][0]["ticketId"] = backfill_ticket_id
            details["type"] = "MatchmakingCancelled"
            data["detail"] = details
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['Status'], "MATCH_COMPLETE")

    def test_accept_match_event(self):
        user_name, ticket = self._initiate_matchmaking()
        events_url = self.endpoints["flexmatch"] + "events"
        data = copy.copy(_matchmaking_event_template)
        details = self._get_event_details(ticket["TicketId"], {"playerId": str(self.player_id), "team": "winners"})
        details["type"] = "PotentialMatchCreated"
        details["acceptanceRequired"] = True
        details["acceptanceTimeout"] = 10
        data["detail"] = details
        with self._managed_bearer_token_user():
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        # Verify state
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['Status'], "REQUIRES_ACCEPTANCE")
        # Verify notification sent
        notification, _ = self.get_player_notification("matchmaking", "PotentialMatchCreated")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["data"]["acceptance_required"])
        # Accept the match
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            self.put(self.endpoints["flexmatch"], data={"match_id": details["matchId"], "acceptance": True}, expected_status_code=http_client.OK)
        # emit flexmatch event
        details["type"] = "AcceptMatch"
        details["tickets"][0]["players"][0]["accepted"] = True
        details["gameSessionInfo"]["players"][0]["accepted"] = True
        data["detail"] = details
        with self._managed_bearer_token_user():
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['MatchId'], details["matchId"])
        self.assertEqual(r['Status'], "REQUIRES_ACCEPTANCE")
        self.assertTrue(r['Players'][0]['Accepted'])

    def test_accept_match_completed_event(self):
        user_name, ticket = self._initiate_matchmaking()
        events_url = self.endpoints["flexmatch"] + "events"
        data = copy.copy(_matchmaking_event_template)
        details = self._get_event_details(ticket["TicketId"], {"playerId": str(self.player_id), "team": "winners"})
        details["type"] = "PotentialMatchCreated"
        details["acceptanceRequired"] = True
        details["acceptanceTimeout"] = 10
        data["detail"] = details
        with self._managed_bearer_token_user():
            self.put(events_url, data=data, expected_status_code=http_client.OK)
            details["type"] = "AcceptMatchCompleted"
            details["acceptance"] = "Accepted"
            data["detail"] = details
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['MatchStatus'], "ACCEPTED")
        with self._managed_bearer_token_user():
            data["detail"]["acceptance"] = "TimedOut"
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['MatchStatus'], "TIMEDOUT")
        with self._managed_bearer_token_user():
            data["detail"]["acceptance"] = "Rejected"
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['MatchStatus'], "REJECTED")

    def test_matchmaking_timed_out_event(self):
        user_name, ticket = self._initiate_matchmaking()
        events_url = self.endpoints["flexmatch"] + "events"
        data = copy.copy(_matchmaking_event_template)
        details = self._get_event_details(ticket["TicketId"], {"playerId": str(self.player_id), "team": "winners"})
        details["type"] = "MatchmakingTimedOut"
        data["detail"] = details
        with self._managed_bearer_token_user():
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['Status'], "TIMED_OUT")
        notification, _ = self.get_player_notification("matchmaking", "MatchmakingFailed")
        self.assertIsInstance(notification, dict)
        self.assertEqual(notification["data"]["reason"], "TimeOut")

    def test_matchmaking_failed_event(self):
        user_name, ticket = self._initiate_matchmaking()
        events_url = self.endpoints["flexmatch"] + "events"
        data = copy.copy(_matchmaking_event_template)
        details = self._get_event_details(ticket["TicketId"], {"playerId": str(self.player_id), "team": "winners"})
        details["type"] = "MatchmakingFailed"
        details["reason"] = "UnitTestInducedFailure"
        data["detail"] = details
        with self._managed_bearer_token_user():
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(self.endpoints["flexmatch"], expected_status_code=http_client.OK).json()
        self.assertEqual(r['Status'], "FAILED")
        notification, _ = self.get_player_notification("matchmaking", "MatchmakingFailed")
        self.assertIsInstance(notification, dict)
        self.assertEqual(notification["data"]["reason"], details["reason"])


class MockGameLiftClient(object):
    def __init__(self, *args, **kwargs):
        self.region = args[0]

    # For quick reference: https://docs.aws.amazon.com/gamelift/latest/apireference/API_StartMatchmaking.html
    def start_matchmaking(self, **kwargs):
        ResponseSyntax = """
        {
            "MatchmakingTicket": {
                "ConfigurationArn": "string",
                "ConfigurationName": "string",
                "EndTime": number,
                "EstimatedWaitTime": number,
                "GameSessionConnectionInfo": {
                    "DnsName": "string",
                    "GameSessionArn": "string",
                    "IpAddress": "string",
                    "MatchedPlayerSessions": [
                        {
                            "PlayerId": "string",
                            "PlayerSessionId": "string"
                        }
                    ],
                    "Port": number
                },
                "Players": [
                    {
                        "LatencyInMs": {
                            "string": number
                        },
                        "PlayerAttributes": {
                            "string": {
                                "N": number,
                                "S": "string",
                                "SDM": {
                                    "string": number
                                },
                                "SL": ["string"]
                            }
                        },
                        "PlayerId": "string",
                        "Team": "string"
                    }
                ],
                "StartTime": number,
                "Status": "string",
                "StatusMessage": "string",
                "StatusReason": "string",
                "TicketId": "string"
            }
        }
        """
        sample_response_from_gamelift  = """
        {
            'MatchmakingTicket': {
                'TicketId': '54a1351b-e271-489c-aa3e-e3c2cfa3c64f',
                'ConfigurationName': 'test',
                'ConfigurationArn': 'arn:aws:gamelift:eu-west-1:331925803394:matchmakingconfiguration/test',
                'Status': 'QUEUED',
                'StartTime': datetime.datetime(2021, 4, 23, 15, 1, 0, 460000, tzinfo=tzlocal()),
                'Players': [{
                    'PlayerId': '1',
                    'PlayerAttributes': {
                        'skill': {'N': 50.0}
                    },
                    'LatencyInMs': {}
                }]
            },
            'ResponseMetadata': {
                'RequestId': '675a758b-a5b9-4934-9167-beb5657016a3',
                'HTTPStatusCode': 200,
                'HTTPHeaders': {
                    'x-amzn-requestid': '675a758b-a5b9-4934-9167-beb5657016a3',
                    'content-type': 'application/x-amz-json-1.1',
                    'content-length': '323',
                    'date': 'Fri, 23 Apr 2021 15:00:59 GMT'
                },
                'RetryAttempts': 0
            }
        }
        """
        import datetime
        from dateutil.tz import tzlocal
        # MEMO TO SELF: the current processor re-uses the status field in redis for ticket events later, so we never actually see the status, just the latest mm event
        return {
            "MatchmakingTicket": {
                "TicketId": str(uuid.uuid4()),
                "ConfigurationName": kwargs["ConfigurationName"],
                "ConfigurationArn": f"arn:aws:gamelift:{self.region}:331925803394:matchmakingconfiguration/{kwargs['ConfigurationName']}",
                "Status": "QUEUED",  # Docs say the ticket will always be created with status QUEUED;
                'StartTime': datetime.datetime(2021, 4, 23, 15, 1, 0, 460000, tzinfo=tzlocal()),
                "Players": kwargs["Players"]
            },
            "ResponseMetadata": {
                "RequestId": str(uuid.uuid4()),
                "HTTPStatusCode": 200,
            }
        }

    def stop_matchmaking(self, **kwargs):
        sample_response = """
        {
            'ResponseMetadata': {
                'RequestId': 'c4270121-4e6c-4dea-8fd2-98d764c2b0ca', 
                'HTTPStatusCode': 200, 
                'HTTPHeaders': {
                    'x-amzn-requestid': 'c4270121-4e6c-4dea-8fd2-98d764c2b0ca', 
                    'content-type': 'application/x-amz-json-1.1', 
                    'content-length': '2', 
                    'date': 'Fri, 23 Apr 2021 15:06:18 GMT'
                }, 
                'RetryAttempts': 0
            }
        }
        """
        return {
            'ResponseMetadata': {
                'RequestId': str(uuid.uuid4()),
                'HTTPStatusCode': 200
            }
        }

    def accept_match(self, **kwargs):
        return {}


_matchmaking_event_template = {
    "version": "0",
    "id": str(uuid.uuid4()),
    "detail-type": "GameLift Matchmaking Event",
    "source": "aws.gamelift",
    "account": "123456789012",
    "time": "2021-05-27T15:19:34Z",
    "region": "eu-west-1",
    "resources": [
        "arn:aws:gamelift:eu-west-1:331925803394:matchmakingconfiguration/unittest"
    ],
    "detail": {
        "tickets": [{
            "ticketId": "54f4a80a-245a-445b-bb57-1ecc4685d584",
            "players": [
                {
                    "playerId": "189"
                }
            ],
            "startTime": "2021-05-27T15:19:34.315Z"
        }],
        "estimatedWaitMillis": "NOT_AVAILABLE",
        "type": "",
        "gameSessionInfo": {
            "ipAddress": "",
            "port": None,
            "players": [{
                "playerId": "189",
                "playerSessionId": "",
                "team": ""
            }]
        }
    }
}
