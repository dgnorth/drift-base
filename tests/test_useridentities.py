import http.client as http_client

from drift.systesthelper import uuid_string
from driftbase.systesthelper import DriftBaseTestCase
from tests import has_key


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
