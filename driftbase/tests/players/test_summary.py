import copy

from six.moves import http_client

from drift.systesthelper import setup_tenant, remove_tenant
from driftbase.utils.test_utils import BaseCloudkitTest


def setUpModule():
    setup_tenant()


def tearDownModule():
    remove_tenant()


class SummaryTests(BaseCloudkitTest):
    def test_summary_patch(self):
        self.make_player()
        summary_url = self.endpoints["my_summary"]
        r = self.get(summary_url)
        self.assertTrue(r.json() == {})
        summary = {"gold": 100, "cement": 200, "happiness": -1, "oranges": 1}
        self.patch(summary_url, data=summary)
        r = self.get(summary_url)
        self.assertEqual(r.json(), summary)

        new_summary = copy.copy(summary)
        summary = {"gold": 200}
        self.patch(summary_url, data=summary)
        r = self.get(summary_url)
        # the summary should now be the same as before with the addition of the new data
        new_summary.update(summary)
        self.assertEqual(r.json(), new_summary)

        # check that we get a 404 if the player doesn't exist
        r = self.get("/players/999999/summary", expected_status_code=http_client.NOT_FOUND)

    def test_summary_put(self):
        self.make_player()
        summary_url = self.endpoints["my_summary"]
        summary = {"gold": 100, "cement": 200, "happiness": -1, "oranges": 1}
        self.put(summary_url, data=summary)
