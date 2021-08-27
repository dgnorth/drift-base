__matchmakers__ = {"flexmatch"}

from flask import url_for, jsonify
from flask_smorest import Blueprint
from flask.views import MethodView
from drift.core.extensions.urlregistry import Endpoints

bp = Blueprint("matchmaking", __name__, url_prefix="/matchmaking", description="Discover matchmakers")
endpoints = Endpoints()

def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


@bp.route("", endpoint="list")
class MatchmakersAPI(MethodView):

    def get(self):
        """
        Get the available matchmakers
        """
        return jsonify(list(__matchmakers__))

@endpoints.register
def endpoint_info(*args):
    info = {
        "matchmaking": url_for("matchmaking.list", _external=True)
    }
    return info
