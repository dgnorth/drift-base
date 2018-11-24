import logging
from six.moves import http_client

from flask import url_for, g
from flask.views import MethodView
import marshmallow as ma
from flask_restplus import reqparse
from flask_rest_api import Blueprint, abort
from marshmallow_sqlalchemy import ModelSchema
from drift.core.extensions.urlregistry import Endpoints
from driftbase.utils import url_player, url_user
from driftbase.models.db import User, CorePlayer, UserIdentity

log = logging.getLogger(__name__)


endpoints = Endpoints()

bp = Blueprint('users', __name__, url_prefix='/users', description='User management')


class PlayerSchema(ModelSchema):
    class Meta:
        model = CorePlayer
        exclude = ('num_logons', )
        strict = True
    player_url = ma.fields.Str(description="Hello")

class UserIdentitySchema(ModelSchema):
    class Meta:
        model = UserIdentity
        strict = True

class UserSchema(ModelSchema):

    class Meta:
        model = User
        strict = True
    user_url = ma.fields.Str(description="Hello")
    client_url = ma.fields.Str()
    user_url = ma.fields.Str()
    players = ma.fields.List(ma.fields.Nested(PlayerSchema))
    identities = ma.fields.List(ma.fields.Nested(UserIdentitySchema))


class UserRequestSchema(ma.Schema):
    class Meta:
        strict = True
        ordered = True


# Fix soon:
import apispec
APISPEC_VERSION_MAJOR = int(apispec.__version__.split('.')[0])


def drift_init_extension(app, api, **kwargs):
    endpoints.init_app(app)
    if APISPEC_VERSION_MAJOR < 1:
        api.spec.definition('User', schema=UserSchema)
    else:
        api.spec.components.schema('User', schema=UserSchema)
    api.register_blueprint(bp)


#@bp.route('', endpoint='users')
@bp.route('', endpoint='list')
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
                "user_url": url_for('users.entry', user_id=row.user_id, _external=True)
            }
            ret.append(user)
        return ret


#@bp.route('/<int:user_id>', endpoint='user')
@bp.route('/<int:user_id>', endpoint='entry')
class UsersAPI(MethodView):
    """

    """
    @bp.response(UserSchema(many=False))
    def get(self, user_id):
        """Single user

        Return a user by ID
        """
        user = g.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            abort(http_client.NOT_FOUND)

        data = user.as_dict()
        data["client_url"] = None
        players = g.db.query(CorePlayer).filter(CorePlayer.user_id == user_id)
        data["players"] = players
        identities = g.db.query(UserIdentity).filter(UserIdentity.user_id == user_id)
        data["identities"] = identities

        return data


@endpoints.register
def endpoint_info(current_user):
    ret = {"users": url_for("users.list", _external=True), }
    ret["my_user"] = None
    if current_user:
        ret["my_user"] = url_for("users.entry", user_id=current_user["user_id"], _external=True)
    return ret
