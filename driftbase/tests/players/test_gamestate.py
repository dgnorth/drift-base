import unittest
import datetime
import json

from six.moves import http_client

from drift.systesthelper import setup_tenant, remove_tenant, uuid_string, DriftBaseTestCase


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


def _generate_dummy_gamestate(numkeys=100):
    ret = {}
    for i in range(numkeys):
        key = uuid_string()
        ret[key] = []
        for i in range(numkeys):
            ret[key].append({uuid_string(): uuid_string()})
    string = json.dumps(ret)
    return string


# @patch.dict('from drift.core.extensions.celery.celery.conf', {'CELERY_ALWAYS_EAGER': True})
class GameStateTests(DriftBaseTestCase):
    """
    Tests for the /players/x/gamestate endpoint
    """

    def get_latest_journal_id(self, journal_url):
        r = self.get(journal_url + "?rows=1")
        if not r.json():
            return 0
        else:
            return int(r.json()[0]["journal_id"])

    def get_timestamp(self):
        return datetime.datetime.utcnow().isoformat() + "Z"

    def get_journal_entry(self, journal_url, action=None, journal_id=None,
                          timestamp=None, details=None, steps=None):
        entry = {"action": action or "test.%s" % uuid_string(),
                 "journal_id": journal_id if journal_id is not None else
                 self.get_latest_journal_id(journal_url) + 1,
                 "timestamp": timestamp or self.get_timestamp()
                 }
        if details:
            entry["details"] = json.dumps(details)
        if steps:
            entry["steps"] = json.dumps(steps)
        return entry

    def write_journal_entry(self, journal_url, action=None, journal_id=None,
                            timestamp=None, details=None, steps=None):
        """helper to push a fake journal entry to the backend and
        return the journal_id of the new entry"""
        # TODO: Possibly move to the gamestate test class
        entry = self.get_journal_entry(journal_url, action, journal_id, timestamp, details, steps)
        r = self.post(journal_url, [entry], expected_status_code=http_client.CREATED)
        return r.json()[0]["journal_id"]

    def test_gamestate_basic(self):
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        resp = self.get(player_url)
        gamestates_url = resp.json()["gamestates_url"]
        journal_url = resp.json()["journal_url"]

        # new players should not have a gamestate
        r = self.get(gamestates_url)
        self.assertEqual(len(r.json()), 0)
        gamestate_data = {"hello": "world"}
        journal_id = self.write_journal_entry(journal_url, journal_id=1)
        data = {
            "gamestate": gamestate_data,
            "journal_id": journal_id,
        }
        gamestate_url = gamestates_url + "/test"
        r = self.put(gamestate_url, data=data)
        self.assertEqual(r.json()["version"], 1)
        self.assertEqual(r.json()["journal_id"], journal_id)
        old_modify_date = r.json()["modify_date"]

        # now we should have a gamestate
        r = self.get(gamestates_url)
        self.assertEqual(len(r.json()), 1)

        # write a new gamestate
        journal_id += 1
        journal_id = self.write_journal_entry(journal_url, journal_id=journal_id)

        data = {
            "gamestate": gamestate_data,
            "journal_id": journal_id,
        }
        r = self.put(gamestate_url, data=data)
        self.assertEqual(r.json()["version"], 2)
        self.assertEqual(r.json()["journal_id"], journal_id)
        self.assertGreater(r.json()["modify_date"], old_modify_date)

    def test_gamestate_nojournal(self):
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        resp = self.get(player_url)
        gamestates_url = resp.json()["gamestates_url"]
        gamestate_data = {"hello": "world"}
        data = {
            "gamestate": gamestate_data,
        }
        gamestate_url = gamestates_url + "/test"
        r = self.put(gamestate_url, data=data)
        r = self.get(gamestates_url)
        self.assertEqual(len(r.json()), 1)
        gamestate_url = r.json()[0]["gamestate_url"]
        r = self.get(gamestate_url)
        self.assertIsNone(r.json()["journal_id"])

        # You can explicitly set journal_id to null as the caller
        data = {
            "gamestate": gamestate_data,
            "journal_id": None
        }
        gamestate_url = gamestates_url + "/test"
        r = self.put(gamestate_url, data=data)
        r = self.get(gamestate_url)
        self.assertIsNone(r.json()["journal_id"])

        # journal_id 0 is also valid for 'no journal entry'
        data = {
            "gamestate": gamestate_data,
            "journal_id": 0
        }
        gamestate_url = gamestates_url + "/test"
        r = self.put(gamestate_url, data=data)
        r = self.get(gamestate_url)
        self.assertIsNone(r.json()["journal_id"])

    def test_gamestate_multiple(self):
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        resp = self.get(player_url)
        gamestates_url = resp.json()["gamestates_url"]
        num = 5
        for i in range(num):
            gamestate_data = {"hello": "world", "number": i}
            data = {
                "gamestate": gamestate_data,
            }
            gamestate_url = gamestates_url + "/multiple:%s" % i
            r = self.put(gamestate_url, data=data)
        r = self.get(gamestates_url)
        self.assertEqual(len(r.json()), num)
        for i, entry in enumerate(r.json()):
            self.assertEqual(entry["namespace"], "multiple:%s" % i)
            r = self.get(entry["gamestate_url"])
            d = r.json()
            self.assertEqual(d["data"]["number"], i)

    def test_gamestate_delete(self):
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        resp = self.get(player_url)
        gamestates_url = resp.json()["gamestates_url"]
        gamestate_data = {"hello": "world"}
        data = {
            "gamestate": gamestate_data,
        }
        gamestate_url = gamestates_url + "/test"
        r = self.put(gamestate_url, data=data)
        r = self.get(gamestates_url)
        self.assertEqual(len(r.json()), 1)

        self.delete(gamestate_url)

        r = self.get(gamestates_url)
        self.assertEqual(len(r.json()), 0)

    def test_gamestate_update(self):
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        resp = self.get(player_url)
        gamestates_url = resp.json()["gamestates_url"]
        gamestate_data = {"hello": "world"}
        data = {
            "gamestate": gamestate_data,
        }
        gamestate_url = gamestates_url + "/test"
        r = self.put(gamestate_url, data=data)
        r = self.get(gamestate_url)
        old_version = r.json()["version"]

        new_gamestate_data = {"something": ["very", "different"]}
        data = {
            "gamestate": new_gamestate_data,
        }
        r = self.put(gamestate_url, data=data)

        r = self.get(gamestate_url)
        self.assertEqual(r.json()["data"], new_gamestate_data)
        self.assertEqual(r.json()["version"], old_version + 1)

    def test_gamestate_history(self):
        self.auth(username=uuid_string())
        player_url = self.endpoints["my_player"]
        resp = self.get(player_url)
        gamestates_url = resp.json()["gamestates_url"]
        first_data = {"first": "entry"}
        data = {
            "gamestate": first_data,
        }
        gamestate_url = gamestates_url + "/test"
        r = self.put(gamestate_url, data=data)
        r = self.get(gamestate_url)
        history_url = r.json()["gamestatehistory_url"]
        r = self.get(history_url)
        self.assertEqual(len(r.json()), 1)

        # add another entry
        second_data = {"second": "entry"}
        data = {
            "gamestate": second_data,
        }
        r = self.put(gamestate_url, data=data)
        r = self.get(gamestate_url)
        history_url = r.json()["gamestatehistory_url"]
        r = self.get(history_url)
        history_list = r.json()
        self.assertTrue(isinstance(history_list, list))
        self.assertEqual(len(history_list), 2)

        r = self.get(history_list[0]["gamestatehistoryentry_url"])
        self.assertEqual(r.json()["data"], second_data)

        r = self.get(history_list[1]["gamestatehistoryentry_url"])
        self.assertEqual(r.json()["data"], first_data)


if __name__ == '__main__':
    unittest.main()
