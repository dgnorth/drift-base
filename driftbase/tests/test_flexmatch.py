import http.client as http_client
import time

from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import flexmatch
import uuid
import json

REGION = "eu-west-1"
EVENTS_ROLE = "flexmatch_event"


class TestFlexmatchMatchmaker(BaseCloudkitTest):
    def test_flexmatch_is_in_matchmakers(self):
        self.make_player()
        self.assertIn("matchmakers", self.endpoints)
        response = self.get(self.endpoints["matchmakers"], expected_status_code=http_client.OK).json()
        self.assertIn("flexmatch", response)

    def test_my_flexmatch_ticket(self):
        with patch.object(flexmatch, 'get_player_ticket', return_value={"TicketId": "Something"}):
            self.make_player()
            self.assertIn("my_flexmatch_ticket", self.endpoints)


class TestFlexMatchPlayerAPI(BaseCloudkitTest):
    def test_patch_api(self):
        self.make_player()
        flexmatch_url = self.endpoints["my_flexmatch"]
        with patch.object(flexmatch, 'update_player_latency', return_value=None):
            with patch.object(flexmatch, 'get_player_latency_averages', return_value={}):
                with patch.object(flexmatch, 'get_valid_regions', return_value={REGION, "ble_region"}):
                    self.patch(flexmatch_url, expected_status_code=http_client.UNPROCESSABLE_ENTITY)
                    self.patch(flexmatch_url, data={"latencies": {REGION: 123, "ble_region": 456}},
                               expected_status_code=http_client.OK)

    def test_get_api(self):
        self.make_player()
        flexmatch_url = self.endpoints["my_flexmatch"]
        retval = {"a_region": 123}
        with patch.object(flexmatch, 'get_player_latency_averages', return_value=retval):
            response = self.get(flexmatch_url, expected_status_code=http_client.OK).json()
            self.assertDictEqual(retval, response["latencies"])


class TestFlexMatchTicketsAPI(BaseCloudkitTest):
    def test_get_api(self):
        self.make_player()
        tickets_url = self.endpoints["flexmatch_tickets"]
        with patch.object(flexmatch, 'get_player_ticket', return_value={}):
            response = self.get(tickets_url, expected_status_code=http_client.NOT_FOUND)
            self.assertIn("error", response.json())
        retval = {"TicketId": "SomeId", "Status": "SomeStatus", "ConfigurationName": "SomeConfig"}
        with patch.object(flexmatch, 'get_player_ticket', return_value=retval):
            response = self.get(tickets_url, expected_status_code=http_client.OK).json()
            self.assertIn("ticket_url", response)
            self.assertIn("ticket_id", response)
            self.assertIn("ticket_status", response)
            self.assertIn("matchmaker", response)

    def test_post_api(self):
        self.make_player()
        tickets_url = self.endpoints["flexmatch_tickets"]
        retval = {"TicketId": 123, "Status": "QUEUED", "ConfigurationName": "unittest"}
        with patch.object(flexmatch, 'upsert_flexmatch_ticket', return_value=retval):
            self.post(tickets_url, expected_status_code=http_client.UNPROCESSABLE_ENTITY)
            response = self.post(tickets_url, data={"matchmaker": "unittest"},
                                 expected_status_code=http_client.CREATED).json()
            self.assertIn("ticket_url", response)
            self.assertIn("ticket_id", response)
            self.assertIn("ticket_status", response)
            self.assertIn("matchmaker", response)

            self.assertTrue(response["ticket_url"].endswith("123"))
            self.assertTrue(response["ticket_id"] == "123")
            self.assertTrue(response["ticket_status"] == "QUEUED")
            self.assertTrue(response["matchmaker"] == "unittest")


class TestFlexMatchTicketAPI(BaseCloudkitTest):
    def test_get_api(self):
        self.make_player()
        some_ticket_id = "1235-abcdef-whatever"
        non_existent_ticket_url = self.endpoints["flexmatch_tickets"] + some_ticket_id
        with patch.object(flexmatch, 'get_player_ticket', return_value={}):
            response = self.get(non_existent_ticket_url, expected_status_code=http_client.NOT_FOUND)
            self.assertIn("error", response.json())
        retval = dict(TicketId=some_ticket_id, Status="SOMETHING", ConfigurationName="SomeConfig", Players=[])
        with patch.object(flexmatch, 'get_player_ticket', return_value=retval):
            response = self.get(non_existent_ticket_url, expected_status_code=http_client.OK).json()
            expected = dict(ticket_id=some_ticket_id, ticket_status="SOMETHING", configuration_name="SomeConfig",
                            players=[], connection_info=None, match_status=None)
            self.assertEqual(response, expected)

    def test_patch_api(self):
        self.make_player()
        non_existent_ticket_url = self.endpoints["flexmatch_tickets"] + "1235-abcdef-whatever"
        with patch.object(flexmatch, 'update_player_acceptance', return_value=None):
            response = self.get(non_existent_ticket_url, expected_status_code=http_client.NOT_FOUND)
            self.assertIn("error", response.json())

    def test_delete_api(self):
        self.make_player()
        non_existent_ticket_url = self.endpoints["flexmatch_tickets"] + "1235-abcdef-whatever"
        with patch.object(flexmatch, 'cancel_active_ticket', return_value=None):
            response = self.delete(non_existent_ticket_url, expected_status_code=http_client.OK).json()
            self.assertEqual(response["status"], "NoTicketFound")
        with patch.object(flexmatch, 'cancel_active_ticket', return_value="TicketState"):
            response = self.delete(non_existent_ticket_url, expected_status_code=http_client.OK).json()
            self.assertEqual(response["status"], "TicketState")
        with patch.object(flexmatch, 'cancel_active_ticket', return_value={"Key": "Value"}):
            response = self.delete(non_existent_ticket_url, expected_status_code=http_client.OK).json()
            self.assertEqual(response["status"], "Deleted")


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
            self.post(self.endpoints["party_invites"], data={"player_id": member["id"]},
                      expected_status_code=http_client.CREATED)

        # The others accept the invite
        for member in info[:-1]:
            self.auth(username=member["name"])
            notification, _ = self.get_player_notification("party_notification", "invite")
            accept_response = self.patch(notification["invite_url"], data={"inviter_id": host_id},
                                         expected_status_code=http_client.OK).json()
            member["member_url"] = accept_response["member_url"]

        # Populate host member url
        self.auth(username=info[-1]["name"])
        notification, _ = self.get_player_notification("party_notification", "player_joined")
        info[-1]["member_url"] = notification["inviting_member_url"]

        return info

    def _initiate_matchmaking(self, user_name=None, extras=None):
        if user_name is None:  # else we assume a user has authenticated
            user_name = self.make_player()

        data = {"matchmaker": "unittest"}
        if extras:
            data["extras"] = extras
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            post_response = self.post(self.endpoints["flexmatch_tickets"], data=data,
                                      expected_status_code=http_client.CREATED).json()
            ticket_url = post_response["ticket_url"]
            ticket = self.get(ticket_url, expected_status_code=http_client.OK)
        return user_name, ticket_url, ticket.json()

    @staticmethod
    def _get_event_details(ticket_id, player_info, event_type, **kwargs):
        if not isinstance(player_info, list):
            players = [player_info]
        else:
            players = player_info
        template = {
            "type": event_type,
            "matchId": "0a3eb4aa-ecdb-4595-81a0-ad2b2d61bd05",
            "gameSessionInfo": {
                "ipAddress": "",
                "port": "",
                "players": players
            },
            "tickets": [{
                "ticketId": ticket_id,
                "players": players
            }]
        }
        template.update(kwargs)
        return template

    @staticmethod
    def _get_event_data(event_details):
        data = {
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
        data["detail"].update(event_details)
        return data


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
        flexmatch_url = self.endpoints["my_flexmatch"]
        latencies = [1.0, 2.0, 3.0, 4.0, 5.0, 10.7]
        expected_avg = [1, 1, 2, 3, 4, 6]  # We expect integers representing the average of the last 3 values
        for i, latency in enumerate(latencies):
            patch_response = self.patch(flexmatch_url, data={"latencies": {REGION: latency}},
                                        expected_status_code=http_client.OK).json()
            self.assertIn("latencies", patch_response)
            response_latencies = patch_response["latencies"]
            self.assertEqual(response_latencies[REGION], expected_avg[i])
            # Fetch the same value via GET and make sure its the same
            get_response = self.get(flexmatch_url, expected_status_code=http_client.OK).json()["latencies"]
            self.assertEqual(get_response[REGION], expected_avg[i])

    def test_start_matchmaking(self):
        _, _, ticket = self._initiate_matchmaking()
        self.assertTrue(ticket["ticket_status"] == "QUEUED")

    def test_start_matchmaking_doesnt_modify_ticket_if_same_player_reissues_request(self):
        _, ticket1_url, ticket = self._initiate_matchmaking()
        first_id = ticket["ticket_id"]
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            response = self.post(self.endpoints["flexmatch_tickets"], data={"matchmaker": "unittest"},
                                 expected_status_code=http_client.CREATED).json()
        self.assertIn("ticket_url", response)
        ticket2_url = response["ticket_url"]
        second_id = self.get(ticket2_url, data={"matchmaker": "unittest"},
                             expected_status_code=http_client.OK).json()["ticket_id"]
        self.assertEqual(first_id, second_id)
        self.assertEqual(ticket1_url, ticket2_url)

    def test_start_matchmaking_creates_event(self):
        _, _, ticket = self._initiate_matchmaking()
        notification, message_number = self.get_player_notification("matchmaking", "MatchmakingStarted")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["event"] == "MatchmakingStarted")
        self.assertIn("ticket_url", notification["data"])
        self.assertIn("ticket_id", notification["data"])
        self.assertIn("ticket_status", notification["data"])
        self.assertIn("matchmaker", notification["data"])

    def test_matchmaking_includes_party_members(self):
        member, host = self._create_party()
        # Let member start matchmaking, host should be included in the ticket
        self.auth(member["name"])
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            _, ticket_url, ticket = self._initiate_matchmaking(member["name"])
            players = ticket["players"]
            self.assertEqual(len(players), 2)
            expected_players = {member["id"], host["id"]}
            response_players = {int(e["PlayerId"]) for e in players}
            self.assertSetEqual(response_players, expected_players)

    def test_start_matchmaking_creates_event_for_party_members(self):
        member, host = self._create_party()
        # Let member start matchmaking, host should be included in the ticket
        self.auth(member["name"])
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            self.post(self.endpoints["flexmatch_tickets"], data={"matchmaker": "unittest"},
                      expected_status_code=http_client.CREATED).json()
        # Check if party host got the message
        self.auth(host["name"])
        notification, message_number = self.get_player_notification("matchmaking", "MatchmakingStarted")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["event"] == "MatchmakingStarted")
        self.assertIn("ticket_url", notification["data"])
        self.assertIn("ticket_id", notification["data"])
        self.assertIn("ticket_status", notification["data"])
        self.assertIn("matchmaker", notification["data"])

    def test_delete_ticket(self):
        # start the matchmaking and then stop it.
        user_name, ticket_url, ticket = self._initiate_matchmaking()
        # Check that we have a stored ticket
        response = self.get(ticket_url, expected_status_code=http_client.OK)
        self.assertIn("ticket_id", response.json())
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            self.delete(ticket_url, expected_status_code=http_client.OK)
        # Ticket should now be in 'CANCELLING' state
        response = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual("CANCELLING", response["ticket_status"])

    def test_ticket_in_matched_state_does_not_get_deleted(self):
        player_name, ticket_url, ticket = self._initiate_matchmaking()
        ticket_id = ticket["ticket_id"]
        player_info = {"playerId": str(self.player_id), "team": "winners"}
        event_details = self._get_event_details(ticket_id, player_info, "PotentialMatchCreated",
                                                acceptanceRequired=True, acceptanceTimeout=123)
        data = self._get_event_data(event_details)
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(self.endpoints["flexmatch_events"], data=data, expected_status_code=http_client.OK)
        self.auth(player_name)
        response = self.delete(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(response["status"], "REQUIRES_ACCEPTANCE")

    def test_cannot_start_matchmaking_with_cancelling_ticket(self):
        player_name, ticket_url, ticket = self._initiate_matchmaking()
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            self.delete(ticket_url, expected_status_code=http_client.OK)
            self.post(self.endpoints["flexmatch_tickets"], data={"matchmaker": "unittest"},
                      expected_status_code=http_client.CONFLICT)

    def test_delete_ticket_clears_cached_ticket_on_permanent_error(self):
        """ If a ticket isn't cancellable because it's completed, we should clear it ? """
        def _stop_matchmaking_with_permanent_error_response(myself, **kwargs):
            response = {
                'Error': {
                    'Message': 'Matchmaking ticket was not found.',
                    'Code': 'NotFoundException'
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
                'Message': 'Matchmaking ticket was not found.'
            }
            from botocore.exceptions import ClientError
            raise ClientError(response, "stop_matchmaking")

        with patch.object(MockGameLiftClient, 'stop_matchmaking', _stop_matchmaking_with_permanent_error_response):
            with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
                _, ticket_url, _ = self._initiate_matchmaking()
                # Attempt to delete
                self.delete(ticket_url, expected_status_code=http_client.INTERNAL_SERVER_ERROR)
                # Ticket should be cleared
                self.get(ticket_url, expected_status_code=http_client.NOT_FOUND).json()
                # And there should be a message waiting
                notification, _ = self.get_player_notification("matchmaking", "MatchmakingCancelled")
                self.assertTrue(notification["event"] == "MatchmakingCancelled")

    def test_party_member_can_delete_ticket(self):
        member, host = self._create_party()
        # Host starts matchmaking
        self.auth(host["name"])
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            _, ticket_url, _ = self._initiate_matchmaking(host["name"])
            # member then cancels
            self.auth(member["name"])
            response = self.delete(ticket_url, expected_status_code=http_client.OK).json()
            self.assertEqual("CANCELLING", response["status"])

    def test_party_members_get_notified_if_ticket_is_cancelled(self):
        member, host = self._create_party()
        self.auth(member["name"])
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            _, ticket_url, _ = self._initiate_matchmaking(member["name"])
            # host then cancels
            self.auth(username=host["name"])
            self.delete(ticket_url, expected_status_code=http_client.OK)
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
        _, _, ticket = self._initiate_matchmaking(host["name"])
        events_url = self.endpoints["flexmatch_events"]
        with self.as_bearer_token_user(EVENTS_ROLE):
            player_info = [ {"playerId": player["id"], "playerSessionId": f"pebble-{player['id']}-flee"}
                            for player in (member, host) ]
            details = self._get_event_details(ticket["ticket_id"], player_info, "MatchmakingSucceeded")
            details["gameSessionInfo"].update({
                "ipAddress": "1.2.3.4",
                "port": "7780"
            })
            data = self._get_event_data(details)
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        for guy in (member, host):
            self.auth(guy["name"])
            notification, _ = self.get_player_notification("matchmaking", "MatchmakingSuccess")
            self.assertIsInstance(notification, dict)
            self.assertEqual(f"PlayerSessionId=pebble-{guy['id']}-flee?PlayerId={guy['id']}",
                             notification["data"]["options"])

    def test_completed_ticket_is_cleared_after_max_rejoin_time(self):
        username, ticket_url, ticket = self._initiate_matchmaking()
        player_id = self.player_id
        events_url = self.endpoints["flexmatch_events"]
        with patch.object(flexmatch._LockedTicket, 'MAX_REJOIN_TIME', 1):
            with self.as_bearer_token_user(EVENTS_ROLE):
                player_info = [{"playerId": player_id, "playerSessionId": f"pebble-{player_id}-flee"}]
                details = self._get_event_details(ticket["ticket_id"], player_info, "MatchmakingSucceeded")
                details["gameSessionInfo"].update({
                    "ipAddress": "1.2.3.4",
                    "port": "7780"
                })
                data = self._get_event_data(details)
                self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username)
        response = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(response["ticket_status"], "COMPLETED")
        time.sleep(1)
        self.get(ticket_url, expected_status_code=http_client.NOT_FOUND)

    def test_extra_matchmaking_data_is_included_in_ticket(self):
        user_name = self.make_player()
        extra_data = {
            str(self.player_id): {
                "Rank": {"N": 3.0},
                "Skill": {"N": 400.0}
            }
        }
        _, ticket_url, ticket = self._initiate_matchmaking(user_name, extra_data)
        self.assertIn("players", ticket)
        self.assertEqual(1, len(ticket["players"]))
        self.assertIn("PlayerAttributes", ticket["players"][0])
        player_attributes = eval(ticket["players"][0]["PlayerAttributes"])
        for k, v in extra_data[str(self.player_id)].items():
            self.assertIn(k, player_attributes)
            self.assertEqual(v, player_attributes[k])
        # above is basically this:
        #self.assertDictContainsSubset(extra_data[str(self.player_id)], player_attributes)

    def test_latencies_are_included_in_player_attributes(self):
        user_name = self.make_player()
        _, ticket_url, ticket = self._initiate_matchmaking(user_name)
        self.assertIn("players", ticket)
        self.assertEqual(1, len(ticket["players"]))
        self.assertIn("PlayerAttributes", ticket["players"][0])
        player_attributes = eval(ticket["players"][0]["PlayerAttributes"])
        self.assertIn("Latencies", player_attributes)
        self.assertIsInstance(player_attributes, dict)

    def test_personal_ticket_is_cancelled_when_player_joins_party(self):
        #  Start matchmaking solo
        user_name = self.make_player()
        player_id = self.player_id
        _, ticket_url, ticket = self._initiate_matchmaking(user_name)
        #  Join party
        _ = self._create_party(party_size=2)
        #  _create_party doesn't log last member out, so we can go ahead and invite
        inviter_id = self.player_id
        self.post(self.endpoints["party_invites"], data={'player_id': player_id},
                  expected_status_code=http_client.CREATED)
        # Login as first player and double check that the ticket is still in place
        self.auth(username=user_name)
        response = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(response["ticket_status"], "QUEUED")
        # Accept party invite
        notification, _ = self.get_player_notification("party_notification", "invite")
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            self.patch(notification['invite_url'], data={'inviter_id': inviter_id}, expected_status_code=http_client.OK)
        # Ticket should now be cancelled
        response = self.get(ticket_url, expected_status_code=http_client.NOT_FOUND).json()
        self.assertIn("error", response)
        # Client should've been notified of the cancellation
        notification, _ = self.get_player_notification("matchmaking", "MatchmakingStopped")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["event"] == "MatchmakingStopped")

    def test_team_ticket_is_cancelled_when_player_leaves_party(self):
        #  Create party
        party_member, party_host = self._create_party(party_size=2)
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            # Start matchmaking with the party
            _, ticket_url, ticket = self._initiate_matchmaking(party_host["name"])

            # Host matchmaking started event
            notification, _ = self.get_player_notification("matchmaking", "MatchmakingStarted")
            self.assertIsInstance(notification, dict)
            self.assertTrue(notification["event"] == "MatchmakingStarted")

            # Member matchmaking started event
            self.auth(username=party_member["name"])
            notification, _ = self.get_player_notification("matchmaking", "MatchmakingStarted")
            self.assertIsInstance(notification, dict)
            self.assertTrue(notification["event"] == "MatchmakingStarted")

            # Member leaves party
            self.delete(party_member["member_url"], expected_status_code=http_client.NO_CONTENT)

            # Ticket should now be cancelled

            # Member matchmaking stopped event
            notification, _ = self.get_player_notification("matchmaking", "MatchmakingStopped")
            self.assertIsInstance(notification, dict)
            self.assertTrue(notification["event"] == "MatchmakingStopped")

            # Host should've also been notified of the cancellation
            self.auth(username=party_host["name"])
            notification, _ = self.get_player_notification("matchmaking", "MatchmakingStopped")
            self.assertIsInstance(notification, dict)
            self.assertTrue(notification["event"] == "MatchmakingStopped")

    def test_client_unregistered_cancels_player_ticket(self):
        # Issue a ticket (implicitly creates a user and registers a client)
        user_name_, ticket_url, ticket = self._initiate_matchmaking()
        client_url = self.endpoints["my_client"]
        # Delete the client
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            r = self.delete(client_url, expected_status_code=http_client.OK).json()
        # Ticket should be CANCELLING now
        ticket = self.get(ticket_url).json()
        self.assertTrue(ticket["ticket_status"] == "CANCELLING")
        # Client should've been notified of the cancellation
        notification, _ = self.get_player_notification("matchmaking", "MatchmakingStopped")

    def test_player_quitting_match_updates_his_ticket(self):
        # Issue a ticket (implicitly creates a user and registers a client)
        user_name, ticket_url, ticket = self._initiate_matchmaking()
        player_id = self.player_id
        # Register a match with the player in it.
        self.auth_service()
        match_url = self._create_match(num_teams=2)["url"]
        match_resp = self.get(match_url).json()
        matchplayers_url = match_resp["matchplayers_url"]
        data = {
            "player_id": player_id,
            "team_id": 1
        }
        matchplayer_resp = self.post(matchplayers_url, data=data, expected_status_code=http_client.CREATED).json()
        # Delete the player from the match
        self.delete(matchplayer_resp["url"])
        # Verify the ticket is in 'MATCH_COMPLETE' state and that the connection info has been cleared.
        self.auth(user_name)
        ticket_resp = self.get(ticket_url).json()
        self.assertEqual(ticket_resp["ticket_id"], ticket["ticket_id"])
        self.assertEqual(ticket_resp["ticket_status"], "MATCH_COMPLETE")
        self.assertIsNone(ticket_resp["connection_info"])

    def test_delete_on_cancelled_ticket_does_not_change_its_status(self):
        # create ticket
        user_name, ticket_url, ticket = self._initiate_matchmaking()
        # put it in CANCELLING state
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            r = self.delete(ticket_url, expected_status_code=http_client.OK).json()
            self.assertEqual("CANCELLING", r["status"])
            # double check the ticket
            ticket = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual("CANCELLING", ticket["ticket_status"])
        # Fully cancel it
        events_url = self.endpoints["flexmatch_events"]
        details = self._get_event_details(ticket["ticket_id"],
                                          {"playerId": str(self.player_id)}, "MatchmakingCancelled")
        data = self._get_event_data(details)
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        # Try to delete again, check that it stays in 'CANCELLED' state
        self.auth(user_name)
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            ticket = self.get(ticket_url, expected_status_code=http_client.OK).json()
            # ticket should be CANCELLED now
            self.assertEqual("CANCELLED", ticket["ticket_status"])
            r = self.delete(ticket_url, expected_status_code=http_client.OK).json()
            self.assertEqual("CANCELLED", r["status"])


class FlexMatchEventTest(_BaseFlexmatchTest):
    def test_searching_event(self):
        user_name, ticket_url, ticket = self._initiate_matchmaking()
        ticket_id, player_info = ticket["ticket_id"], {"playerId": str(self.player_id)}
        with self.as_bearer_token_user(EVENTS_ROLE):
            details = self._get_event_details(ticket_id, player_info, "MatchmakingSearching")
            data = self._get_event_data(details)
            self.put(self.endpoints["flexmatch_events"], data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(r['ticket_status'], "SEARCHING")
        notification, _ = self.get_player_notification("matchmaking", "MatchmakingSearching")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["event"] == "MatchmakingSearching")

    def test_potential_match_event(self):
        user_name, ticket_url, ticket = self._initiate_matchmaking()
        events_url = self.endpoints["flexmatch_events"]
        acceptance_timeout = 123
        ticket_id, player_info = ticket["ticket_id"], {"playerId": str(self.player_id), "team": "winners"}
        details = self._get_event_details(ticket_id, player_info, "PotentialMatchCreated", acceptanceRequired=False,
                                          acceptanceTimeout=acceptance_timeout)
        data = self._get_event_data(details)
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        # Verify state
        self.auth(username=user_name)
        r = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(r['ticket_status'], "PLACING")
        # Verify notification sent
        notification, _ = self.get_player_notification("matchmaking", "PotentialMatchCreated")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["event"] == "PotentialMatchCreated")
        self.assertSetEqual(set(notification["data"]["teams"]["winners"]), {self.player_id})
        self.assertEqual(notification["data"]["match_id"], details["matchId"])
        # Test with acceptanceRequired as True
        with self.as_bearer_token_user(EVENTS_ROLE):
            data["detail"]["acceptanceRequired"] = True
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(r['ticket_status'], "REQUIRES_ACCEPTANCE")
        # Verify notification sent
        notification, _ = self.get_player_notification("matchmaking", "PotentialMatchCreated")
        self.assertTrue(notification["event"] == "PotentialMatchCreated")
        self.assertSetEqual(set(notification["data"]["teams"]["winners"]), {self.player_id})
        self.assertTrue(notification["data"]["acceptance_required"])
        self.assertEqual(notification["data"]["acceptance_timeout"], acceptance_timeout)

    def test_matchmaking_succeeded(self):
        user_name, ticket_url, ticket = self._initiate_matchmaking()
        connection_ip, connection_port = "1.2.3.4", "7780"
        player_session_id = "psess-6f45ca3a-5522-4f6c-9293-7df04dc12cb6"
        ticket_id, player_info = ticket["ticket_id"], {"playerId": str(self.player_id),
                                                       "playerSessionId": player_session_id}
        details = self._get_event_details(ticket_id, player_info, "MatchmakingSucceeded")
        details["gameSessionInfo"].update({
            "ipAddress": connection_ip,
            "port": connection_port
        })
        data = self._get_event_data(details)
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(self.endpoints["flexmatch_events"], data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual("COMPLETED", r['ticket_status'])
        self.assertTrue("connection_info" in r)
        session_info = r["connection_info"]
        self.assertEqual(connection_ip, session_info["ipAddress"])
        self.assertEqual(connection_port, session_info["port"])
        # Verify notification sent
        notification, _ = self.get_player_notification("matchmaking", "MatchmakingSuccess")
        self.assertTrue(notification["event"] == "MatchmakingSuccess")
        connection_data = notification["data"]
        self.assertEqual(f"{connection_ip}:{connection_port}", connection_data["connection_string"])
        self.assertEqual(f"PlayerSessionId={player_session_id}?PlayerId={self.player_id}", connection_data["options"])

    def test_matchmaking_cancelled(self):
        user_name, ticket_url, ticket = self._initiate_matchmaking()
        events_url = self.endpoints["flexmatch_events"]
        details = self._get_event_details(ticket["ticket_id"], {"playerId": str(self.player_id)}, "MatchmakingCancelled")
        data = self._get_event_data(details)
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(r['ticket_status'], "CANCELLED")
        notification, _ = self.get_player_notification("matchmaking", "MatchmakingCancelled")
        self.assertIsInstance(notification, dict)

    def test_backfill_ticket_cancellation_updates_player_ticket(self):
        # This is a test for a hack/heuristic; i.e. we want to mark tickets as MATCH_COMPLETE when a backfill ticket
        # for a match the player is in gets cancelled. This should not have to rely on heuristics like that.
        user_name, ticket_url, ticket = self._initiate_matchmaking()
        # Set ticket to 'COMPLETED'
        ticket_id, player_info = ticket["ticket_id"], {"playerId": str(self.player_id),
                                                       "playerSessionId": "psess-123123", "team": "winners"}
        details = self._get_event_details(ticket_id, player_info, "MatchmakingSucceeded")
        details["gameSessionInfo"].update({
            "ipAddress": "1.2.3.4",
            "port": "1234"
        })
        data = self._get_event_data(details)
        events_url = self.endpoints["flexmatch_events"]
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        # Ensure this works for multiple backfill tickets being cancelled
        for _ in range(2):
            with self.as_bearer_token_user(EVENTS_ROLE):
                real_ticket_id = ticket["ticket_id"]
                backfill_ticket_id = "BackFill--" + real_ticket_id
                # The backfill tickets are issued by the battleserver with a ticketId drift doesn't track
                details["tickets"][0]["ticketId"] = backfill_ticket_id
                details["type"] = "MatchmakingCancelled"
                data["detail"] = details
                self.put(events_url, data=data, expected_status_code=http_client.OK)
            self.auth(username=user_name)
            r = self.get(ticket_url, expected_status_code=http_client.OK).json()
            self.assertEqual(r['ticket_status'], "MATCH_COMPLETE")

    def test_accept_match_event(self):
        user_name, ticket_url, ticket = self._initiate_matchmaking()
        ticket_id, player_info = ticket["ticket_id"], {"playerId": str(self.player_id), "team": "winners"}
        details = self._get_event_details(ticket_id, player_info, "PotentialMatchCreated", acceptanceRequired=True, acceptanceTimeout=10)
        data = self._get_event_data(details)
        events_url = self.endpoints["flexmatch_events"]
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        # Verify state
        self.auth(username=user_name)
        r = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(r['ticket_status'], "REQUIRES_ACCEPTANCE")
        # Verify notification sent
        notification, _ = self.get_player_notification("matchmaking", "PotentialMatchCreated")
        self.assertIsInstance(notification, dict)
        self.assertTrue(notification["data"]["acceptance_required"])
        # Accept the match
        with patch.object(flexmatch, 'GameLiftRegionClient', MockGameLiftClient):
            self.patch(ticket_url, data={"match_id": details["matchId"], "acceptance": True},
                       expected_status_code=http_client.OK)
        # emit flexmatch event
        details["type"] = "AcceptMatch"
        details["tickets"][0]["players"][0]["accepted"] = True
        details["gameSessionInfo"]["players"][0]["accepted"] = True
        data["detail"].update(details)
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(r['ticket_status'], "REQUIRES_ACCEPTANCE")
        self.assertTrue(r['players'][0]['Accepted'])

    def test_accept_match_completed_event(self):
        user_name, ticket_url, ticket = self._initiate_matchmaking()
        ticket_id, player_info = ticket["ticket_id"], {"playerId": str(self.player_id), "team": "winners"}
        details = self._get_event_details(ticket_id, player_info, "PotentialMatchCreated", acceptanceRequired=True,
                                          acceptanceTimeout=10)
        data = self._get_event_data(details)
        events_url = self.endpoints["flexmatch_events"]
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(events_url, data=data, expected_status_code=http_client.OK)
            details["type"] = "AcceptMatchCompleted"
            details["acceptance"] = "Accepted"
            data["detail"] = details
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(r['match_status'], "ACCEPTED")
        with self.as_bearer_token_user(EVENTS_ROLE):
            data["detail"]["acceptance"] = "TimedOut"
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(r['match_status'], "TIMEDOUT")
        with self.as_bearer_token_user(EVENTS_ROLE):
            data["detail"]["acceptance"] = "Rejected"
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(r['match_status'], "REJECTED")

    def test_matchmaking_timed_out_event(self):
        user_name, ticket_url, ticket = self._initiate_matchmaking()
        ticket_id, player_info = ticket["ticket_id"], {"playerId": str(self.player_id), "team": "winners"}
        details = self._get_event_details(ticket_id, player_info, "MatchmakingTimedOut")
        data = self._get_event_data(details)
        events_url = self.endpoints["flexmatch_events"]
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(events_url, data=data, expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(r['ticket_status'], "TIMED_OUT")
        notification, _ = self.get_player_notification("matchmaking", "MatchmakingFailed")
        self.assertIsInstance(notification, dict)
        self.assertEqual(notification["data"]["reason"], "TimeOut")

    def test_matchmaking_failed_event(self):
        user_name, ticket_url, ticket = self._initiate_matchmaking()
        ticket_id, player_info = ticket["ticket_id"], {"playerId": str(self.player_id), "team": "winners"}
        details = self._get_event_details(ticket_id, player_info, "MatchmakingFailed", reason="UnitTestInducedFailure")
        events_url = self.endpoints["flexmatch_events"]
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(events_url, data=self._get_event_data(details), expected_status_code=http_client.OK)
        self.auth(username=user_name)
        r = self.get(ticket_url, expected_status_code=http_client.OK).json()
        self.assertEqual(r['ticket_status'], "FAILED")
        notification, _ = self.get_player_notification("matchmaking", "MatchmakingFailed")
        self.assertIsInstance(notification, dict)
        self.assertEqual(notification["data"]["reason"], details["reason"])

    def test_potential_match_notification_is_sent_to_all_party_members(self):
        # Create a team
        member1, member2, host = self._create_party(party_size=3)
        # Start matchmaking as a team, check if all members are in ticket
        _, _, ticket = self._initiate_matchmaking(host["name"])
        ticket_players = {int(p["PlayerId"]) for p in ticket["players"]}
        player_info = []
        for player in (member1, member2, host):
            self.assertIn(player["id"], ticket_players)
            player_info.append({"playerId": str(player["id"]), "team": "winners"})
        # PUT a PotentialMatchCreated event
        events_url = self.endpoints["flexmatch_events"]
        details = self._get_event_details(ticket["ticket_id"], player_info, "PotentialMatchCreated",
                                          acceptanceRequired=False, acceptanceTimeout=123)
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(events_url, data=self._get_event_data(details), expected_status_code=http_client.OK)
        # Check if all team members get the PLACING notification
        for player in (member1, member2, host):
            self.auth(username=player["name"])
            notification, _ = self.get_player_notification("matchmaking", "PotentialMatchCreated")
            self.assertIsInstance(notification, dict)
            self.assertEqual(notification["event"], "PotentialMatchCreated")
            self.assertSetEqual(ticket_players, set(notification["data"]["teams"]["winners"]))

    def test_searching_notification_is_sent_to_all_party_members(self):
        # Create a team
        member1, member2, host = self._create_party(party_size=3)
        # Start matchmaking as a team, check if all members are in ticket
        _, _, ticket = self._initiate_matchmaking(host["name"])
        ticket_players = {int(p["PlayerId"]) for p in ticket["players"]}
        player_info = []
        for player in (member1, member2, host):
            self.assertIn(player["id"], ticket_players)
            player_info.append({"playerId": str(player["id"]), "team": "winners"})
        # PUT a MatchmakingSearching event
        events_url = self.endpoints["flexmatch_events"]
        details = self._get_event_details(ticket["ticket_id"], player_info, "MatchmakingSearching",
                                          acceptanceRequired=False, acceptanceTimeout=123)
        with self.as_bearer_token_user(EVENTS_ROLE):
            self.put(events_url, data=self._get_event_data(details), expected_status_code=http_client.OK)
        # Check if all team members get the MatchmakingSearching notification
        for player in (member1, member2, host):
            self.auth(username=player["name"])
            notification, _ = self.get_player_notification("matchmaking", "MatchmakingSearching")
            self.assertIsInstance(notification, dict)
            self.assertTrue(notification["event"] == "MatchmakingSearching")


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
