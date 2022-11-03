import http.client as http_client

from drift.systesthelper import setup_tenant, remove_tenant

from driftbase.utils.test_utils import BaseCloudkitTest


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


class PlayerGroupsTest(BaseCloudkitTest):

    def test_playergroups(self):

        self.auth()

        def pg_url(group_name):
            return self.endpoints["my_player_groups"].replace('{group_name}', group_name)

        # Check access control. Other peoples groups are unaccessible unless one has service role
        # or provides appropriate secret key.

        # First create the user group and remember its secret key.
        self.auth(username='user_owning_a_group')
        public_url = pg_url('public_group')
        group_owner_id = self.user_id
        r = self.put(public_url, data={'player_ids': [self.player_id]})
        secret = r.json()['secret']

        # Now log on as a different user and test access restrictions
        self.auth(username='user_accessing_someone_elses_group')
        # Just in case: Make sure we are logged on as a different user
        self.assertTrue(group_owner_id != self.user_id)
        # Without secret, expect FORBIDDEN
        r = self.get(public_url, expected_status_code=http_client.FORBIDDEN)
        self.assertIn("'player_id' does not match current user.", r.json()['error']["description"])
        r = self.get(public_url + '?secret={}'.format(secret), expected_status_code=http_client.OK)
        self.auth_service()
        # No secret required if I am a service
        r = self.get(public_url, expected_status_code=http_client.OK)

        self.auth(username='normal_user')

        # Group name must be correctly formatted
        r = self.get(pg_url('bad%20format'), expected_status_code=http_client.BAD_REQUEST)
        self.assertIn("'group_name' must match regex", r.json()['error']["description"])

        # Properly formatted query but no record
        r = self.get(pg_url('not_found'), expected_status_code=http_client.NOT_FOUND)
        self.assertIn("No player group named 'not_found' exists for player",
                      r.json()['error']["description"])

        # Create three players for test
        self.auth(username="user_no_1")
        self.auth(username="user_no_2")
        self.auth(username="user_no_3")

        # Create a group using identity_id for user 1, and my current player id, which is user 3.
        data = {
            'identity_names': ['user_no_1'],
            'player_ids': [self.player_id],
        }
        r = self.put(pg_url('my_friends'), data=data, expected_status_code=http_client.OK)
        pg = r.json()
        self.assertEqual(len(pg['players']), 2)

        # Make sure both entries are in there
        identities = [row['identity_name'] for row in pg['players']]
        self.assertIn('user_no_1', identities)
        self.assertIn('user_no_3', identities)

        # Fetch the data again and compare
        r = self.get(pg_url('my_friends'))
        self.assertEqual(r.json(), pg)

        # Make sure duplicates are eliminated
        data = {
            'identity_names': ['user_no_3'],
            'player_ids': [self.player_id],
        }
        r = self.put(pg_url('no_duplicates'), data=data, expected_status_code=http_client.OK)
        pg = r.json()
        self.assertEqual(len(pg['players']), 1)

        # Test empty groups
        r = self.put(pg_url('empty'), data={'player_ids': []})
        self.assertEqual(len(r.json()['players']), 0)
        r = self.put(pg_url('not_found'), data={'player_ids': [123456],
                     'identity_names': ['nobody']})
        self.assertEqual(len(r.json()['players']), 0)

    def test_players_with_group(self):

        self.make_player(username="Number one user")
        p1 = self.player_id
        self.make_player(username="Number two user")
        p2 = self.player_id
        self.make_player(username="Number three user")

        # Filter on player group. Create a group with player one and two
        pg_url = self.endpoints["my_player_groups"].replace('{group_name}', 'my_friends')
        self.put(pg_url, data={'player_ids': [p1, p2]}, expected_status_code=http_client.OK)
        players = self.get(self.endpoints["players"] + "?player_group=my_friends").json()
        self.assertTrue(len(players) == 2)
        self.assertIn(players[0]['player_id'], [p1, p2])
        self.assertIn(players[1]['player_id'], [p1, p2])

        self.assertTrue(players[0]["is_online"])
        self.assertTrue(players[1]["is_online"])

        # Make sure unknown player group returns 404
        players = self.get("/players?player_group=no_such_group",
                           expected_status_code=http_client.NOT_FOUND)

        # Make sure filtering on empty player group returns an empty list
        pg_url = self.endpoints["my_player_groups"].replace('{group_name}', 'empty_group')
        self.put(pg_url, data={'player_ids': [123456]}, expected_status_code=http_client.OK)
        players = self.get(self.endpoints["players"] + "?player_group=empty_group").json()
        self.assertEqual(len(players), 0)
