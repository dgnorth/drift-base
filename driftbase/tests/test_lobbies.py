import http.client as http_client

from driftbase.utils.test_utils import BaseCloudkitTest
from unittest.mock import patch
from driftbase import flexmatch, lobbies
from drift.utils import get_config
import uuid
import contextlib

REGION = "eu-west-1"

class TestLobbies(BaseCloudkitTest):
    def test_my_lobby(self):
        with patch.object(lobbies, "get_player_lobby", return_value={"lobby_id": "123456"}):
            self.make_player()
            self.assertIn("my_lobby", self.endpoints)
            self.assertIn("my_lobby_members", self.endpoints)
            self.assertIn("my_lobby_member", self.endpoints)
