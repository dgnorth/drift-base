
from flask import url_for, jsonify
from drift.blueprint import Blueprint
from flask.views import MethodView
from drift.core.extensions.urlregistry import Endpoints
import http.client as http_client
import marshmallow as ma

MATCHMAKER_MODULES = ["flexmatch"]

bp = Blueprint("matchmakers", __name__, url_prefix="/matchmakers")
endpoints = Endpoints()

def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


class MatchmakersGetResponseSchema(ma.Schema):
    class Meta:
        strict = True
    matchmakers = ma.fields.List(ma.fields.String())

@bp.route("", endpoint="list")
class MatchmakersAPI(MethodView):

    @bp.response(http_client.OK, MatchmakersGetResponseSchema)
    def get(self):
        """
        Get the available matchmakers
        """
        return jsonify(MATCHMAKER_MODULES)

@endpoints.register
def endpoint_info(*args):
    info = {
        "matchmakers": url_for("matchmakers.list", _external=True)
    }
    return info
