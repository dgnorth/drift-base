import http.client as http_client

from drift.systesthelper import setup_tenant, remove_tenant
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
            self.post('/auth', data=data)

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
                self.post('/auth', data=data)

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

    def test_old_style_auth_with_user_pass_provider(self):
        user1 = self._auth_and_get_user(old_style_auth_with_user_pass_provider_data)
        user2 = self._auth_and_get_user(old_style_auth_with_user_pass_provider_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])

    def test_user_pass_auth_with_provider(self):
        user1 = self._auth_and_get_user(user_pass_auth_with_provider_data)
        user2 = self._auth_and_get_user(user_pass_auth_with_provider_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])

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

    def test_old_style_uuid_provider(self):
        user1 = self._auth_and_get_user(old_style_uuid_provider_data)
        user2 = self._auth_and_get_user(old_style_uuid_provider_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])

    def test_uuid_auth_with_provider(self):
        user1 = self._auth_and_get_user(uuid_auth_with_provider_data)
        user2 = self._auth_and_get_user(uuid_auth_with_provider_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])

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
        self.assertEqual(user2['identity_id'], user3['identity_id'])
        self.assertEqual(user2['user_id'], user3['user_id'])

    def test_uuid_methods_resolve_to_same_user(self):
        user1 = self._auth_and_get_user(old_style_uuid_data)
        user2 = self._auth_and_get_user(old_style_uuid_provider_data)
        user3 = self._auth_and_get_user(uuid_auth_with_provider_data)
        self.assertEqual(user1['identity_id'], user2['identity_id'])
        self.assertEqual(user1['user_id'], user2['user_id'])
        self.assertEqual(user2['identity_id'], user3['identity_id'])
        self.assertEqual(user2['user_id'], user3['user_id'])
