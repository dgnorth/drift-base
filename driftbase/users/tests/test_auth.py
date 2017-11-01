# -*- coding: utf-8 -*-

from mock import patch, MagicMock
import httplib

from drift.systesthelper import setup_tenant, remove_tenant, DriftBaseTestCase
from driftconfig.util import _sticky_ts


def setUpModule():
    conf = setup_tenant()

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


public_test_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAYQDjhJCi86VWOc" \
    "zW59s2Zc/yZUXt/N33Z7Lstpjk4V6SXPU6vhriPjySV7DWucLjwct9q+Ovz" \
    "fL6Hv81BuKmK60Qkco5ldMruJGXjT0nTuLjOCvfD9aG61GmK4pPXKcJ7vE=" \
    " unittest@dg-api.com"


class AuthTests(DriftBaseTestCase):

    def test_oculus_authentication(self):
        # Oculus provisional authentication check
        data = {
            "provider": "oculus",
            "provider_details": {
                "provisional": True, "username": "someuser", "password": "somepass"
            }
        }
        with patch('drift.auth.oculus.run_ticket_validation', return_value=u'testuser'):
            self.post('/auth', data=data)

        # verify error with empty username
        data['provider_details']['username'] = ""
        self.post('/auth', data=data, expected_status_code=httplib.UNAUTHORIZED)

        # Oculus normal authentication check
        nonce = "140000003DED3A"
        data = {
        "provider": "oculus",
            "provider_details": {
                "nonce": nonce,
                "user_id": "testuser"
            }
        }
        with patch('drift.auth.oculus.run_ticket_validation', return_value=u'testuser'):
            self.post('/auth', data=data)

    def test_steam_authentication(self):
        # Steam normal authentication check
        data = {
            "provider": "steam",
            "provider_details": {
                "ticket": "tick",
                "appid": 12345,
                "steam_id": "steamdude"
            }
        }
        with patch('drift.auth.steam._call_authenticate_user_ticket') as mock_auth:
            mock_auth.return_value.status_code = 200
            mock_auth.return_value.json = MagicMock()
            mock_auth.return_value.json.return_value = {'response': {'params': {'steamid': u'steamtester'}}}
            with patch('drift.auth.steam._call_check_app_ownership') as mock_own:
                mock_own.return_value.status_code = 200
                self.post('/auth', data=data)
