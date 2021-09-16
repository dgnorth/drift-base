import http.client as http_client

from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import match_placements
from drift.utils import get_config
import uuid
import contextlib

class TestMatchPlacements(BaseCloudkitTest):
    def test_my_match_placement(self):
        with patch.object(match_placements, "get_player_match_placement", return_value={"placement_id": "123456"}):
            self.make_player()
            self.assertIn("my_match_placement", self.endpoints)
