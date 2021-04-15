import uuid
from unittest.mock import patch

from six.moves import http_client

from driftbase import parties
from driftbase.utils.test_utils import BaseCloudkitTest


class PartiesTest(BaseCloudkitTest):
    """
    Tests for the /parties endpoint
    """

    def make_user_name(self, name):
        # For performance reasons the test DB is not cleared between tests
        # so to ensure a clean slate for some tests, we must be able to generate fresh users
        return "{}.{}".format(str(uuid.uuid4())[:8], name)

    def make_named_player(self, username):
        self.auth(username=username)
        self.patch(self.endpoints['my_player'], data={"name": username})

    def test_party_invite_creates_party_after_one_player_accepts(self):
        # Create players for test
        host_user = self.make_user_name("Host")
        guest_user_1 = self.make_user_name("Guest 1")
        guest_user_2 = self.make_user_name("Guest 2")

        self.make_named_player(guest_user_1)
        g1_id = self.player_id
        self.make_named_player(guest_user_2)
        g2_id = self.player_id
        self.make_named_player(host_user)
        host_id = self.player_id

        # Invite g1 to a new party
        invite = self.post(self.endpoints["party_invites"], data={'player_id': g1_id},
                           expected_status_code=http_client.CREATED).json()

        # Check g1 gets a notification about the invite
        self.auth(username=guest_user_1)
        g1_notification, g1_message_number = self.get_party_notification('invite')
        self.assertEqual(g1_notification['inviting_player_name'], host_user)
        self.assertEqual(g1_notification['inviting_player_id'], host_id)
        self.assertEqual(g1_notification['invite_url'], invite['url'])

        # Accept the invite, and check that both players are in the party
        accept = self.patch(g1_notification['invite_url'], data={'inviter_id': host_id}).json()
        party = self.get(accept['party_url']).json()
        self.check_expected_players_in_party(party, [(host_id, host_user), (g1_id, guest_user_1)])

        # Check g1 doesn't get a notification about joining
        g1_notification, g1_message_number = self.get_party_notification('player_joined',
                                                                         messages_after=g1_message_number)
        self.assertIsNone(g1_notification)

        # Check host gets a notification about the new party
        self.auth(username=host_user)
        host_notification, host_message_number = self.get_party_notification('player_joined')
        self.assertEqual(host_notification['party_url'], accept['party_url'])
        self.assertEqual(host_notification['party_url'], accept['party_url'])

        # Invite g2 as well
        invite = self.post(self.endpoints["party_invites"], data={'player_id': g2_id},
                           expected_status_code=http_client.CREATED).json()

        # Check g2 gets a notification about the invite
        self.auth(username=guest_user_2)
        g2_notification, g2_message_number = self.get_party_notification('invite')
        self.assertEqual(g2_notification['inviting_player_name'], host_user)
        self.assertEqual(g2_notification['inviting_player_id'], host_id)
        self.assertEqual(g2_notification['invite_url'], invite['url'])

        # Accept the invite, and check that all three players are in the party
        accept = self.patch(g2_notification['invite_url'], data={'inviter_id': host_id}).json()
        party = self.get(accept['party_url']).json()
        self.check_expected_players_in_party(party, [(host_id, host_user), (g1_id, guest_user_1), (g2_id, guest_user_2)])

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

    def test_invite_non_existing_player(self):
        # Create players for test
        host_user = self.make_user_name("Host")
        self.auth(username=host_user)
        host_id = self.player_id
        self.post(self.endpoints["party_invites"], data={'player_id': host_id + 1},
                  expected_status_code=http_client.BAD_REQUEST).json()

    def test_invite_self(self):
        # Create players for test
        host_user = self.make_user_name("Host")
        self.auth(username=host_user)
        host_id = self.player_id
        self.post(self.endpoints["party_invites"], data={'player_id': host_id},
                  expected_status_code=http_client.BAD_REQUEST).json()

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
        self.delete(g1_notification['invite_url'],
                    expected_status_code=http_client.NO_CONTENT)

        # Check host gets a notification about the player declining
        self.auth(username=host_user)
        host_notification, host_message_number = self.get_party_notification('invite_declined')
        self.assertEqual(host_notification['player_id'], g1_id)

        # Check trying to accept the deleted invite fails
        self.patch(g1_notification['invite_url'], data={'inviter_id': host_id},
                   expected_status_code=http_client.NOT_FOUND)

    def test_leave_party(self):
        # Create players for test
        host_user = self.make_user_name("Host")
        guest_user_1 = self.make_user_name("Guest 1")
        guest_user_2 = self.make_user_name("Guest 2")

        self.make_named_player(guest_user_1)
        g1_id = self.player_id
        self.make_named_player(guest_user_2)
        g2_id = self.player_id
        self.make_named_player(host_user)
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
        self.delete(g2_accept['member_url'], expected_status_code=http_client.NO_CONTENT)

        # Check host gets a notification
        self.auth(username=host_user)
        host_notification, host_message_number = self.get_party_notification('player_joined')
        party_url = host_notification['party_url']
        host_notification, host_message_number = self.get_party_notification('player_left',
                                                                             messages_after=host_message_number)
        self.assertEqual(host_notification['player_id'], g2_id)

        # Check g1 gets a notification
        self.auth(username=guest_user_1)
        g1_notification, g1_message_number = self.get_party_notification('player_left')
        self.assertEqual(g1_notification['player_id'], g2_id)

        # Check party still contains host and g1
        party = self.get(party_url).json()
        self.check_expected_players_in_party(party, [(host_id, host_user), (g1_id, guest_user_1)])

        # Leave the party with g1
        self.delete(g1_accept['member_url'], expected_status_code=http_client.NO_CONTENT)

        # Check host gets a notification
        self.auth(username=host_user)
        host_notification, host_message_number = self.get_party_notification('player_left',
                                                                             messages_after=host_message_number)
        self.assertEqual(host_notification['player_id'], g1_id)

        # Check party no longer exists
        self.get(party_url, expected_status_code=http_client.NOT_FOUND)

    def test_outstanding_invites_will_form_a_new_party_if_the_host_is_left_in_a_disbanded_party(self):
        # Create players for test
        host_user = self.make_user_name("Host")
        guest_user_1 = self.make_user_name("Guest 1")
        guest_user_2 = self.make_user_name("Guest 2")

        self.make_named_player(guest_user_1)
        g1_id = self.player_id
        self.make_named_player(guest_user_2)
        g2_id = self.player_id
        self.make_named_player(host_user)
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

        # Leave the party with g1
        self.delete(g1_accept['member_url'], expected_status_code=http_client.NO_CONTENT)

        # Verify the party is gone as there's only one player left
        self.auth(username=host_user)
        host_notification, host_message_number = self.get_party_notification('player_joined')
        self.get(host_notification['party_url'], expected_status_code=http_client.NOT_FOUND)
        host_notification, host_message_number = self.get_party_notification('player_left')
        self.assertIsNotNone(host_notification)
        host_notification, host_message_number = self.get_party_notification('disbanded')
        self.assertIsNotNone(host_notification)

        # Accept the g2 invite
        self.auth(username=guest_user_2)
        g2_notification, g2_message_number = self.get_party_notification('invite')
        g2_accept = self.patch(g2_notification['invite_url'], data={'inviter_id': host_id}).json()
        self.assertNotEqual(g1_accept['party_url'], g2_accept['party_url'])

        # Check host and g2 are in the party
        party = self.get(g2_accept['party_url']).json()
        self.check_expected_players_in_party(party, [(host_id, host_user), (g2_id, guest_user_2)])

    def test_leaving_party_invalidates_outstanding_invites_from_same_player(self):
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

        # Leave the party with host
        self.auth(username=host_user)
        host_notification, host_message_number = self.get_party_notification('player_joined')
        self.delete(host_notification['inviting_member_url'], expected_status_code=http_client.NO_CONTENT)

        self.auth(username=guest_user_2)
        g2_notification, g2_message_number = self.get_party_notification('invite')
        self.patch(g2_notification['invite_url'], data={'inviter_id': host_id}, expected_status_code=http_client.NOT_FOUND)

    def test_party_is_capped_at_n_members(self):
        player_limit = 3
        with patch.object(parties, 'get_max_players_per_party', return_value=player_limit) as mock:
            # Create players for test
            guest_ids = []
            guest_names = []
            for guest_name in [self.make_user_name(f"Guest_{i}") for i in range(player_limit)]:
                self.make_named_player(username=guest_name)
                guest_ids.append(self.player_id)
                guest_names.append(guest_name)
            host_user_name = self.make_user_name("Host")
            self.make_named_player(host_user_name)
            host_id = self.player_id

            # Invite all the guests
            invites = [self.post(self.endpoints["party_invites"], data={'player_id': guest_id}, expected_status_code=http_client.CREATED).json() for guest_id in guest_ids]
            # First 3 accept the invite
            for guest_name in guest_names[:-1]:
                self.auth(username=guest_name)
                notification, message_number = self.get_party_notification('invite')
                self.patch(notification['invite_url'], data={'inviter_id': host_id}, expected_status_code=http_client.OK).json()

            # Now attempt to accept as the 5th party member
            self.auth(username=guest_names[-1])
            notification, message_number = self.get_party_notification('invite')
            self.patch(notification['invite_url'], data={'inviter_id': host_id}, expected_status_code=http_client.CONFLICT).json()

    def check_expected_players_in_party(self, party, expected_players):
        """
        Check that all players in expected_players are in the party, and nobody else
        """
        players = [(entry['id'], entry['player_name']) for entry in party['members']]
        self.assertEqual(len(players), len(expected_players))
        for expected_player in expected_players:
            self.assertIn(expected_player, players)

    def get_party_notification(self, event, messages_after=None):
        """
        Return the first notification matching the event
        """
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
