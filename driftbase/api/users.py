import logging
from six.moves import http_client

from flask import url_for, g
from flask_restplus import Namespace, Resource, abort
from flask.views import MethodView
import marshmallow as ma
from flask_rest_api import Api, Blueprint
from marshmallow_sqlalchemy import ModelSchema
from drift.core.extensions.urlregistry import Endpoints
from driftbase.utils import url_player, url_user
from driftbase.models.db import User, CorePlayer, UserIdentity

log = logging.getLogger(__name__)


endpoints = Endpoints()

bp = Blueprint('users', 'Users', url_prefix='/users', description='User management')

class PlayerSchema(ModelSchema):
    class Meta:
        model = CorePlayer
        exclude = ('num_logons', )
    player_url = ma.fields.Str(description="Hello")

class UserSchema(ModelSchema):

    class Meta:
        model = User
    user_url = ma.fields.Str(description="Hello")
    client_url = ma.fields.Str()
    user_url = ma.fields.Str()
    players = ma.fields.List(ma.fields.Nested(PlayerSchema))
    identities = ma.fields.List(ma.fields.Dict())

class UserRequestSchema(ma.Schema):

    class Meta:
        strict = True
        ordered = True

def drift_init_extension(app, api, **kwargs):
    endpoints.init_app(app)

    api.spec.definition('User', schema=UserSchema)

    api.register_blueprint(bp)


#@namespace.route('', endpoint='users')
@bp.route('', endpoint='users')
class UsersListAPI(MethodView):
    @bp.response(UserSchema(many=True))
    def get(self):
        """List Users

        Return users, just the most recent 10 records with no paging or anything I'm afraid.
        """
        ret = []
        users = g.db.query(User).order_by(-User.user_id).limit(10)
        for row in users:
            user = {
                "user_id": row.user_id,
                "user_url": url_for('users.user', user_id=row.user_id, _external=True)
            }
            ret.append(user)
        return ret


#@namespace.route('/<int:user_id>', endpoint='user')
@bp.route('/<int:user_id>', endpoint='user')
class UsersAPI(Resource):
    """

    """
    @bp.response(UserSchema(many=False))
    def get(self, user_id):
        """A single user

        Return a user by ID
        """
        user = g.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            abort(http_client.NOT_FOUND)

        data = user.as_dict()
        data["client_url"] = None
        #if user.client_id:
        #    data["client_url"] = url_for("client", client_id=user.client_id, _external=True)
        players = g.db.query(CorePlayer).filter(CorePlayer.user_id == user_id)
        data["players"] = players
        identities = g.db.query(UserIdentity).filter(UserIdentity.user_id == user_id)
        data["identities"] = identities

        return data


@endpoints.register
def endpoint_info(current_user):
    ret = {"users": url_for("users", _external=True), }
    ret["my_user"] = None
    if current_user:
        ret["my_user"] = url_for("user", user_id=current_user["user_id"], _external=True)
    return ret
