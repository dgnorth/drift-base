# -*- coding: utf-8 -*-

import datetime
import unittest
import random
import json
from mock import patch
from dateutil import parser

from six.moves import http_client

from drift.systesthelper import setup_tenant, remove_tenant, uuid_string, DriftBaseTestCase

MIN_ENTRIES = 0


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


# patch celery to run its tasks inproc
#@patch.dict('drift.core.extensions.celery.celery.conf', {'CELERY_ALWAYS_EAGER': True})
class JournalTests(DriftBaseTestCase):
    """
    Tests for the /players/x/journal endpoints
    """
    player_url = None
    journal_url = None

    def init_player(self):
        self.auth(username=uuid_string())
        self.player_url = self.endpoints["my_player"]
        resp = self.get(self.player_url)
        self.gamestates_url = resp.json()["gamestates_url"]
        self.journal_url = resp.json()["journal_url"]

    def get_latest_journal_id(self):
        r = self.get(self.journal_url + "?rows=1")
        if not r.json():
            return 0
        else:
            return int(r.json()[0]["journal_id"])

    def get_timestamp(self):
        return datetime.datetime.utcnow().isoformat() + "Z"

    def get_journal_entry(self, action=None, journal_id=None, timestamp=None,
                          details=None, steps=None):
        entry = {"action": action or "test.%s" % uuid_string(),
                 "journal_id": journal_id if journal_id is not None
                 else self.get_latest_journal_id() + 1,
                 "timestamp": timestamp or self.get_timestamp()
                 }
        if details:
            entry["details"] = json.dumps(details)
        if steps:
            entry["steps"] = json.dumps(steps)
        return entry

    def test_journal_newplayer(self):
        self.init_player()

        # we should start off with an empty journal
        r = self.get(self.journal_url)
        self.assertTrue(len(r.json()) == MIN_ENTRIES)

    def test_journal_gamestate(self):
        # start a gamestate and ensure that the right journal entries are written
        # note: might belong in gamestate tests
        self.init_player()

        data = self.get_journal_entry()
        details = {"my dict": "details"}
        data["details"] = json.dumps(details)
        r = self.post(self.journal_url, [data], expected_status_code=http_client.CREATED)
        journal_id = r.json()[0]["journal_id"]

        gamestate_data = {"journal gamestate": "test"}
        gamestate_url = self.gamestates_url + "/default"
        r = self.put(gamestate_url, data={"gamestate": gamestate_data, "journal_id": journal_id})
        r = self.get(self.journal_url)
        actions = set([j["action_type_name"] for j in r.json()])
        self.assertGreater(len(actions), 0)

    def test_journal_rollback(self):
        self.init_player()

        # rollback a new journal entry without a home base
        data = [self.get_journal_entry()]
        r = self.post(self.journal_url, data, expected_status_code=http_client.CREATED)
        journal_id = r.json()[0]["journal_id"]

        rollback_entry = self.get_journal_entry(action="journal.rollback",
                                                journal_id=journal_id + 1)
        rollback_entry["rollback_to_journal_id"] = journal_id
        rollback_entry["details"] = json.dumps({"rollback_to_journal_id": journal_id})

        r = self.post(self.journal_url, [rollback_entry], expected_status_code=http_client.CREATED)
        journal_id = r.json()[0]["journal_id"]

        # persist the journal entry into a gamestate
        gamestate_data = {"journal gamestate": "test"}
        gamestate_url = self.gamestates_url + "/default"
        r = self.put(gamestate_url, data={"gamestate": gamestate_data, "journal_id": journal_id})

        # ensure we cannot rollback past the journal entry now
        r = self.post(self.journal_url, [rollback_entry], expected_status_code=http_client.BAD_REQUEST)

        # add a new journal entry
        journal_id += 1
        data[0]["journal_id"] = journal_id
        r = self.post(self.journal_url, data, expected_status_code=http_client.CREATED)
        journal_id = r.json()[0]["journal_id"]

        # we should be able to roll it back this one because it's
        # not been persisted into gamestate yet
        rollback_entry = self.get_journal_entry(action="journal.rollback",
                                                journal_id=journal_id + 1)
        rollback_entry["rollback_to_journal_id"] = journal_id - 1
        rollback_entry["details"] = json.dumps({"rollback_to_journal_id": journal_id})

        r = self.post(self.journal_url, [rollback_entry], expected_status_code=http_client.CREATED)

        # Rolling it back again should be fine and produce a new rollback entry
        rollback_entry["journal_id"] += 1
        r = self.post(self.journal_url, [rollback_entry], expected_status_code=http_client.CREATED)

        # Make sure we cannot write a rolled-back journal entry into a gamestate
        gamestate_data = {"journal gamestate": "test"}
        r = self.put(gamestate_url, data={"gamestate": json.dumps(gamestate_data),
                     "journal_id": journal_id}, expected_status_code=http_client.BAD_REQUEST)

        # Roll back a few entries and ensure they are not returned from
        # a GET to /journals except if asked for
        journal_id = rollback_entry["journal_id"]
        rollback_to_journal_id = journal_id
        for i in range(10):
            data = [self.get_journal_entry(journal_id=journal_id + 1)]
            r = self.post(self.journal_url, data, expected_status_code=http_client.CREATED)
            journal_id = r.json()[0]["journal_id"]

        rollback_entry["journal_id"] = journal_id + 1
        rollback_entry["rollback_to_journal_id"] = rollback_to_journal_id
        rollback_entry["details"] = json.dumps({"rollback_to_journal_id": rollback_to_journal_id})
        r = self.post(self.journal_url, [rollback_entry], expected_status_code=http_client.CREATED)

        # if we don't specify a condition the GET should ignore the deleted entries
        r = self.get(self.journal_url + "?rows=2")
        self.assertEqual(r.json()[0]["journal_id"], rollback_entry["journal_id"])
        self.assertEqual(r.json()[1]["journal_id"], rollback_entry["rollback_to_journal_id"])

        # we get back deleted entries if asking for them
        r = self.get(self.journal_url + "?rows=2&include_deleted=1")
        self.assertEqual(r.json()[0]["journal_id"], rollback_entry["journal_id"])
        self.assertEqual(r.json()[1]["journal_id"], rollback_entry["journal_id"] - 1)

    def test_journal_details(self):
        self.init_player()

        # test putting some arbitrary data in with the journal
        data = self.get_journal_entry()
        details = {"my dict": "details"}
        data["details"] = json.dumps(details)
        r = self.post(self.journal_url, [data], expected_status_code=http_client.CREATED)
        journal_entry_url = r.json()[0]["url"]
        r = self.get(journal_entry_url)
        self.assertDictEqual(r.json()["details"], details)

    def test_journal_steps(self):
        self.init_player()

        data = self.get_journal_entry()
        steps = [{"name": "buy.stuff", "cost": 1000},
                 {"name": "place.stuff", "x": 1, "y": 2, "z": 3}]
        data["steps"] = json.dumps(steps)
        r = self.post(self.journal_url, [data], expected_status_code=http_client.CREATED)
        journal_entry_url = r.json()[0]["url"]
        r = self.get(journal_entry_url)
        self.assertListEqual(r.json()["steps"], steps)

    def test_journal_write(self):
        self.init_player()

        # write a journal entry and check if it made it in
        data = [self.get_journal_entry()]
        r = self.post(self.journal_url, data, expected_status_code=http_client.CREATED)
        self.assertIsInstance(r.json(), list)
        self.assertIsInstance(r.json()[0], dict)
        journal_entry_url = r.json()[0]["url"]
        r = self.get(journal_entry_url)
        self.assertEqual(r.json()["action_type_name"], data[0]["action"])

        r = self.get(self.journal_url)
        self.assertTrue(len(r.json()) == MIN_ENTRIES + 1)

    def test_journal_multiple(self):
        self.init_player()

        NUM_ENTRIES = 10

        # write multiple journal entries in the same call
        data = []
        for i in range(1, NUM_ENTRIES + 1):
            data.append(self.get_journal_entry("multitest.%s" % i, i))

        r = self.post(self.journal_url, data,
                      expected_status_code=http_client.CREATED)
        self.assertEqual(len(r.json()), NUM_ENTRIES)

        # the next 10 entries will be randomly shuffled. The server should be able to
        # insert them into the db in sequence if they are submitted together
        r = self.get(self.journal_url + "?rows=1")
        journal_id = r.json()[0]["journal_id"] + 1
        data = []
        lst = range(journal_id, journal_id + NUM_ENTRIES)
        random.shuffle(lst)
        for i in lst:
            data.append(self.get_journal_entry("multitest.randomorder.%s" % i, i))

        r = self.post(self.journal_url, data,
                      expected_status_code=http_client.CREATED)
        self.assertEqual(len(r.json()), NUM_ENTRIES)

        # we should have a total of 20 entries in the journal now plus the initial ones
        r = self.get(self.journal_url + "?rows=1000")
        self.assertEqual(len(r.json()), NUM_ENTRIES * 2 + MIN_ENTRIES)

    def test_journal_journalid(self):
        self.init_player()

        # test passing in a journal_id
        r = self.get(self.journal_url + "?rows=1")
        # no journals to start off with
        self.assertEqual(len(r.json()), 0)
        last_journal_id = 0
        journal_id = last_journal_id + 1

        r = self.post(self.journal_url, [self.get_journal_entry(journal_id=journal_id)],
                      expected_status_code=http_client.CREATED)
        self.assertEqual(r.json()[0]["journal_id"], journal_id)

        # we should be able to write a journal entry which skips some entries in between
        r = self.post(self.journal_url, [self.get_journal_entry(journal_id=journal_id + 11)],
                      expected_status_code=http_client.CREATED)
        journal_id = journal_id + 11
        r = self.get(self.journal_url + "?rows=1")
        self.assertEqual(r.json()[0]["journal_id"], journal_id)

        # if no journal_id is passed in we should get a jsonschema error
        r = self.post(self.journal_url, [{"action": "my.journal.test"}],
                      expected_status_code=http_client.BAD_REQUEST)

        r = self.get(self.journal_url + "?rows=1")
        self.assertEqual(r.json()[0]["journal_id"], journal_id)

        # if the same journal_id is sent again we should get an error
        r = self.post(self.journal_url, [self.get_journal_entry(journal_id=journal_id)],
                      expected_status_code=http_client.BAD_REQUEST)
        self.assertIn("out of sequence", r.json()["error"]["description"])

        r = self.get(self.journal_url + "?rows=1")
        self.assertEqual(r.json()[0]["journal_id"], journal_id)

        # if an older journal_id is sent again we should get an error
        journal_id += 1
        r = self.post(self.journal_url, [self.get_journal_entry(journal_id=journal_id)],
                      expected_status_code=http_client.CREATED)
        r = self.get(self.journal_url + "?rows=1")
        self.assertEqual(r.json()[0]["journal_id"], journal_id)

        r = self.post(self.journal_url, [self.get_journal_entry(journal_id=journal_id - 1)],
                      expected_status_code=http_client.BAD_REQUEST)
        self.assertIn("out of sequence", r.json()["error"]["description"])
        r = self.get(self.journal_url + "?rows=1")
        self.assertEqual(r.json()[0]["journal_id"], journal_id)

    def test_journal_timestamp(self):
        self.init_player()

        # use a timestamp supplied by the sender as well as journal_id
        timestamp = self.get_timestamp()
        journal_id = self.get_latest_journal_id() + 1
        entry = {"action": "journal.with.timestamp",
                 "journal_id": journal_id,
                 "timestamp": timestamp,
                 }
        r = self.post(self.journal_url, [entry], expected_status_code=http_client.CREATED)

        r = self.get(r.json()[0]["url"])

        timestamp_received = parser.parse(r.json()["timestamp"])
        timestamp_expected = parser.parse(timestamp)
        self.assertEqual(timestamp_received, timestamp_expected)
        journal_id += 1
        entry = {"action": "journal.with.timestamp",
                 "journal_id": journal_id,
                 "timestamp": timestamp,
                 "client_current_time": timestamp,
                 }
        r = self.post(self.journal_url, [entry], expected_status_code=http_client.CREATED)


if __name__ == '__main__':
    unittest.main()
