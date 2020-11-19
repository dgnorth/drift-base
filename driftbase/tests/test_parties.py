import re
import uuid

from six.moves import http_client

from driftbase.utils.test_utils import BaseCloudkitTest


class PartiesTest(BaseCloudkitTest):
    """
    Tests for the /parties endpoint
    """

    def make_user_name(self, name):
        # For performance reasons the test DB is not cleared between tests
        # so to ensure a clean slate for some tests, we must be able to generate fresh users
        return "{}.{}".format(str(uuid.uuid4())[:8], name)

    def test_party_invite_creates_party_after_one_player_accepts(self):
        # Create players for test
        host_user = self.make_user_name("Host")
        guest_user_1 = self.make_user_name("Guest 1")
        guest_user_2 = self.make_user_name("Guest 2")

        self.auth(username=guest_user_1)
        g1_id = self.player_id
        self.auth(username=guest_user_2)
        g2_id = self.player_id
        self.auth(username=host_user)
        host_id = self.player_id

        # Invite g1 to a new party
        invite = self.post(self.endpoints["party_invites"], data={'player_id': g1_id},
                           expected_status_code=http_client.CREATED).json()

        # Check g1 gets a notification about the invite
        self.auth(username=guest_user_1)
        g1_notification, g1_message_number = self.get_party_notification('invite')
        self.assertEqual(g1_notification['inviting_player_id'], host_id)
        self.assertEqual(g1_notification['invite_url'], invite['url'])

        # Accept the invite, and check that both players are in the party
        accept = self.patch(g1_notification['invite_url'], data={'inviter_id': host_id}).json()
        party = self.get(accept['party_url']).json()
        player_ids = [entry['id'] for entry in party['players']]
        self.assertEqual(len(player_ids), 2)
        self.assertIn(g1_id, player_ids)
        self.assertIn(host_id, player_ids)

        # Check g1 doesn't get a notification about joining
        g1_notification, g1_message_number = self.get_party_notification('player_joined',
                                                                         messages_after=g1_message_number)
        self.assertIsNone(g1_notification)

        # Check host gets a notification about the new party
        self.auth(username=host_user)
        host_notification, host_message_number = self.get_party_notification('player_joined')
        self.assertEqual(host_notification['party_url'], accept['party_url'])

        # Invite g2 as well
        invite = self.post(self.endpoints["party_invites"], data={'player_id': g2_id},
                           expected_status_code=http_client.CREATED).json()

        # Check g2 gets a notification about the invite
        self.auth(username=guest_user_2)
        g2_notification, g2_message_number = self.get_party_notification('invite')
        self.assertEqual(g2_notification['inviting_player_id'], host_id)
        self.assertEqual(g2_notification['invite_url'], invite['url'])

        # Accept the invite, and check that all three players are in the party
        accept = self.patch(g2_notification['invite_url'], data={'inviter_id': host_id}).json()
        party = self.get(accept['party_url']).json()
        player_ids = [entry['id'] for entry in party['players']]
        self.assertEqual(len(player_ids), 3)
        self.assertIn(host_id, player_ids)
        self.assertIn(g1_id, player_ids)
        self.assertIn(g2_id, player_ids)

        # Check host gets a notification about the joining player
        self.auth(username=host_user)
        host_notification, host_message_number = self.get_party_notification('player_joined',
                                                                             messages_after=host_message_number)
        self.assertEqual(host_notification['party_url'], accept['party_url'])

        # Check g1 gets a notification about the joining player
        self.auth(username=guest_user_1)
        g1_notification, g1_message_number = self.get_party_notification('player_joined',
                                                                         messages_after=g1_message_number)
        self.assertEqual(g1_notification['party_url'], accept['party_url'])

        # Check g2 doesn't get a notification about joining
        self.auth(username=guest_user_2)
        g2_notification, g2_message_number = self.get_party_notification('player_joined',
                                                                         messages_after=g2_message_number)
        self.assertIsNone(g2_notification)

    def test_decline_invite(self):
        # Create players for test
        host_user = self.make_user_name("Host")
        guest_user_1 = self.make_user_name("Guest 1")
        guest_user_2 = self.make_user_name("Guest 2")

        self.auth(username=guest_user_1)
        g1_id = self.player_id
        self.auth(username=guest_user_2)
        g2_id = self.player_id
        self.auth(username=host_user)
        host_id = self.player_id

        # Invite g1 to a new party
        invite = self.post(self.endpoints["party_invites"], data={'player_id': g1_id},
                           expected_status_code=http_client.CREATED).json()

        # Decline the invite
        self.auth(username=guest_user_1)
        g1_notification, g1_message_number = self.get_party_notification('invite')
        self.delete(g1_notification['invite_url'], data={'inviter_id': host_id})

        # Check host gets a notification about the player declining
        self.auth(username=host_user)
        host_notification, host_message_number = self.get_party_notification('invite_declined')
        self.assertEqual(host_notification['player_id'], g1_id)

        # Check trying to accept the deleted invite fails
        self.patch(g1_notification['invite_url'], data={'inviter_id': host_id}, expected_status_code=http_client.NOT_FOUND)

    def test_leave_party(self):
        # Create players for test
        host_user = self.make_user_name("Host")
        guest_user_1 = self.make_user_name("Guest 1")
        guest_user_2 = self.make_user_name("Guest 2")

        self.auth(username=guest_user_1)
        g1_id = self.player_id
        self.auth(username=guest_user_2)
        g2_id = self.player_id
        self.auth(username=host_user)
        host_id = self.player_id

        # Invite g1 to a new party
        g1_invite = self.post(self.endpoints["party_invites"], data={'player_id': g1_id},
                           expected_status_code=http_client.CREATED).json()

        g2_invite = self.post(self.endpoints["party_invites"], data={'player_id': g2_id},
                           expected_status_code=http_client.CREATED).json()

        # Accept the g1 invite
        self.auth(username=guest_user_1)
        g1_notification, g1_message_number = self.get_party_notification('invite')
        g1_accept = self.patch(g1_notification['invite_url'], data={'inviter_id': host_id}).json()

        # Accept the g2 invite
        self.auth(username=guest_user_2)
        g2_notification, g2_message_number = self.get_party_notification('invite')
        g2_accept = self.patch(g2_notification['invite_url'], data={'inviter_id': host_id}).json()

        # Leave the party with g2
        self.delete(g2_accept['player_url'])

        # Check host gets a notification
        self.auth(username=host_user)
        host_notification, host_message_number = self.get_party_notification('player_joined')
        party_url = host_notification['party_url']
        host_notification, host_message_number = self.get_party_notification('player_left', messages_after=host_message_number)
        self.assertEqual(host_notification['player_id'], g2_id)

        # Check g1 gets a notification
        self.auth(username=guest_user_1)
        g1_notification, g1_message_number = self.get_party_notification('player_left')
        self.assertEqual(g1_notification['player_id'], g2_id)

        # Check party still contains host and g1
        party = self.get(party_url).json()
        player_ids = [entry['id'] for entry in party['players']]
        self.assertEqual(len(player_ids), 2)
        self.assertIn(host_id, player_ids)
        self.assertIn(g1_id, player_ids)

        # Leave the party with g1
        self.delete(g1_accept['player_url'])

        # Check host gets a notification
        self.auth(username=host_user)
        host_notification, host_message_number = self.get_party_notification('player_left', messages_after=host_message_number)
        self.assertEqual(host_notification['player_id'], g1_id)

        # Check party no longer exists
        self.get(party_url, expected_status_code=http_client.NOT_FOUND)

    # def test_create_adds_creating_player_to_party(self):
    #     # Create player for test
    #     self.auth(username="Number one user")
    #
    #     result = self.post(self.endpoints["parties"], expected_status_code=http_client.CREATED).json()
    #
    #     # Check that create and the resource returns matching data
    #     party = self.get(result['url']).json()
    #     self.assertEqual(party['url'], result['url'])
    #     self.assertEqual(result['invites_url'], party['invites_url'])
    #     self.assertEqual(result['players_url'], party['players_url'])
    #
    #     # Check there's only one player in the party, and it's the player who created it
    #     players = self.get(result['players_url'], expected_status_code=http_client.OK).json()
    #
    #     self.assertEqual(len(players), 1)
    #     self.assertEqual(players[0]['player_id'], self.player_id)
    #
    # def test_invite_players_to_party(self):
    #     # Create players for test
    #     self.auth(username="Number one user")
    #     p1 = self.player_id
    #
    #     self.auth(username="Number two user")
    #     p2 = self.player_id
    #
    #     # Create a party
    #     result = self.post(self.endpoints["parties"], expected_status_code=http_client.CREATED).json()
    #     party_url = result['url']
    #
    #     # Player 2 invites player 1 to the party
    #     invite = self.post(result['invites_url'], data={"player_id": p1}, expected_status_code=http_client.CREATED).json()
    #     invite_url = invite.get('url')
    #     self.assertIsNotNone(invite_url)
    #
    #     # Check that player 1 got the invite
    #     self.auth(username="Number one user")
    #
    #     def validator(payload):
    #         self.assertEqual(payload['party_url'], party_url)
    #         self.assertEqual(payload['invite_url'], invite_url)
    #         self.assertEqual(payload['inviting_player_id'], p2)
    #
    #     invite_notification = self.check_party_notification('invite', validator)
    #
    #     # The invite contains details about the party
    #     invite_resp = self.get(invite_notification['invite_url'], expected_status_code=http_client.OK).json()
    #     self.assertEqual(invite_resp['party_url'], party_url)
    #
    #     # Accept the invite
    #     resp = self.patch(invite_notification['invite_url'], data={}, expected_status_code=http_client.OK).json()
    #
    #     # Accepting the invite deletes it
    #     self.get(invite_notification['invite_url'], expected_status_code=http_client.NOT_FOUND)
    #
    #     # Check that the information returned matches
    #     party_player = self.get(resp['player_url']).json()
    #     self.assertEqual(party_player['player_id'], p1)
    #     party = self.get(resp['party_url']).json()
    #     self.assertEqual(len(party['players']), 2)
    #     self.assertIn(resp['player_url'], party['players'])
    #
    #     # Check that player 2 gets a notification when player 1 accepts the invite
    #     self.auth(username="Number two user")
    #
    #     def validator(payload):
    #         self.assertEqual(payload['party_url'], party_url)
    #         self.assertEqual(payload['player_id'], p1)
    #         return True
    #
    #     self.check_party_notification('player_joined', validator)
    #
    # def test_decline_invite(self):
    #     # Create players for test
    #     self.auth(username="Number one user")
    #     p1 = self.player_id
    #
    #     self.auth(username="Number two user")
    #     p2 = self.player_id
    #
    #     # Create a party
    #     result = self.post(self.endpoints["parties"], expected_status_code=http_client.CREATED).json()
    #     party_url = result['url']
    #
    #     # Player 2 invites player 1 to the party
    #     invite = self.post(result['invites_url'], data={"player_id": p1}, expected_status_code=http_client.CREATED).json()
    #     invite_url = invite.get('url')
    #
    #     # Player 1 declines the invite
    #     self.auth(username="Number one user")
    #     invite_notification = self.get_party_notification('invite')
    #     self.delete(invite_notification['invite_url'], expected_status_code=http_client.OK)
    #
    #     # Check that player 2 gets a notification when player 1 declines
    #     self.auth(username="Number two user")
    #
    #     def validator(payload):
    #         self.assertEqual(payload['party_url'], party_url)
    #         self.assertEqual(payload['player_id'], p1)
    #         return True
    #
    #     decline_notification = self.check_party_notification('invite_declined', validator)
    #     self.assertIsNotNone(decline_notification)
    #
    #     # Declining again fails
    #     self.delete(invite_notification['invite_url'], expected_status_code=http_client.NOT_FOUND)
    #
    #     # Getting declined invite details fails
    #     self.get(invite_notification['invite_url'], expected_status_code=http_client.NOT_FOUND)
    #
    # def test_invite_non_existing_player(self):
    #     # Create players for test
    #     self.auth(username="Last user")
    #     p1 = self.player_id
    #
    #     # Create a party
    #     result = self.post(self.endpoints["parties"], expected_status_code=http_client.CREATED).json()
    #     party_url = result['url']
    #
    #     # Player invites player p1 + 1 to the party (which shouldn't exist)
    #     self.post(result['invites_url'], data={"player_id": p1 + 1}, expected_status_code=http_client.BAD_REQUEST)

    # def test_invite_to_deleted_party(self):
    #     # Create players for test
    #     self.auth(username="Number two user")
    #     player_id = self.player_id
    #     self.auth(username="Number one user")
    #
    #     # Create a party
    #     result = self.post(self.endpoints["parties"], expected_status_code=http_client.CREATED).json()
    #     self.delete(result['url'])
    #
    #     # Invite a player to the now deleted party
    #     self.post(result['invites_url'], data={"player_id": player_id}, expected_status_code=http_client.NOT_FOUND)

    def get_party_notification(self, event, messages_after=None):
        notification = None
        args = "?messages_after={}".format(messages_after) if messages_after else ""
        messages = self.get(self.endpoints["my_messages"] + args).json()
        topic = messages.get('party_notification', [])
        message_number = messages_after
        for message in topic:
            message_number = message.get('message_number')
            payload = message.get('payload', {})
            if payload.get('event', None) == event:
                notification = payload
                break
        return notification, message_number

    def check_party_notification(self, event, validator):
        notification = self.get_party_notification(event)
        self.assertIsNotNone(notification)
        validator(notification)
        return notification
