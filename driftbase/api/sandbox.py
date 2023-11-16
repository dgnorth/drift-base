import logging
import marshmallow as ma
import http.client as http_client

from flask import url_for, g
from flask.views import MethodView
from drift.blueprint import Blueprint
from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints

from driftbase import sandbox

log = logging.getLogger(__name__)

bp = Blueprint("sandbox", __name__, url_prefix="/sandbox")
endpoints = Endpoints()


def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)
    app.messagebus.register_consumer(sandbox.process_placement_event, "gamelift_queue")
    endpoints.init_app(app)


@bp.route('', endpoint='placements')
class SandboxAPI(MethodView):

    class SandboxGetResponse(ma.Schema):
        pass

    @bp.response(http_client.OK, SandboxGetResponse)
    def get(self):
        return {}  #TODO: return list of placements


@bp.route('/<int:location_id>', endpoint='placement')
class ExperienceAPI(MethodView):

    class SandboxPutSchema(ma.Schema):
        queue = ma.fields.String(required=False)

    class SandboxPutResponse(ma.Schema):
        placement_id = ma.fields.String()

    @bp.arguments(SandboxPutSchema)
    @bp.response(http_client.CREATED, SandboxPutResponse)
    def put(self, args, location_id):
        return dict(
            placement_id=sandbox.handle_player_session_request(
                location_id,
                current_user["player_id"],
                args.get("queue")
            )
        )

@endpoints.register
def endpoint_info(*args):
    template_url = url_for("sandbox.placement", location_id="99999", _external=True)
    template_url = template_url.replace("/99999", "/{location_id}")
    ret = {
        "sandbox": url_for("sandbox.placements", _external=True),
        "template_sandbox": template_url,
    }
    return ret
