import http.client as http_client
import datetime
from drift.systesthelper import uuid_string
from driftbase.systesthelper import DriftBaseTestCase
from tests import has_key
from unittest import mock


class UserIdentitiesTest(DriftBaseTestCase):
    def test_identities_missing_user(self):
        # authenticate with gamecenter
        username_gamecenter = "gamecenter:G:%s" % uuid_string()
        self.auth(username=username_gamecenter)
        headers_gamecenter = self.headers
        user_identities_url = self.endpoints["user_identities"]

        r = self.get("/").json()
        gamecenter_user_id = r["current_user"]["user_id"]
        gamecenter_jti = r["current_user"]["jti"]

        # authenticate with device
        self.auth(username="device_%s" % uuid_string())
        r = self.get("/").json()
        device_user_id = r["current_user"]["user_id"]
        device_jti = r["current_user"]["jti"]

        # switch to gamecenter user
        self.headers = headers_gamecenter

        data = {
            "link_with_user_id": -1,
            "link_with_user_jti": device_jti
        }
        self.post(user_identities_url, data=data, expected_status_code=http_client.NOT_FOUND)

    def test_identities_wrong_user(self):
        # authenticate with gamecenter
        username_gamecenter = "gamecenter:G:%s" % uuid_string()
        self.auth(username=username_gamecenter)
        headers_gamecenter = self.headers
        user_identities_url = self.endpoints["user_identities"]

        r = self.get("/").json()
        gamecenter_user_id = r["current_user"]["user_id"]
        gamecenter_jti = r["current_user"]["jti"]

        # authenticate with device
        self.auth(username="device_%s" % uuid_string())
        r = self.get("/").json()
        other_user_id = r["current_user"]["user_id"]

        # authenticate with device again
        self.auth(username="device_%s" % uuid_string())
        r = self.get("/").json()
        device_user_id = r["current_user"]["user_id"]
        device_jti = r["current_user"]["jti"]

        # switch to gamecenter user
        self.headers = headers_gamecenter

        data = {
            "link_with_user_id": other_user_id,
            "link_with_user_jti": device_jti
        }
        r = self.post(user_identities_url, data=data, expected_status_code=http_client.BAD_REQUEST)
        self.assertIn("User does not match JWT user", r.json()['error']["description"])

    def test_identities_add_gamecenter(self):
        """
        Use case #1:
        Player starts the game for the first time. His Game Center id has
        no user account association. The
        game client will automatically associate his Game Center id with his
        current device user account.

        ```device_jwt, device_jti = POST /auth {"username": "deviceid:12345"}
        gamecenter_jwt, gamecenter_jti =
            POST /auth {"username": "G:398475", "provider_details": ...}

        if gamecenter_jwt.user_id == 0:
            # Use case 1
            Authorization: JTI gamecenter_jti
            POST /user-identities
                {"link_with_user_jti": device_jti, "link_with_user_id": device_jwt.user_id}
        """
        # authenticate with gamecenter
        username_gamecenter = "gamecenter:G:%s" % uuid_string()
        self.auth(username=username_gamecenter)
        headers_gamecenter = self.headers
        user_identities_url = self.endpoints["user_identities"]

        r = self.get("/").json()
        gamecenter_user_id = r["current_user"]["user_id"]
        gamecenter_jti = r["current_user"]["jti"]

        # authenticate with device
        self.auth(username="device_%s" % uuid_string())
        r = self.get("/").json()
        device_user_id = r["current_user"]["user_id"]
        device_jti = r["current_user"]["jti"]

        # switch to gamecenter user
        self.headers = headers_gamecenter

        data = {"link_with_user_id": device_user_id,
                "link_with_user_jti": device_jti
                }
        self.post(user_identities_url, data=data)

        # I should not be able to associate the same user again
        self.post(user_identities_url, data=data, expected_status_code=http_client.BAD_REQUEST)

        # reauthenticate and ensure the user is associated with the gamecenter account
        self.auth(username=username_gamecenter)
        r = self.get("/").json()
        new_gamecenter_user_id = r["current_user"]["user_id"]
        self.assertEqual(new_gamecenter_user_id, device_user_id)

        # I should not be able to associate the same user again (now with a proper jwt)
        self.post(user_identities_url, data=data, expected_status_code=http_client.BAD_REQUEST)

    def test_identities_already_claimed(self):
        # authenticate with gamecenter
        username_gamecenter = "gamecenter:G:%s" % uuid_string()
        self.auth(username=username_gamecenter)
        headers_gamecenter = self.headers
        user_identities_url = self.endpoints["user_identities"]

        r = self.get("/").json()
        gamecenter_user_id = r["current_user"]["user_id"]
        gamecenter_jti = r["current_user"]["jti"]

        # authenticate with device
        self.auth(username="device_%s" % uuid_string())
        r = self.get("/").json()
        device_user_id = r["current_user"]["user_id"]
        device_jti = r["current_user"]["jti"]

        # switch to gamecenter user
        self.headers = headers_gamecenter

        data = {"link_with_user_id": device_user_id,
                "link_with_user_jti": device_jti
                }
        self.post(user_identities_url, data=data)

        # authenticate with a new gamecenter user
        username_other_gamecenter = "gamecenter:G:%s" % uuid_string()
        self.auth(username=username_other_gamecenter)

        r = self.get("/").json()
        other_gamecenter_user_id = r["current_user"]["user_id"]
        other_gamecenter_jti = r["current_user"]["jti"]

        r = self.post(user_identities_url, data=data, expected_status_code=http_client.FORBIDDEN)
        self.assertEqual(r.json()['error']["code"], "linked_account_already_claimed")

    def test_identities_get(self):
        # authenticate with gamecenter
        username = "testing:%s" % uuid_string()
        self.auth(username=username)
        user_identities_url = self.endpoints["user_identities"]

        r = self.get(user_identities_url + "?name=bla")
        self.assertEqual(len(r.json()), 0)
        r = self.get(user_identities_url + "?name=%s" % username)
        self.assertEqual(len(r.json()), 1)
        self.assertEqual(r.json()[0]["player_id"], self.player_id)

        r = self.get(user_identities_url + "?player_id=9999999")
        self.assertEqual(len(r.json()), 0)
        r = self.get(user_identities_url + "?player_id=%s" % self.player_id)
        self.assertEqual(len(r.json()), 1)
        self.assertEqual(r.json()[0]["player_id"], self.player_id)
        self.assertEqual(r.json()[0]["identity_name"], username)

        self.assertFalse(has_key(r.json(), "password_hash"))

    def test_get_identity_by_wallet_id(self):
        # authenticate with wallet/ethereum
        ethereum_data = {
            'provider': 'ethereum',
            'provider_details': {
                'signer': '0x854Cc1Ce8e826e514f1dD8127f9D0AF689f181A9',
                'message': '{\r\n\t"message": "Authorize for Drift login",\r\n\t"timestamp": "2022-01-12T08:12:59.787Z"\r\n}',
                'signature': '0x5b0bf23f6cccf4315f561a04aef11b60dadced91bc17ac168db14b467851d4010349a8d3fbaec28c4671eb27ba7a8160900b51c2ded5137b3a9804881f3ee32c1c',
            }
        }
        with mock.patch('driftbase.auth.ethereum.utcnow') as now:
            now.return_value = datetime.datetime.fromisoformat('2022-01-12T08:12:59.787') + datetime.timedelta(seconds=5)
            with mock.patch('driftbase.auth.ethereum.get_provider_config') as config:
                config.return_value = dict()
                token = self.post('/auth', data=ethereum_data, expected_status_code=http_client.OK).json()['token']
                headers = {'Authorization': f'Bearer {token}'}
                response = self.get('/', headers=headers).json()
                identities_url = response['endpoints']['user_identities']
                user = response['current_user']
                identity_string = f"ethereum:{ethereum_data['provider_details']['signer']}"
                identity = self.get(f'{identities_url}?name={identity_string}', headers=headers).json()
                self.assertEqual(len(identity), 1)
                self.assertEqual(identity[0]['identity_name'], identity_string)
                self.assertEqual(identity[0]['player_id'], user['player_id'])
                self.assertEqual(identity[0]['player_name'], user['player_name'])
