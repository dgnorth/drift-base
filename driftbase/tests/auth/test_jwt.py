import http
import unittest

from driftbase.utils.test_utils import BaseCloudkitTest
from drift.core.extensions.jwt import jwt_not_required, check_jwt_authorization, requires_roles
from drift.systesthelper import setup_tenant
from drift.flaskfactory import drift_app
from flask.views import MethodView
from drift.utils import get_config

ts = setup_tenant()
test_app = drift_app()

ACCESS_KEY = "ThisIsMySecret"
ROLE_NAME = "test_role"

class TestJWTAccessControl(BaseCloudkitTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        test_app.before_request(check_jwt_authorization)
        cls.app = test_app.test_client()

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
        self._setup_service_user_with_bearer_token()
        token = "non3xisting7okenbit"
        self.headers = {"Authorization": "Bearer " + token}
        # This should fail because the token is invalid
        self.put("/testapi", expected_status_code=http.HTTPStatus.UNAUTHORIZED)
        self.get("/trivialfunctions", expected_status_code=http.HTTPStatus.UNAUTHORIZED)

        self.headers = {"Authorization": "Bearer " + ACCESS_KEY}

        # This should fail as the post method requires role 'service' which we dont have
        self.post("/testapi", expected_status_code=http.HTTPStatus.UNAUTHORIZED)
        self.post("/trivialfunctions", expected_status_code=http.HTTPStatus.UNAUTHORIZED)

        # This should succeed as we have a valid token and the delete method requires our role
        self.delete("/testapi", expected_status_code=http.HTTPStatus.OK)
        self.delete("/trivialfunctions", expected_status_code=http.HTTPStatus.OK)

    @staticmethod
    def _setup_service_user_with_bearer_token():
        breakpoint()
        conf = get_config()
        user_name = "test_service_user"
        # setup access roles
        ts.get_table("access-roles").add({
            "role_name": ROLE_NAME,
            "deployable_name": conf.deployable["deployable_name"],
            "description": "a throwaway test role"
        })
        # Setup a user with an access key
        ts.get_table("users").add({
            "user_name": user_name,
            "password": "SomeVeryGoodPasswordNoOneWillGuess",
            "access_key": ACCESS_KEY,
            "is_active": True,
            "is_role_admin": False,
            "is_service": True,
            "organization_name": conf.organization["organization_name"]
        })
        # Associate the bunch.
        ts.get_table("users-acl").add({
            "organization_name": conf.organization["organization_name"],
            "user_name": user_name,
            "role_name": ROLE_NAME,
            "tenant_name": conf.tenant["tenant_name"]
        })


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
    @requires_roles(ROLE_NAME)
    def delete():
        return {}, http.HTTPStatus.OK


test_app.add_url_rule('/testapi', view_func=TestAPI.as_view('openapi'))
test_app.add_url_rule('/trivialapi', view_func=TrivialAPI.as_view('trivialapi'))


@test_app.route("/trivialfunctions")  # GET is the default method
def get_trivial():
    return {}, http.HTTPStatus.OK

@test_app.route("/trivialfunctions", methods=["PUT"])
def put_trivial():
    return {}, http.HTTPStatus.OK

@test_app.route("/trivialfunctions", methods=["POST"])
@requires_roles("service")
def post_rolecheck():
    return {}, http.HTTPStatus.OK

@test_app.route("/trivialfunctions", methods=["DELETE"])
@requires_roles(ROLE_NAME)
def delete_external_service_role():
    return {}, http.HTTPStatus.OK

@test_app.route("/openfunction")
@jwt_not_required
def get():
    return {}, http.HTTPStatus.OK



if __name__ == "__main__":
    unittest.main()
