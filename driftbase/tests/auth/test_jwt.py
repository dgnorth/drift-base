import http
import unittest

from driftbase.utils.test_utils import BaseCloudkitTest
from drift.core.extensions.jwt import jwt_not_required, check_jwt_authorization
from drift.systesthelper import setup_tenant
from drift.flaskfactory import drift_app
from flask.views import MethodView


ts = setup_tenant()
test_app = drift_app()

class TestJWTAccessControl(BaseCloudkitTest):
    @classmethod
    def setUpClass(cls):
        # NOTE TO SELF:  The only reason for doing this setup here is that the systesthelper is part of the drift library
        # and I can't be arsed to modify the lib and release a new version atm.
        #  IMO systesthelper should set just set the drift_app up as a global at the same time as the tenant
        # so tests can add routes to it on the fly
        super().setUpClass()
        test_app.before_request(check_jwt_authorization)
        cls.app = test_app.test_client()

    def test_trivial_functions(self):
        self.post("/trivialfunctions", expected_status_code=http.HTTPStatus.METHOD_NOT_ALLOWED)
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

    def test_bearer_token_auth(self):
        token = "aRandomString"
        self.headers = {"Authorization": "Bearer: permanent:" + token}
        self.put("/testapi", expected_status_code=http.HTTPStatus.OK)

class TrivialAPI(MethodView):

    def get(self):
        return {}, http.HTTPStatus.OK


class TestAPI(MethodView):
    no_jwt_check = ["GET"]

    @staticmethod
    def get():
        return {}, http.HTTPStatus.OK

    def put(self):
        return {}, http.HTTPStatus.OK


test_app.add_url_rule('/testapi', view_func=TestAPI.as_view('openapi'))
test_app.add_url_rule('/trivialapi', view_func=TrivialAPI.as_view('trivialapi'))


@test_app.route("/trivialfunctions")  # GET is the default method
def get_trivial():
    return {}, http.HTTPStatus.OK

@test_app.route("/trivialfunctions", methods=["PUT"])
def put_trivial():
    return {}, http.HTTPStatus.OK

@test_app.route("/openfunction")
@jwt_not_required
def get():
    return {}, http.HTTPStatus.OK



if __name__ == "__main__":
    unittest.main()
