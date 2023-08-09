import http.client as http_client

import mock
from drift.test_helpers.systesthelper import setup_tenant, remove_tenant
from drift.utils import get_config
from mock import patch, MagicMock

from driftbase.systesthelper import DriftBaseTestCase


def setUpModule():
    setup_tenant()

    conf = get_config()

    conf.table_store.get_table('platforms').add({
        'product_name': conf.product['product_name'],
        'provider_name': 'oculus',
        "provider_details": {
            "access_token": "four",
            "sekrit": "five"
        }})

    conf.table_store.get_table('platforms').add({
        'product_name': conf.product['product_name'],
        'provider_name': 'steam',
        "provider_details": {
            "appid": 12345,
            "key": "steam key"
        }})


def tearDownModule():
    remove_tenant()


class AuthTests(DriftBaseTestCase):

    def test_oculus_authentication(self):
        # Oculus provisional authentication check
        data = {
            "provider": "oculus",
            "provider_details": {
                "provisional": True, "username": "someuser", "password": "somepass"
            }
        }
        with patch('driftbase.auth.oculus.run_ticket_validation', return_value=u'testuser'):
            self.post('/auth', data=data)

        # verify error with empty username
        data['provider_details']['username'] = ""
        self.post('/auth', data=data, expected_status_code=http_client.UNAUTHORIZED)

        # Oculus normal authentication check
        nonce = "140000003DED3A"
        data = {
            "provider": "oculus",
            "provider_details": {
                "nonce": nonce,
                "user_id": "testuser"
            }
        }
        with patch('driftbase.auth.oculus.run_ticket_validation', return_value=u'testuser'):
            token = self.post('/auth', data=data).json()['token']
            user = self.get('/', headers={'Authorization': f"BEARER {token}"}).json()['current_user']
            self.assertEqual(user['provider_user_id'], data['provider_details']['user_id'])

    def test_steam_authentication(self):
        # Steam normal authentication check
        data = {
            "provider": "steam",
            "provider_details": {
                "ticket": "tick",
                "appid": 12345,
                "steamid": "steamtester"
            }
        }
        with patch('driftbase.auth.steam._call_authenticate_user_ticket') as mock_auth:
            mock_auth.return_value.status_code = 200
            mock_auth.return_value.json = MagicMock()
            mock_auth.return_value.json.return_value = {'response': {'params': {'steamid': u'steamtester'}}}
            with patch('driftbase.auth.steam._call_check_app_ownership') as mock_own:
                mock_own.return_value.status_code = 200
                token = self.post('/auth', data=data).json()['token']
                user = self.get('/', headers={'Authorization': f"BEARER {token}"}).json()['current_user']
                self.assertEqual(user['provider_user_id'], data['provider_details']['steamid'])

    def test_steam_authentication_ignores_legacy_id(self):
        # Steam normal authentication check
        data = {
            "provider": "steam",
            "provider_details": {
                "ticket": "tick",
                "appid": 12345,
                "steam_id": "this_is_ignored_for_now"
            }
        }
        with patch('driftbase.auth.steam._call_authenticate_user_ticket') as mock_auth:
            mock_auth.return_value.status_code = 200
            mock_auth.return_value.json = MagicMock()
            mock_auth.return_value.json.return_value = {'response': {'params': {'steamid': u'steamtester'}}}
            with patch('driftbase.auth.steam._call_check_app_ownership') as mock_own:
                mock_own.return_value.status_code = 200
                self.post('/auth', data=data)

    def test_steam_authentication_must_match_steamid(self):
        # Steam failed authentication check
        data = {
            "provider": "steam",
            "provider_details": {
                "ticket": "tick",
                "appid": 12345,
                "steamid": "steamdude"
            }
        }
        with patch('driftbase.auth.steam._call_authenticate_user_ticket') as mock_auth:
            mock_auth.return_value.status_code = 200
            mock_auth.return_value.json = MagicMock()
            mock_auth.return_value.json.return_value = {'response': {'params': {'steamid': u'steamtester'}}}
            with patch('driftbase.auth.steam._call_check_app_ownership') as mock_own:
                mock_own.return_value.status_code = 200
                self.post('/auth', data=data, expected_status_code=http_client.UNAUTHORIZED)


old_style_user_pass_data = {
    'username': 'new-user',
    'password': 'test',
    'automatic_account_creation': True
}

old_style_auth_with_user_pass_provider_data = {
    'provider': 'user+pass',
    'username': 'new-user',
    'password': 'test',
    'automatic_account_creation': True
}

user_pass_auth_with_provider_data = {
    'provider': 'user+pass',
    'provider_details': {
        'username': 'new-user',
        'password': 'test',
    },
    'automatic_account_creation': True
}

old_style_uuid_data = {
    'username': 'uuid:some_hash',
    'password': 'test',
    'automatic_account_creation': True
}

old_style_uuid_provider_data = {
    'provider': 'uuid',
    'username': 'some_hash',
    'password': 'test',
    'automatic_account_creation': True
}

uuid_auth_with_provider_data = {
    'provider': 'uuid',
    'provider_details': {
        'key': 'some_hash',
        'secret': 'test',
    },
    'automatic_account_creation': True
}

class _BasePlayerAttributeTestCase(DriftBaseTestCase):
    def _old_authenticate_without_roles(self, username, password, automatic_account_creation=True):
        """ Stripped down version of the old authentication method, i.e. before we added role 'player' by default. """
        from flask import g
        from driftbase.models.db import User, UserIdentity, CorePlayer

        my_identity = g.db.query(UserIdentity).filter(UserIdentity.name == username).first()
        self.assertIsNone(my_identity)

        my_identity = UserIdentity(name=username, identity_type='')
        my_identity.set_password(password)
        my_user = g.db.query(User).filter(User.user_name == username).first()
        self.assertIsNone(my_user)

        g.db.add(my_identity)
        g.db.flush()
        identity_id = my_identity.identity_id
        my_user = g.db.query(User).get(my_identity.user_id)
        self.assertIsNone(my_user)

        my_user = User(user_name=username)
        g.db.add(my_user)
        g.db.flush()
        user_id = my_user.user_id
        my_identity.user_id = user_id
        user_id = my_user.user_id
        my_user_name = my_user.user_name
        my_player = g.db.query(CorePlayer).filter(CorePlayer.user_id == user_id).first()
        self.assertIsNone(my_player)

        my_player = CorePlayer(user_id=user_id, player_name=u"")
        g.db.add(my_player)
        g.db.flush()

        player_id = my_player.player_id
        player_name = my_player.player_name
        my_user.default_player_id = my_player.player_id
        g.db.commit()

        ret = {
            "user_name": my_user_name,
            "user_id": user_id,
            "identity_id": identity_id,
            "player_id": player_id,
            "player_name": player_name,
            "roles": [],
        }
        return ret


class PlayerRoleTestCase(_BasePlayerAttributeTestCase):

    def test_player_has_player_role(self):
        token = self.post('/auth', data=old_style_user_pass_data, expected_status_code=http_client.OK)
        user = self.get('/', headers={'Authorization': f"BEARER {token.json()['token']}"}).json()['current_user']
        self.assertIn('player', user['roles'])

    def test_existing_users_get_player_role_added(self):
        with mock.patch('driftbase.auth.authenticate.authenticate', self._old_authenticate_without_roles):
            token = self.post('/auth', data=old_style_user_pass_data, expected_status_code=http_client.OK)
            user = self.get('/', headers={'Authorization': f"BEARER {token.json()['token']}"}).json()['current_user']
            self.assertNotIn('player', user['roles'])

        token = self.post('/auth', data=old_style_user_pass_data, expected_status_code=http_client.OK)
        user = self.get('/', headers={'Authorization': f"BEARER {token.json()['token']}"}).json()['current_user']
        self.assertIn('player', user['roles'])


class PlayerUUIDTestCase(_BasePlayerAttributeTestCase):
    def test_player_has_uuid(self):
        token = self.post('/auth', data=old_style_user_pass_data, expected_status_code=http_client.OK).json()
        user = self.get('/', headers={'Authorization': f"BEARER {token['token']}"}).json()['current_user']
        self.assertIn('player_uuid', user)

    def test_existing_users_get_uuid_added(self):
        with mock.patch('driftbase.auth.authenticate.authenticate', self._old_authenticate_without_roles):
            token = self.post('/auth', data=old_style_user_pass_data, expected_status_code=http_client.OK).json()
            user = self.get('/', headers={'Authorization': f"BEARER {token['token']}"}).json()['current_user']
            self.assertNotIn('player_uuid', user)

        token = self.post('/auth', data=old_style_user_pass_data, expected_status_code=http_client.OK).json()
        user = self.get('/', headers={'Authorization': f"BEARER {token['token']}"}).json()['current_user']
        self.assertIn('player_uuid', user)


class BaseAuthTestCase(DriftBaseTestCase):
    def _auth_and_get_user(self, data):
        token1 = self.post('/auth', data=data, expected_status_code=http_client.OK)
        user1 = self.get('/', headers={'Authorization': f"BEARER {token1.json()['token']}"}).json()['current_user']
        return user1


class UserPassAuthTests(BaseAuthTestCase):
    def test_old_style_user_pass_auth(self):
        user1 = self._auth_and_get_user(old_style_user_pass_data)
        user2 = self._auth_and_get_user(old_style_user_pass_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])
        self.assertEqual(user1['provider_user_id'], user2['provider_user_id'])
        self.assertEqual(user1['provider_user_id'], user1['user_id'])

    def test_old_style_auth_with_user_pass_provider(self):
        user1 = self._auth_and_get_user(old_style_auth_with_user_pass_provider_data)
        user2 = self._auth_and_get_user(old_style_auth_with_user_pass_provider_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])
        self.assertEqual(user1['provider_user_id'], user1['user_id'])

    def test_user_pass_auth_with_provider(self):
        user1 = self._auth_and_get_user(user_pass_auth_with_provider_data)
        user2 = self._auth_and_get_user(user_pass_auth_with_provider_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])
        self.assertEqual(user1['provider_user_id'], user1['user_id'])

    def test_user_pass_with_missing_properties(self):
        data = old_style_user_pass_data
        del data['username']
        self.post('/auth', data=data, expected_status_code=http_client.BAD_REQUEST)
        data = old_style_user_pass_data
        del data['password']
        self.post('/auth', data=data, expected_status_code=http_client.BAD_REQUEST)

        data = old_style_auth_with_user_pass_provider_data
        del data['username']
        self.post('/auth', data=data, expected_status_code=http_client.BAD_REQUEST)
        data = old_style_auth_with_user_pass_provider_data
        del data['password']
        self.post('/auth', data=data, expected_status_code=http_client.BAD_REQUEST)

        data = user_pass_auth_with_provider_data
        del data['provider_details']['username']
        self.post('/auth', data=data, expected_status_code=http_client.BAD_REQUEST)
        data = user_pass_auth_with_provider_data
        del data['provider_details']['password']
        self.post('/auth', data=data, expected_status_code=http_client.BAD_REQUEST)

    def test_old_style_uuid(self):
        user1 = self._auth_and_get_user(old_style_uuid_data)
        user2 = self._auth_and_get_user(old_style_uuid_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])
        self.assertEqual(user1['provider_user_id'], user2['provider_user_id'])
        self.assertEqual(user1['provider_user_id'], old_style_uuid_data['username'].split(':')[1])

    def test_old_style_uuid_provider(self):
        user1 = self._auth_and_get_user(old_style_uuid_provider_data)
        user2 = self._auth_and_get_user(old_style_uuid_provider_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])
        self.assertEqual(user1['provider_user_id'], user2['provider_user_id'])
        self.assertEqual(user1['provider_user_id'], old_style_uuid_provider_data["username"])

    def test_uuid_auth_with_provider(self):
        user1 = self._auth_and_get_user(uuid_auth_with_provider_data)
        user2 = self._auth_and_get_user(uuid_auth_with_provider_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])
        self.assertEqual(user1['provider_user_id'], user2['provider_user_id'])
        self.assertEqual(user1['provider_user_id'], uuid_auth_with_provider_data['provider_details']['key'])

    def test_uuid_with_missing_properties(self):
        data = old_style_uuid_data
        del data['username']
        self.post('/auth', data=data, expected_status_code=http_client.BAD_REQUEST)
        data = old_style_uuid_data
        del data['password']
        self.post('/auth', data=data, expected_status_code=http_client.BAD_REQUEST)

        data = old_style_uuid_provider_data
        del data['username']
        self.post('/auth', data=data, expected_status_code=http_client.BAD_REQUEST)
        data = old_style_uuid_provider_data
        del data['password']
        self.post('/auth', data=data, expected_status_code=http_client.BAD_REQUEST)

        data = uuid_auth_with_provider_data
        del data['provider_details']['key']
        self.post('/auth', data=data, expected_status_code=http_client.BAD_REQUEST)
        data = uuid_auth_with_provider_data
        del data['provider_details']['secret']
        self.post('/auth', data=data, expected_status_code=http_client.BAD_REQUEST)

    def test_user_pass_methods_resolve_to_same_user(self):
        user1 = self._auth_and_get_user(old_style_user_pass_data)
        user2 = self._auth_and_get_user(old_style_auth_with_user_pass_provider_data)
        user3 = self._auth_and_get_user(user_pass_auth_with_provider_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])
        self.assertEqual(user1['provider_user_id'], user2['provider_user_id'])
        self.assertEqual(user2['identity_id'], user3['identity_id'])
        self.assertEqual(user2['user_id'], user3['user_id'])
        self.assertEqual(user2['provider_user_id'], user3['provider_user_id'])

    def test_uuid_methods_resolve_to_same_user(self):
        user1 = self._auth_and_get_user(old_style_uuid_data)
        user2 = self._auth_and_get_user(old_style_uuid_provider_data)
        user3 = self._auth_and_get_user(uuid_auth_with_provider_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])
        self.assertEqual(user1['provider_user_id'], user2['provider_user_id'])
        self.assertEqual(user2['identity_id'], user3['identity_id'])
        self.assertEqual(user2['user_id'], user3['user_id'])
        self.assertEqual(user2['provider_user_id'], user3['provider_user_id'])
