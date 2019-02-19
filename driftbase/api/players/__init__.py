import logging
from six.moves import http_client

from flask import g, url_for
from flask.views import MethodView
from flask_rest_api import Blueprint, abort
from marshmallow_sqlalchemy import ModelSchema
import marshmallow as ma
from marshmallow import validates, ValidationError, pre_dump

from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints
from drift.utils import Url

from driftbase.utils import url_player
from driftbase.models.db import CorePlayer
from driftbase.players import get_playergroup_ids
from driftbase.api.players import (
    counters,
    gamestate,
    journal,
    playergroups,
    summary,
    tickets,
)

log = logging.getLogger(__name__)


bp = Blueprint(
    'players', __name__, url_prefix='/players', description='Player Management'
)

endpoints = Endpoints()


class PlayerSchema(ModelSchema):
    class Meta:
        strict = True
        model = CorePlayer
        exclude = ('ck_player_summary',)

    is_online = ma.fields.Boolean()

    player_url = Url(
        'players.entry',
        doc="Fully qualified URL of the player resource",
        player_id='<player_id>',
    )

    gamestates_url = Url(
        'player_gamestate.list',
        doc="Fully qualified URL of the players' gamestate resource",
        player_id='<player_id>',
    )
    journal_url = Url(
        'player_journal.list',
        doc="Fully qualified URL of the players' journal resource",
        player_id='<player_id>',
    )
    user_url = Url(
        'users.entry',
        doc="Fully qualified URL of the players' user resource",
        user_id='<user_id>',
    )
    messagequeue_url = ma.fields.Str(
        description="Fully qualified URL of the players' message queue resource"
    )
    messages_url = Url(
        'messages.exchange',
        doc="Fully qualified URL of the players' messages resource",
        exchange='players',
        exchange_id='<player_id>',
    )
    summary_url = Url(
        'player_summary.list',
        doc="Fully qualified URL of the players' summary resource",
        player_id='<player_id>',
    )
    countertotals_url = Url(
        'player_counters.totals',
        doc="Fully qualified URL of the players' counter totals resource",
        player_id='<player_id>',
    )
    counter_url = Url(
        'player_counters.list',
        doc="Fully qualified URL of the players' counter resource",
        player_id='<player_id>',
    )
    tickets_url = Url(
        'player_tickets.list',
        doc="Fully qualified URL of the players' tickets resource",
        player_id='<player_id>',
    )

    @pre_dump
    def populate_urls(self, obj):
        obj.messagequeue_url = (
            url_for(
                'messages.exchange',
                exchange='players',
                exchange_id=obj.player_id,
                _external=True,
            )
            + '/{queue}'
        )
        return obj


class PlayersListArgs(ma.Schema):
    class Meta:
        strict = True

    player_id = ma.fields.List(
        ma.fields.Integer(), description="Player ID's to filter for"
    )
    rows = ma.fields.Integer(description="Number of rows to return, maximum of 100")
    player_group = ma.fields.String(
        description="The player group the players should belong to (see player-group api)"
    )
    key = ma.fields.List(ma.fields.String(), description="Only return these columns")


class PlayerPatchArgs(ma.Schema):
    class Meta:
        strict = True

    name = ma.fields.String(description="New name for the player. Can be between 1 and 20 characters long.")

    @validates('name')
    def validate(self, s):
        min_length = 1
        max_length = 20
        if len(s) >= min_length and len(s) <= max_length:
            return
        raise ValidationError(
            "String must be between %i and %i characters long"
            % (min_length, max_length),
            status_code=400,
        )


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    api.register_blueprint(counters.bp)
    api.register_blueprint(gamestate.bp)
    api.register_blueprint(journal.bp)
    api.register_blueprint(playergroups.bp)
    api.register_blueprint(summary.bp)
    api.register_blueprint(tickets.bp)
    endpoints.init_app(app)


# TODO: Have this configured on a per product level and use drift config to specify it.
MIN_NAME_LEN = 1
MAX_NAME_LEN = 20


@bp.route('', endpoint='list')
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
            player_ids = get_playergroup_ids(
                args['player_group'], caress_in_predicate=False
            )
            if not player_ids:
                # Note! This is a particular optimization in case where player group is empty
                return []
            query = query.filter(CorePlayer.player_id.in_(player_ids))
        query = query.order_by(-CorePlayer.player_id).limit(min(rows, 500))
        players = query.all()

        return players


@bp.route('/<int:player_id>', endpoint='entry')
class PlayerAPI(MethodView):
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
    def patch(self, args, player_id):
        """
        Update player name
        """
        return self._patch(player_id, args)

    @bp.arguments(PlayerPatchArgs)
    @bp.response(PlayerSchema(many=False))
    def put(self, args, player_id):
        """
        Update player name

        This method is provided for backwards compatibility with old clients
        """
        return self._patch(player_id, args)

    def _patch(self, player_id, args):
        new_name = args.get('name')

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
    ret = {"players": url_for("players.list", _external=True)}
    ret["my_player"] = None
    ret["my_gamestates"] = None
    ret["my_player_groups"] = None
    ret["my_summary"] = None
    if current_user:
        player_id = current_user["player_id"]
        ret["my_player"] = url_player(player_id)

        ret["my_gamestates"] = url_for(
            "player_gamestate.list", player_id=player_id, _external=True
        )
        ret["my_gamestate"] = (
            url_for("player_gamestate.list", player_id=player_id, _external=True)
            + "/{namespace}"
        )
        url = url_for(
            "playergroups.group",
            player_id=current_user["player_id"],
            group_name='group_name',
            _external=True,
        )
        url = url.replace('group_name', '{group_name}')
        ret["my_player_groups"] = url
        ret["my_summary"] = url_for(
            "player_summary.list", player_id=player_id, _external=True
        )
    return ret
