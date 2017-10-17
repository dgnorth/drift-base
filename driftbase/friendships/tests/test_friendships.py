# -*- coding: utf-8 -*-
import httplib
import re
import uuid
import datetime
from mock import patch

from drift.systesthelper import uuid_string, big_number
from driftbase.utils.test_utils import BaseCloudkitTest


class FriendTokensTest(BaseCloudkitTest):
    """
    Tests for the /friend_tokens endpoint
    """
    def test_create_token(self):
        # Create player for test
        self.auth(username="Number one user")

        result = self.post(self.endpoints["friendship_tokens"], expected_status_code=httplib.CREATED).json()
        self.assertIsInstance(result, dict)

        pattern = re.compile('^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$', re.IGNORECASE)

        self.assertTrue(pattern.match(result["token"]), "Token '{}' doesn't match the expected uuid format".format(result["token"]))


    def test_delete_token(self):
        self.auth(username="Number one user")

        # create a token
        result = self.post(self.endpoints["friendship_tokens"], expected_status_code=httplib.CREATED).json()

        # delete the token
        self.delete(result['url'], expected_status_code=httplib.NO_CONTENT)

        # delete it again
        self.delete(result['url'], expected_status_code=httplib.NOT_FOUND)


class FriendsTest(BaseCloudkitTest):
    """
    Tests for the /friends endpoint
    """
    def test_no_friends(self):
        # Create players for test
        self.auth(username="Number one user")
        self.auth(username="Number two user")
        self.auth(username="Number three user")

        # Should have no friends
        friends = self.get(self.endpoints["my_friendships"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 0)


    def test_add_friend(self):
        # Create players for test
        self.auth(username="Number one user")
        p1 = self.player_id
        token1 = self.make_token()

        self.auth(username="Number two user")
        p2 = self.player_id
        token2 = self.make_token()

        self.auth(username="Number four user")
        player_id = self.player_id

        # add one friend
        self.post(self.endpoints["my_friendships"], data={"friend_id":p1, "token":token1}, expected_status_code=httplib.CREATED)

        friends = self.get(self.endpoints["my_friendships"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 1)
        self.assertEqual(friends[0]["friend_id"], p1)

        # add another friend
        self.post(self.endpoints["my_friendships"], data={"friend_id": p2, "token":token2}, expected_status_code=httplib.CREATED)

        friends = self.get(self.endpoints["my_friendships"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 2)
        self.assertTrue(friends[0]["friend_id"] in [p1, p2])
        self.assertTrue(friends[1]["friend_id"] in [p1, p2])
        self.assertTrue(friends[0]["friend_id"] != friends[1]["friend_id"])

        # check that first player is friends with you
        self.auth(username="Number one user")
        friends = self.get(self.endpoints["my_friendships"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 1)
        self.assertEqual(friends[0]["friend_id"], player_id)

        # check that second player is friends with you
        self.auth(username="Number two user")
        friends = self.get(self.endpoints["my_friendships"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 1)
        self.assertEqual(friends[0]["friend_id"], player_id)


    def test_delete_friend(self):
        # Create players for test
        self.auth(username="Number seven user")
        p1 = self.player_id
        token = self.make_token()

        self.auth(username="Number six user")

        # add one friend
        result = self.post(self.endpoints["my_friendships"], data={"friend_id":p1, "token":token}, expected_status_code=httplib.CREATED).json()

        # delete friend
        self.delete(result["url"], expected_status_code=httplib.NO_CONTENT)

        friends = self.get(self.endpoints["my_friendships"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 0)

        # other player should not have you as friend anymore
        self.auth(username="Number seven user")
        friends = self.get(self.endpoints["my_friendships"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 0)


    def test_cannot_add_self_as_friend(self):

        # Create player for test
        self.auth(username="Number four user")
        token = self.make_token()
        player_id = self.player_id

        # add self as friend
        result = self.post(self.endpoints["my_friendships"], data={"friend_id":player_id, "token":token}, expected_status_code=httplib.METHOD_NOT_ALLOWED)
        response = result.json()
        self.assertEqual(response['error']['code'], "user_error")
        self.assertEqual(response['error']['description'], "You cannot befriend yourself!")


    def test_cannot_add_player_as_friend_with_mismatching_token(self):
        # Create players for test
        self.auth(username="Number one user")
        token = self.make_token()

        self.auth(username="Number four user")

        # add non exiting player as friend
        result = self.post(self.endpoints["my_friendships"], data={"friend_id":big_number, "token":token}, expected_status_code=httplib.NOT_FOUND)
        response = result.json()
        self.assertEqual(response['error']['code'], "user_error")
        self.assertEqual(response['error']['description'], "Token doesn't match the friend you're adding!")


    def test_cannot_add_player_as_friend_with_invalid_token(self):
        # Create players for test
        self.auth(username="Number one user")
        p1 = self.player_id

        self.auth(username="Number four user")

        token = str(uuid.uuid4())

        # add exiting player as friend, but use invalid token
        result = self.post(self.endpoints["my_friendships"], data={"friend_id":p1, "token":token}, expected_status_code=httplib.NOT_FOUND)
        response = result.json()
        self.assertEqual(response['error']['code'], "user_error")
        self.assertEqual(response['error']['description'], "Token not found!")


    def test_adding_same_friend_twice_changes_nothing(self):
        # Create players for test
        self.auth(username="Number one user")
        p1 = self.player_id
        token = self.make_token()

        self.auth(username="Number five user")

        # add a friend
        self.post(self.endpoints["my_friendships"], data={"friend_id":p1, "token":token}, expected_status_code=httplib.CREATED)
        # add same friend again
        self.post(self.endpoints["my_friendships"], data={"friend_id":p1, "token":token}, expected_status_code=httplib.OK)

        friends = self.get(self.endpoints["my_friendships"]).json()
        self.assertIsInstance(friends, list)
        self.assertEqual(len(friends), 1)
        self.assertEqual(friends[0]["friend_id"], p1)


    def make_token(self):
        return self.post(self.endpoints["friendship_tokens"], expected_status_code=httplib.CREATED).json()["token"]
