import contextlib
import http
import unittest

from driftbase.utils.test_utils import BaseCloudkitTest
from drift.core.extensions.jwt import jwt_not_required, check_jwt_authorization, requires_roles
from flask.views import MethodView
from drift.utils import get_config

ACCESS_KEY = "ThisIsMySecret"
ROLE_NAME = "test_role"
USER_NAME = "test_service_user"

class TestJWTAccessControl(BaseCloudkitTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.drift_app.before_request(check_jwt_authorization)
        cls.drift_app.add_url_rule('/testapi', view_func=TestAPI.as_view('openapi'))
        cls.drift_app.add_url_rule('/trivialapi', view_func=TrivialAPI.as_view('trivialapi'))

        cls.drift_app.add_url_rule("/trivialfunctions", view_func=get_trivial, methods=["GET"])
        cls.drift_app.add_url_rule("/trivialfunctions", view_func=put_trivial, methods=["PUT"])
        cls.drift_app.add_url_rule("/trivialfunctions", view_func=post_rolecheck, methods=["POST"])
        cls.drift_app.add_url_rule("/openfunction", view_func=get_no_check, methods=["GET"])

    def test_trivial_functions(self):
        self.post("/trivialfunctions", expected_status_code=http.HTTPStatus.UNAUTHORIZED)
        self.put("/trivialfunctions", expected_status_code=http.HTTPStatus.UNAUTHORIZED)
        self.get("/trivialfunctions", expected_status_code=http.HTTPStatus.UNAUTHORIZED)
        self.make_player()
        self.get("/trivialfunctions", expected_status_code=http.HTTPStatus.OK)
        self.put("/trivialfunctions", expected_status_code=http.HTTPStatus.OK)

    def test_open_function(self):
        self.get("/openfunction", expected_status_code=http.HTTPStatus.OK)

    def test_trivial_methods(self):
        self.post("/trivialapi", expected_status_code=http.HTTPStatus.METHOD_NOT_ALLOWED)
        self.get("/trivialapi", expected_status_code=http.HTTPStatus.UNAUTHORIZED)
        self.make_player()
        self.get("/trivialapi", expected_status_code=http.HTTPStatus.OK)

    def test_mixed_api(self):
        self.get("/testapi", expected_status_code=http.HTTPStatus.OK)
        self.put("/testapi", expected_status_code=http.HTTPStatus.UNAUTHORIZED)
        self.make_player()
        self.get("/testapi", expected_status_code=http.HTTPStatus.OK)
        self.put("/testapi", expected_status_code=http.HTTPStatus.OK)

    def test_jti_auth(self):
        self.make_player()
        jti = self.jti
        self.token = self.jti = None
        self.headers = {"Authorization": "JTI " + jti}
        self.put("/testapi", expected_status_code=http.HTTPStatus.OK)
        self.headers = {"Authorization": "JTI " + jti + "junk"}
        self.put("/testapi", expected_status_code=http.HTTPStatus.UNAUTHORIZED)

    def test_jwt_auth(self):
        self.make_player()
        token = self.token
        self.token = self.jti = None
        self.headers = {"Authorization": "JWT " + token}
        self.put("/testapi", expected_status_code=http.HTTPStatus.OK)
        self.headers = {"Authorization": "JWT " + token + "junk"}
        self.put("/testapi", expected_status_code=http.HTTPStatus.UNAUTHORIZED)

    def test_service_user_bearer_token_auth(self):
        with self._managed_bearer_token_user():
            token = "non3xisting7okenbit"
            self.headers = {"Authorization": "Bearer " + token}
            # This should fail because the token is invalid
            self.put("/testapi", expected_status_code=http.HTTPStatus.UNAUTHORIZED)
            self.get("/trivialfunctions", expected_status_code=http.HTTPStatus.UNAUTHORIZED)

            self.headers = {"Authorization": "Bearer " + ACCESS_KEY}

            # This should succeed as we have a valid token and the delete method requires no roles
            self.delete("/testapi", expected_status_code=http.HTTPStatus.OK)

            # This should fail as the post method requires role 'service' which we dont have
            self.post("/testapi", expected_status_code=http.HTTPStatus.UNAUTHORIZED)
            self.post("/trivialfunctions", expected_status_code=http.HTTPStatus.UNAUTHORIZED)


    @contextlib.contextmanager
    def _managed_bearer_token_user(self):
        try:
            yield self._setup_service_user_with_bearer_token()
        finally:
            self._remove_service_user_with_bearer_token()

    @staticmethod
    def _setup_service_user_with_bearer_token():
        # FIXME: Might be cleaner to use patching instead of populating the actual config. The upside with using config
        #  is that it exposes the intended use case more clearly
        conf = get_config()
        ts = conf.table_store
        # Setup user
        ts.get_table("users").add({
            "user_name": USER_NAME,
            "tenant_name": conf.tenant["tenant_name"]
        })
        # Setup access key
        ts.get_table("access-keys").add({
            "user_name": USER_NAME,
            "tenant_name": conf.tenant["tenant_name"],
            "access_key": ACCESS_KEY,
        })
        # Setup credentials
        ts.get_table("client-credentials").add({
            "user_name": USER_NAME,
            "tenant_name": conf.tenant["tenant_name"],
            "client_id": "test_client",
            "client_secret": ACCESS_KEY
        })

    @staticmethod
    def _remove_service_user_with_bearer_token():
        conf = get_config()
        ts = conf.table_store
        ts.get_table("client-credentials").remove({"user_name": USER_NAME, "tenant_name": conf.tenant["tenant_name"]})
        ts.get_table("access-keys").remove({"user_name": USER_NAME, "tenant_name": conf.tenant["tenant_name"]})
        ts.get_table("users").remove({"user_name": USER_NAME, "tenant_name": conf.tenant["tenant_name"]})


class TrivialAPI(MethodView):

    def get(self):
        return {}, http.HTTPStatus.OK


class TestAPI(MethodView):
    no_jwt_check = ["GET"]

    @staticmethod
    def get():
        return {}, http.HTTPStatus.OK

    @staticmethod
    def put():
        return {}, http.HTTPStatus.OK

    @staticmethod
    @requires_roles("service")
    def post():
        return {}, http.HTTPStatus.OK

    @staticmethod
    def delete():
        return {}, http.HTTPStatus.OK


def get_trivial():
    return {}, http.HTTPStatus.OK

def put_trivial():
    return {}, http.HTTPStatus.OK

@requires_roles("service")
def post_rolecheck():
    return {}, http.HTTPStatus.OK

@jwt_not_required
def get_no_check():
    return {}, http.HTTPStatus.OK



if __name__ == "__main__":
    unittest.main()
