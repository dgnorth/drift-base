import http.client as http_client
import jwt
from mock import patch, MagicMock

from drift.core.extensions.jwt import JWT_ALGORITHM
from drift.systesthelper import setup_tenant, remove_tenant
from drift.utils import get_config
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

    def test_userpass_auth_fallback(self):
        # Create or login
        data1 = {
            "username": "foo",
            "password": "bar",
            "automatic_account_creation": True
        }
        resp1 = self.post('/auth', data=data1, expected_status_code=http_client.OK).json()
        data2 = {
            "provider": "user+pass",
            "username": "foo",
            "password": "bar",
            "automatic_account_creation": True
        }
        resp2 = self.post('/auth', data=data2, expected_status_code=http_client.OK).json()
        data3 = {
            "provider": "user+pass",
            "provider_details": {
                "username": "foo",
                "password": "bar"
            },
            "automatic_account_creation": True
        }
        resp3 = self.post('/auth', data=data3, expected_status_code=http_client.OK).json()
        options = {"verify_signature": False}
        token1 = jwt.decode(resp1['token'], algorithms=[JWT_ALGORITHM], options=options)
        token2 = jwt.decode(resp2['token'], algorithms=[JWT_ALGORITHM], options=options)
        token3 = jwt.decode(resp3['token'], algorithms=[JWT_ALGORITHM], options=options)
        self.assertEqual(token1['user_id'], token2['user_id'])
        self.assertEqual(token1['player_id'], token2['player_id'])
        self.assertEqual(token1['identity_id'], token2['identity_id'])
        self.assertEqual(token1['user_id'], token3['user_id'])
        self.assertEqual(token1['player_id'], token3['player_id'])
        self.assertEqual(token1['identity_id'], token3['identity_id'])

    def test_uuid_auth_fallback(self):
        # Will be converted to user+pass
        data1 = {
            "username": "foo",
            "password": "bar",
            "automatic_account_creation": True
        }
        resp1 = self.post('/auth', data=data1, expected_status_code=http_client.OK).json()
        # Will be treated as uuid
        data2 = {
            "provider": "uuid",
            "provider_details": {
                "key": "foo",
                "secret": "bar"
            },
            "username": "foo",
            "password": "bar",
            "automatic_account_creation": True
        }
        resp2 = self.post('/auth', data=data2, expected_status_code=http_client.OK).json()
        # Will be treated as uuid
        data3 = {
            "provider": "uuid",
            "provider_details": {
                "key": "foo",
                "secret": "bar"
            },
            "automatic_account_creation": True
        }
        resp3 = self.post('/auth', data=data3, expected_status_code=http_client.OK).json()
        options = {"verify_signature": False}
        token1 = jwt.decode(resp1['token'], algorithms=[JWT_ALGORITHM], options=options)
        token2 = jwt.decode(resp2['token'], algorithms=[JWT_ALGORITHM], options=options)
        token3 = jwt.decode(resp3['token'], algorithms=[JWT_ALGORITHM], options=options)
        self.assertEqual(token1['user_id'], token2['user_id'])
        self.assertEqual(token1['player_id'], token2['player_id'])
        self.assertEqual(token1['identity_id'], token2['identity_id'])
        self.assertEqual(token1['user_id'], token3['user_id'])
        self.assertEqual(token1['player_id'], token3['player_id'])
        self.assertEqual(token1['identity_id'], token3['identity_id'])
