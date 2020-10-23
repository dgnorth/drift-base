"""
    Utilities functions assisting the system tests
"""
from six.moves import http_client
from drift.systesthelper import uuid_string, DriftBaseTestCase


class BaseCloudkitTest(DriftBaseTestCase):

    def make_player(self, username=None):
        username = username or uuid_string()
        self.auth(username=username)
        player_url = self.endpoints["my_player"]
        r = self.get(player_url)
        player_name = "Player #%s" % self.player_id
        self.patch(player_url, data={"name": player_name})

        # start by getting a client session (this should be in utils!)
        clients_url = self.endpoints["clients"]
        data = {
            "client_type": "client_type",
            "build": "build",
            "platform_type": "platform_type",
            "app_guid": "app_guid",
            "version": "version"
        }
        r = self.post(clients_url, data=data, expected_status_code=http_client.CREATED)
        new_jti = r.json()["jti"]
        self.headers["Authorization"] = "JTI %s" % new_jti
        r = self.get("/")
        self.endpoints = r.json()["endpoints"]
        return username


class BaseMatchTest(BaseCloudkitTest):

    def _create_machine(self):
        if "service" not in self.current_user["roles"]:
            raise RuntimeError("Only service users can call this method")
        data = {"realm": "aws",
                "instance_name": "awsinstance",
                "placement": "placement",
                "instance_type": "instance_type",
                "instance_id": "instance_id",
                "public_ip": "8.8.8.8",
                }
        resp = self.post("/machines", data=data, expected_status_code=http_client.CREATED)
        url = resp.json()["url"]
        resp = self.get(url)
        return resp.json()

    def _create_server(self, machine_id):
        if "service" not in self.current_user["roles"]:
            raise RuntimeError("Only service users can call this method")
        data = {"machine_id": machine_id,
                "version": "version",
                "public_ip": "8.8.8.8",
                "port": 50000,
                "command_line": "command_line",
                "command_line_custom": "command_line_custom",
                "pid": 666,
                "status": "active",
                "image_name": "image_name",
                "branch": "develop",
                "commit_id": "commit_id",
                "process_info": {"process_info": "yes"},
                "details": {"details": "yes"},
                "ref": "test/testing",
                }
        resp = self.post("/servers", data=data, expected_status_code=http_client.CREATED)
        return resp.json()

    def _create_match(self, server_id=None, expected_status_code=http_client.CREATED, **kwargs):
        if "service" not in self.current_user["roles"]:
            raise RuntimeError("Only service users can call this method")
        if not server_id:
            machine = self._create_machine()
            server = self._create_server(machine["machine_id"])
            server_id = server["server_id"]

        data = {"server_id": server_id,
                "status": "idle",
                "map_name": "map_name",
                "game_mode": "game_mode",
                "max_players": 2,
                }
        data.update(**kwargs)
        resp = self.post("/matches", data=data, expected_status_code=expected_status_code)
        if resp:
            resp = self.get(resp.json()["url"])
            return resp.json()
        return None

    def _filter_matches(self, resp, match_ids):
        return [m for m in resp.json() if m["match_id"] in match_ids]
