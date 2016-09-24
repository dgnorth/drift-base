# -*- coding: utf-8 -*-

import httplib

from drift.systesthelper import setup_tenant, remove_tenant
from driftbase.utils.test_utils import BaseCloudkitTest


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


class TicketsTests(BaseCloudkitTest):
    def test_tickets_create(self):
        self.make_player()
        r = self.get(self.endpoints["my_player"])
        player = r.json()
        data = {
            "ticket_type": "bla",
            "external_id": "test.1"
        }
        self.post(player["tickets_url"], data=data, expected_status_code=httplib.UNAUTHORIZED)

        self.auth_service()
        r = self.post(player["tickets_url"], data=data, expected_status_code=httplib.CREATED)
        self.assertEquals(r.json()["ticket_url"], r.headers["location"])
        r = self.get(r.json()["ticket_url"])
        self.assertIsNone(r.json()["used_date"])

    def test_tickets_errors(self):
        self.make_player()
        r = self.get(self.endpoints["my_player"])
        player = r.json()
        data = {
            "ticket_type": "bla",
            "external_id": "test.1"
        }

        old_headers = self.headers

        self.auth_service()
        r = self.post(player["tickets_url"], data=data, expected_status_code=httplib.CREATED)
        ticket_url = r.json()["ticket_url"]

        # make a new player to verify that he can not access the ticket
        self.make_player()

        r = self.get(ticket_url, expected_status_code=httplib.METHOD_NOT_ALLOWED)
        self.assertIn("not your player", r.json()["error"]["description"])
        r = self.patch(ticket_url, data={"journal_id": 1},
                       expected_status_code=httplib.METHOD_NOT_ALLOWED)
        self.assertIn("not your player", r.json()["error"]["description"])

        # switch to the owning player
        self.headers = old_headers

        # try to get an invalid ticket
        r = self.get(player["tickets_url"] + "/999999", expected_status_code=httplib.NOT_FOUND)
        r = self.patch(player["tickets_url"] + "/999999", data={"journal_id": 1},
                       expected_status_code=httplib.NOT_FOUND)

        # claim the ticket twice

        data = {"journal_id": 10}
        r = self.patch(ticket_url, data=data)

        data = {"journal_id": 10}
        r = self.patch(ticket_url, data=data, expected_status_code=httplib.NOT_FOUND)
        self.assertIn("has already been claimed", r.json()["error"]["description"])

    def test_tickets_claim(self):
        self.make_player()
        r = self.get(self.endpoints["my_player"])
        player = r.json()
        data = {
            "ticket_type": "bla",
            "external_id": "test.1"
        }

        old_headers = self.headers

        self.auth_service()
        r = self.post(player["tickets_url"], data=data, expected_status_code=httplib.CREATED)
        ticket_url = r.json()["ticket_url"]

        # switch to the player
        self.headers = old_headers

        r = self.get(r.json()["ticket_url"])

        data = {"journal_id": 10}
        r = self.patch(ticket_url, data=data)
