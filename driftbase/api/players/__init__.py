import logging
from six.moves import http_client

from flask import url_for, g, request
from flask.views import MethodView
from flask_restplus import Namespace, Resource, reqparse, abort
from flask_restplus.errors import ValidationError
import marshmallow as ma
from flask_rest_api import Api, Blueprint
from marshmallow_sqlalchemy import ModelSchema

from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints

from driftbase.utils import url_player
from driftbase.models.db import CorePlayer
from driftbase.models.responses import player_model
from driftbase.players import get_playergroup_ids
from driftbase.api.players import counters, gamestate, journal, playergroups, summary, tickets

log = logging.getLogger(__name__)


bp = Blueprint('players', 'Users', url_prefix='/players', description='Player Management')

endpoints = Endpoints()

class PlayerSchema(ModelSchema):
    class Meta:
        model = CorePlayer
        exclude = ('ck_player_summary', )
    player_url = ma.fields.Str(description="Fully qualified URL of the player resource")

class PlayersListArgs(ma.Schema):
    player_id = ma.fields.List(ma.fields.Integer(), description="Player ID's to filter for")
    rows = ma.fields.Integer(description="Number of rows to return, maximum of 100")
    player_group = ma.fields.String(description="The player group the players should belong to (see player-group api)")
    key = ma.fields.List(ma.fields.String(), description="Only return these columns")


class PlayerPatchArgs(ma.Schema):
    name = ma.fields.String(description="New name for the player")


def drift_init_extension(app, api, **kwargs):
    #api.spec.definition('User', schema=UserSchema)

    api.register_blueprint(bp)
    endpoints.init_app(app)

    api.spec.definition('Player', schema=PlayerSchema)

    return
    api.add_namespace(namespace)
    api.add_namespace(counters.namespace)
    api.add_namespace(gamestate.namespace)
    api.add_namespace(journal.namespace)
    api.add_namespace(playergroups.namespace)
    api.add_namespace(summary.namespace)
    api.add_namespace(tickets.namespace)

    api.models[player_model.name] = player_model


# TODO: Have this configured on a per product level and use drift config to specify it.
MIN_NAME_LEN = 1
MAX_NAME_LEN = 20


@bp.route('', endpoint='players')
class PlayersListAPI(MethodView):

    @bp.arguments(PlayersListArgs, location='query')
    @bp.response(PlayerSchema(many=True))
    def get(self, args):
        """
        List Players

        Retrieves multiple players based on input filters
        """
        query = g.db.query(CorePlayer)
        rows = min(args.get('rows') or 10, 100)
        if 'player_id' in args:
            query = query.filter(CorePlayer.player_id.in_(args['player_id']))
        elif 'player_group' in args:
            player_ids = get_playergroup_ids(args['player_group'], caress_in_predicate=False)
            if not player_ids:
                # Note! This is a particular optimization in case where player group is empty
                return []
            query = query.filter(CorePlayer.player_id.in_(player_ids))
        query = query.order_by(-CorePlayer.player_id).limit(min(rows, 500))
        players = query.all()

        return players


def validate_length(min_length, max_length):
    def validate(s):
        if len(s) >= min_length and len(s) <= max_length:
            return s
        raise ValidationError("String must be between %i and %i characters long" %
                              (min_length, max_length))
    return validate


@bp.route('/<int:player_id>', endpoint='player')
class PlayerAPI(Resource):
    @bp.response(PlayerSchema(many=False))
    def get(self, player_id):
        """
        Single Player

        Retrieve information about a specific player
        """
        player = g.db.query(CorePlayer).get(player_id)
        if not player:
            abort(http_client.NOT_FOUND)

        return player

    @bp.arguments(PlayerPatchArgs)
    @bp.response(PlayerSchema(many=False))
    def patch(self, player_id):
        """
        Update player name
        """
        return self._patch(player_id)

    @bp.arguments(PlayerPatchArgs)
    @bp.response(PlayerSchema(many=False))
    def put(self, player_id):
        """
        Update player name

        This method is provided for backwards compatibility with old clients
        """
        return self._patch(player_id)

    def _patch(self, player_id):
        args = self.patch_args.parse_args()
        new_name = args.name

        if player_id != current_user["player_id"]:
            abort(http_client.METHOD_NOT_ALLOWED, message="That is not your player!")
        my_player = g.db.query(CorePlayer).get(player_id)
        if not my_player:
            abort(http_client.NOT_FOUND)
        old_name = my_player.player_name
        my_player.player_name = new_name
        g.db.commit()
        log.info("Player changed name from '%s' to '%s'", old_name, new_name)
        return my_player


@endpoints.register
def endpoint_info(current_user):
    ret = {"players": url_for("players", _external=True)}
    ret["my_player"] = None
    ret["my_gamestates"] = None
    ret["my_player_groups"] = None
    ret["my_summary"] = None
    if current_user:
        player_id = current_user["player_id"]
        ret["my_player"] = url_player(player_id)

        ret["my_gamestates"] = url_for("player_gamestates", player_id=player_id, _external=True)
        ret["my_gamestate"] = url_for("player_gamestates", player_id=player_id, _external=True) + \
            "/{namespace}"
        url = url_for(
            "player_playergroups",
            player_id=current_user["player_id"],
            group_name='group_name',
            _external=True,
        )
        url = url.replace('group_name', '{group_name}')
        ret["my_player_groups"] = url
        ret["my_summary"] = url_for("player_summary", player_id=player_id,  _external=True)
    return ret
