# -*- coding: utf-8 -*-
import collections
import datetime
from six.moves import http_client
from mock import patch
from drift.systesthelper import uuid_string
from driftbase.utils.test_utils import BaseMatchTest


class MatchQueueTest(BaseMatchTest):
    """
    Tests for the /matchqueue player endpoints
    """
    def clear_queue(self):
        # cleanup after earlier tests
        matchqueue_url = self.endpoints["matchqueue"]
        matches_url = self.endpoints["matches"]

        # The matchqueue may mutate during deletion so we requery after each delete
        while True:
            entries = self.get(matchqueue_url + "?status=waiting&status=matched") \
                          .json()
            for entry in entries:
                self.delete(entry["matchqueueplayer_url"] + "?force=true")
            else:
                break

        entries = self.get(matches_url).json()
        for entry in entries:
            if entry["status"] == "idle":
                self.put(entry["url"], data={"status": "completed"})

    def test_matchqueue_nomatches(self):
        # add two players to the queue
        self.auth_service()
        self.clear_queue()

        self.make_player()
        matchqueue_url = self.endpoints["matchqueue"]

        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)

        self.make_player()
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)

        r = self.get(matchqueue_url)
        self.assertEquals(len(r.json()), 2)
        self.assertIsNone(r.json()[0]["match_id"])
        self.assertIsNone(r.json()[1]["match_id"])

    def test_matchqueue_response(self):
        # add two players to the queue
        self.make_player()
        matchqueue_url = self.endpoints["matchqueue"]

        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        resp = r.json()
        self.assertIn("match_id", resp)
        self.assertIn("match_url", resp)
        self.assertIn("player_id", resp)
        self.assertIn("ue4_connection_url", resp)
        self.assertIsNotNone(resp["player_url"])

    def test_matchqueue_remove(self):
        self.make_player()
        matchqueue_url = self.endpoints["matchqueue"]
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        resp = r.json()
        matchqueueplayer_url = resp["matchqueueplayer_url"]
        r = self.get(matchqueueplayer_url)

        self.delete(matchqueueplayer_url)
        self.get(matchqueueplayer_url, expected_status_code=http_client.NOT_FOUND)

    def test_matchqueue_remove_matched(self):
        self.auth_service()
        self.clear_queue()
        self._create_match()

        self.make_player()

        matchqueue_url = self.endpoints["matchqueue"]
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)

        resp = r.json()
        other_matchqueueplayer_url = resp["matchqueueplayer_url"]

        self.make_player()
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)

        resp = r.json()
        matchqueueplayer_url = resp["matchqueueplayer_url"]
        r = self.get(matchqueueplayer_url)
        self.assertIsNotNone(r.json()["match_id"])

        r = self.delete(matchqueueplayer_url, expected_status_code=http_client.BAD_REQUEST)
        self.assertEquals(r.json()["error"]["code"], "player_already_matched")

        # make sure the resource didn't get deleted anyway
        r = self.get(matchqueueplayer_url)
        self.assertIsNotNone(r.json()["match_id"])

        r = self.get(other_matchqueueplayer_url)
        self.assertIsNotNone(r.json()["match_id"])

    def test_matchqueue_simplematchmaking(self):
        # create a match
        self.auth_service()
        self.clear_queue()
        match = self._create_match()

        # add two players to the queue
        self.make_player()
        matchqueue_url = self.endpoints["matchqueue"]

        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer1_url = r.json()["matchqueueplayer_url"]
        r = self.get(matchqueueplayer1_url)
        self.assertEquals(r.json()["status"], "waiting")
        self.assertIsNone(r.json()["match_id"])
        self.assertIn('match_url', r.json())

        self.make_player()
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer2_url = r.json()["matchqueueplayer_url"]

        r = self.get(matchqueue_url + "?status=matched")
        self.assertEquals(len(r.json()), 2)
        self.assertEquals(r.json()[0]["match_id"], match["match_id"])
        self.assertEquals(r.json()[1]["match_id"], match["match_id"])

        r = self.get(matchqueueplayer2_url)
        self.assertEquals(r.json()["status"], "matched")
        self.assertEquals(r.json()["match_id"], match["match_id"])
        self.assertIsNotNone(r.json()["ue4_connection_url"])
        self.assertIn("player_id=%s" % self.player_id, r.json()["ue4_connection_url"])

        # The player should not get a connection url for the other player's resource
        r = self.get(matchqueueplayer1_url)
        self.assertIsNone(r.json()["ue4_connection_url"])

    def test_matchqueue_multiplematchmaking(self):
        # create a match
        self.auth_service()
        self.clear_queue()
        matchqueue_url = self.endpoints["matchqueue"]

        for i in xrange(3):
            self.auth_service()
            self._create_match()
            # make 2 players for each match
            for j in xrange(2):
                self.make_player()
                data = {"player_id": self.player_id}
                r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)

        r = self.get(matchqueue_url)
        # make sure everyone found a match and that no match has more than 2 people in it
        num_players_in_match = collections.defaultdict(int)
        for entry in r.json():
            self.assertIsNotNone(entry["match_id"])
            num_players_in_match[entry["match_id"]] += 1
        self.assertEquals(sum(num_players_in_match.values()), len(num_players_in_match) * 2)

    def test_matchqueue_playeroffline(self):
        # create a match
        self.auth_service()
        self.clear_queue()
        self._create_match()

        # add a players to the queue
        self.make_player()
        matchqueue_url = self.endpoints["matchqueue"]

        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url = r.json()["matchqueueplayer_url"]
        # make the player go offline

        self.make_player()
        # mock out the utcnow call so that we can put the players 'offline'
        with patch("driftbase.matchqueue.utcnow") as mock_date:
            mock_date.return_value = datetime.datetime.utcnow() + datetime.timedelta(minutes=5)

            data = {"player_id": self.player_id}
            r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)

            # Both players should be removed from the match queue
            r = self.get(matchqueue_url)
            self.assertEquals(len(r.json()), 0)

            r = self.get(matchqueueplayer_url, expected_status_code=http_client.NOT_FOUND)

    def test_matchqueue_lock_conflict(self):
        # create a match
        self.auth_service()
        self.clear_queue()
        self._create_match()

        # add a player to the queue
        self.make_player()
        other_player_id = self.player_id
        matchqueue_url = self.endpoints["matchqueue"]

        # now we mock out the mutex so that it reports that a locking conflict exists
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        with patch("driftbase.matchqueue.lock", side_effect=Exception('cannot lock')):
            self.make_player()
            data = {"player_id": self.player_id}

            r = self.post(matchqueue_url, data=data, expected_status_code=http_client.BAD_REQUEST)

            # we should get a 400 error back and the only guy in the match queue should
            # be the first one
            self.assertIn("error processing the match queue", r.json()["error"]["description"])
            r = self.get(matchqueue_url)
            js = r.json()
            self.assertEquals(len(js), 1)
            self.assertNotIn(self.player_id, [d["player_id"] for d in js])
            self.assertIn(other_player_id, [d["player_id"] for d in js])

    def test_joining_match_queue_twice(self):
        """
        This assumes there are registered battles expecting
        two players on the tier you connect to

        Join the queue with client A, status is waiting
        Join the queue with client B, status is matched
        A and B both get status matched on the next poll
        Join the queue again (POST) with A, status is waiting
        B will still show status matched
        A will show status waiting

        B must at this point leave the queue, and join again, or
        simply join again, without first leaving
        """
        # create a match
        self.auth_service()
        self.clear_queue()
        match = self._create_match()
        matchqueue_url = self.endpoints["matchqueue"]

        # add two players to the queue
        player_a = self.make_player()
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url = r.json()["matchqueueplayer_url"]
        r = self.get(matchqueueplayer_url)
        self.assertEquals(r.json()["status"], "waiting")
        self.assertIsNone(r.json()["match_id"])
        self.assertIn('match_url', r.json())

        player_b = self.make_player()
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_b = r.json()["matchqueueplayer_url"]

        # A and B are now matched
        r = self.get(matchqueue_url + "?status=matched")
        self.assertEquals(len(r.json()), 2)
        self.assertEquals(r.json()[0]["match_id"], match["match_id"])
        self.assertEquals(r.json()[1]["match_id"], match["match_id"])

        r = self.get(matchqueueplayer_url)
        self.assertEquals(r.json()["status"], "matched")
        self.assertEquals(r.json()["match_id"], match["match_id"])

        # Add player C to the queue who is matched with no one
        player_c = self.make_player()
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_c = r.json()["matchqueueplayer_url"]
        r = self.get(matchqueueplayer_url_c)
        self.assertEquals(r.json()["status"], "waiting")
        self.assertIsNone(r.json()["match_id"])

        # Now A screws everything up by joining again
        self.make_player(player_a)
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url = r.json()["matchqueueplayer_url"]
        r = self.get(matchqueueplayer_url)
        self.assertEquals(r.json()["status"], "waiting")
        self.assertIsNone(r.json()["match_id"])
        self.assertIn('match_url', r.json())

        # Make sure B is no longer waiting or matched in any match
        self.make_player(player_b)
        matchqueue_url = self.endpoints["matchqueue"]
        r = self.get(matchqueueplayer_url_b, expected_status_code=http_client.NOT_FOUND)

        # Make sure C is unaffected
        r = self.get(matchqueueplayer_url_c)
        self.assertEquals(r.json()['status'], 'waiting')
        self.assertIsNone(r.json()["match_id"])

        # Add player D to the queue who is matched with no one because he has a different ref
        self.make_player()
        data = {"player_id": self.player_id, "ref": "something/else"}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_d = r.json()["matchqueueplayer_url"]
        r = self.get(matchqueueplayer_url_c)
        self.assertEquals(r.json()["status"], "waiting")
        self.assertIsNone(r.json()["match_id"])

        # Player C rejoins and is usurped but other players should be unaffected
        self.make_player(player_c)
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)

        r = self.get(matchqueueplayer_url_d)
        self.assertEquals(r.json()["status"], "waiting")
        self.assertIsNone(r.json()["match_id"])

    def test_matchqueue_placement_emptystring(self):
        self.auth_service()
        self.clear_queue()
        self._create_match()
        # the machine has placement 'placement' by default
        matchqueue_url = self.endpoints["matchqueue"]

        # add two players, not caring about placement
        self.make_player()
        data = {"player_id": self.player_id, "placement": ""}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_a = r.json()["matchqueueplayer_url"]

        self.make_player()
        data = {"player_id": self.player_id, "placement": ""}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_b = r.json()["matchqueueplayer_url"]

        r = self.get(matchqueueplayer_url_a)
        self.assertEquals(r.json()["status"], "matched")

        r = self.get(matchqueueplayer_url_b)
        self.assertEquals(r.json()["status"], "matched")

    def test_matchqueue_placement_notfound(self):
        self.auth_service()
        self.clear_queue()
        match = self._create_match()
        # the machine has placement 'placement' by default
        matchqueue_url = self.endpoints["matchqueue"]

        # add two players, one not caring about placement but
        # the other one wanting another placement
        self.make_player()
        data = {"player_id": self.player_id, "placement": ""}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_a = r.json()["matchqueueplayer_url"]

        self.make_player()
        data = {"player_id": self.player_id, "placement": "somethingelse"}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_b = r.json()["matchqueueplayer_url"]

        r = self.get(matchqueueplayer_url_a)
        self.assertEquals(r.json()["status"], "waiting")

        r = self.get(matchqueueplayer_url_b)
        self.assertEquals(r.json()["status"], "waiting")

        # add a third player choosing placement 'placement' and it should be
        # matched up with player_a but player_b is still waiting
        self.make_player()
        data = {"player_id": self.player_id, "placement": "placement"}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_c = r.json()["matchqueueplayer_url"]

        r = self.get(matchqueueplayer_url_a)
        self.assertEquals(r.json()["status"], "matched")
        self.assertEquals(r.json()["match_id"], match["match_id"])

        r = self.get(matchqueueplayer_url_b)
        self.assertEquals(r.json()["status"], "waiting")

        r = self.get(matchqueueplayer_url_c)
        self.assertEquals(r.json()["status"], "matched")
        self.assertEquals(r.json()["match_id"], match["match_id"])

    def test_matchqueue_ref(self):
        self.auth_service()
        self.clear_queue()
        match = self._create_match()
        # the machine has ref 'ref' by default
        matchqueue_url = self.endpoints["matchqueue"]

        # add two players, one not caring about ref but the other one wanting another ref
        self.make_player()
        data = {"player_id": self.player_id, "ref": ""}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_a = r.json()["matchqueueplayer_url"]

        self.make_player()
        data = {"player_id": self.player_id, "ref": "somethingelse"}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_b = r.json()["matchqueueplayer_url"]

        r = self.get(matchqueueplayer_url_a)
        self.assertEquals(r.json()["status"], "waiting")

        r = self.get(matchqueueplayer_url_b)
        self.assertEquals(r.json()["status"], "waiting")

        # add a third player choosing ref 'ref' and it should be matched up with
        # player_a but player_b is still waiting
        self.make_player()
        data = {"player_id": self.player_id, "ref": "test/testing"}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_c = r.json()["matchqueueplayer_url"]

        r = self.get(matchqueueplayer_url_a)
        self.assertEquals(r.json()["status"], "matched")
        self.assertEquals(r.json()["match_id"], match["match_id"])

        r = self.get(matchqueueplayer_url_b)
        self.assertEquals(r.json()["status"], "waiting")

        r = self.get(matchqueueplayer_url_c)
        self.assertEquals(r.json()["status"], "matched")
        self.assertEquals(r.json()["match_id"], match["match_id"])

    def test_matchqueue_ref_and_placement(self):
        self.auth_service()
        self.clear_queue()
        match = self._create_match()
        # the machine has ref 'ref' by default
        matchqueue_url = self.endpoints["matchqueue"]

        # add two players, one not caring about ref but the other one wanting another ref
        self.make_player()
        data = {"player_id": self.player_id, "ref": "", "placement": ""}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_a = r.json()["matchqueueplayer_url"]

        self.make_player()
        data = {"player_id": self.player_id, "ref": "somethingelse", "placement": ""}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_b = r.json()["matchqueueplayer_url"]

        r = self.get(matchqueueplayer_url_a)
        self.assertEquals(r.json()["status"], "waiting")

        r = self.get(matchqueueplayer_url_b)
        self.assertEquals(r.json()["status"], "waiting")

        # add a third player choosing ref 'ref' and it should be matched up with player_a
        # but player_b is still waiting
        self.make_player()
        data = {"player_id": self.player_id, "ref": "test/testing", "placement": "placement"}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_url_c = r.json()["matchqueueplayer_url"]

        r = self.get(matchqueueplayer_url_a)
        self.assertEquals(r.json()["status"], "matched")
        self.assertEquals(r.json()["match_id"], match["match_id"])

        r = self.get(matchqueueplayer_url_b)
        self.assertEquals(r.json()["status"], "waiting")

        r = self.get(matchqueueplayer_url_c)
        self.assertEquals(r.json()["status"], "matched")
        self.assertEquals(r.json()["match_id"], match["match_id"])

    def test_matchqueue_challenge(self):
        # create a match
        self.auth_service()
        self.clear_queue()
        match = self._create_match()

        # add two players to the queue
        self.make_player()
        matchqueue_url = self.endpoints["matchqueue"]

        token = uuid_string()

        data = {"player_id": self.player_id, "token": token}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer1_url = r.json()["matchqueueplayer_url"]
        r = self.get(matchqueueplayer1_url)
        self.assertEquals(r.json()["status"], "waiting")
        self.assertIsNone(r.json()["match_id"])
        self.assertIn('match_url', r.json())

        # add a new player who is using a different token
        self.make_player()
        data = {"player_id": self.player_id, "token": uuid_string()}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_anothertoken_url = r.json()["matchqueueplayer_url"]

        # add a new player who is using no token
        self.make_player()
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer_notoken_url = r.json()["matchqueueplayer_url"]

        self.make_player()
        data = {"player_id": self.player_id, "token": token}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer2_url = r.json()["matchqueueplayer_url"]

        r = self.get(matchqueue_url + "?status=matched")

        self.assertEquals(len(r.json()), 2)
        self.assertEquals(r.json()[0]["match_id"], match["match_id"])
        self.assertEquals(r.json()[1]["match_id"], match["match_id"])

        r = self.get(matchqueueplayer_anothertoken_url)
        self.assertEquals(r.json()["status"], "waiting")
        self.assertIsNone(r.json()["match_id"])

        r = self.get(matchqueueplayer_notoken_url)
        self.assertEquals(r.json()["status"], "waiting")
        self.assertIsNone(r.json()["match_id"])

        r = self.get(matchqueueplayer1_url)
        self.assertEquals(r.json()["status"], "matched")
        self.assertEquals(r.json()["match_id"], match["match_id"])

        r = self.get(matchqueueplayer2_url)
        self.assertEquals(r.json()["status"], "matched")
        self.assertEquals(r.json()["match_id"], match["match_id"])

    def test_matchqueue_matchafterqueue(self):
        # Two people join the queue and don't find a match.
        # Then we add a new match and the two players should get matched into it

        # create a match
        self.auth_service()
        self.clear_queue()

        # add two players to the queue
        self.make_player()
        matchqueue_url = self.endpoints["matchqueue"]

        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer1_url = r.json()["matchqueueplayer_url"]
        r = self.get(matchqueueplayer1_url)
        self.assertEquals(r.json()["status"], "waiting")
        self.assertIsNone(r.json()["match_id"])
        self.assertIn('match_url', r.json())

        self.make_player()
        data = {"player_id": self.player_id}
        r = self.post(matchqueue_url, data=data, expected_status_code=http_client.CREATED)
        matchqueueplayer2_url = r.json()["matchqueueplayer_url"]

        # before we create the match both players should be 'waiting'
        r = self.get(matchqueue_url + "?status=waiting")
        self.assertEquals(len(r.json()), 2)

        r = self.get(matchqueueplayer1_url)
        self.assertEquals(r.json()["status"], "waiting")
        self.assertIsNone(r.json()["match_id"])

        r = self.get(matchqueueplayer2_url)
        self.assertEquals(r.json()["status"], "waiting")
        self.assertIsNone(r.json()["match_id"])

        # now create a match and ensure the players are matched into it
        self.auth_service()
        match = self._create_match()

        r = self.get(matchqueue_url + "?status=matched")
        self.assertEquals(len(r.json()), 2)

        self.assertEquals(r.json()[0]["match_id"], match["match_id"])
        self.assertEquals(r.json()[1]["match_id"], match["match_id"])

        r = self.get(matchqueueplayer2_url)
        self.assertEquals(r.json()["status"], "matched")
        self.assertEquals(r.json()["match_id"], match["match_id"])
