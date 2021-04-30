import http
import unittest

from driftbase.utils.test_utils import BaseCloudkitTest
from drift.core.extensions.jwt import verify_token, jwt_not_required, current_user, check_jwt_authorization
from drift.systesthelper import setup_tenant
from drift.flaskfactory import drift_app
from flask.views import MethodView


ts = setup_tenant()
test_app = drift_app()

class TestJWTAccessControl(BaseCloudkitTest):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        test_app.before_request(check_jwt_authorization)
        cls.app = test_app.test_client()

    def test_trivial_function(self):
        self.post("/trivialfunction", expected_status_code=http.HTTPStatus.METHOD_NOT_ALLOWED)
        self.get("/trivialfunction", expected_status_code=http.HTTPStatus.UNAUTHORIZED)
        self.make_player()
        self.get("/trivialfunction", expected_status_code=http.HTTPStatus.OK)
        self.put("/trivialfunction", expected_status_code=http.HTTPStatus.OK)

    def test_trivial_method(self):
        self.post("/trivialapi", expected_status_code=http.HTTPStatus.METHOD_NOT_ALLOWED)
        self.get("/trivialapi", expected_status_code=http.HTTPStatus.UNAUTHORIZED)
        self.make_player()
        self.get("/trivialapi", expected_status_code=http.HTTPStatus.OK)

    def test_open_api(self):
        self.get("/openapi", expected_status_code=http.HTTPStatus.OK)

    def test_open_function(self):
        self.get("/openfunction", expected_status_code=http.HTTPStatus.OK)



class TrivalAPI(MethodView):

    def get(self):
        return {}, http.HTTPStatus.OK


class OpenAPI(MethodView):
    no_jwt_check = ["GET"]

    @staticmethod
    def get():
        return {}, http.HTTPStatus.OK


test_app.add_url_rule('/openapi', view_func=OpenAPI.as_view('openapi'))
test_app.add_url_rule('/trivialapi', view_func=TrivalAPI.as_view('trivialapi'))


@test_app.route("/trivialfunction")  # GET is the default method
def get_trivial():
    return {}, http.HTTPStatus.OK

@test_app.route("/trivialfunction", methods=["PUT"])
def put_trivial():
    return {}, http.HTTPStatus.OK

@test_app.route("/openfunction")
@jwt_not_required
def get_open():
    return {}, http.HTTPStatus.OK



if __name__ == "__main__":

    unittest.main()
