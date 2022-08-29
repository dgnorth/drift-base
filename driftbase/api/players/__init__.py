import logging

import marshmallow as ma
from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints
from flask import g, url_for
from flask.views import MethodView
from drift.blueprint import Blueprint, abort
from marshmallow import validates, ValidationError
from sqlalchemy.sql import func
import http.client as http_client

from driftbase.api.players import (
    counters,
    gamestate,
    journal,
    playergroups,
    summary,
    tickets,
)
from driftbase.models.db import CorePlayer, MatchPlayer
from driftbase.players import get_playergroup_ids
from driftbase.utils import url_player
from driftbase.schemas.players import PlayerSchema

log = logging.getLogger(__name__)

bp = Blueprint('players', __name__, url_prefix='/players')

endpoints = Endpoints()


class PlayersListArgs(ma.Schema):
    class Meta:
        strict = True

    player_id = ma.fields.List(
        ma.fields.Integer(), metadata=dict(description="Player ID's to filter for"
    ))
    rows = ma.fields.Integer(metadata=dict(description="Number of rows to return, maximum of 100"))
    player_group = ma.fields.String(
        metadata=dict(description="The player group the players should belong to (see player-group api)"
    ))
    key = ma.fields.List(ma.fields.String(), metadata=dict(description="Only return these columns"))
    player_name = ma.fields.String(
        metadata=dict(description="Player name to search for")
    )


class PlayerPatchArgs(ma.Schema):
    class Meta:
        strict = True

    name = ma.fields.String(metadata=dict(description="New name for the player. Can be between 1 and 20 characters long."))

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
    @bp.response(http_client.OK, PlayerSchema(many=True))
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
        elif 'player_name' in args:
            player_name = args["player_name"]
            if '*' not in player_name:
                query = query.filter(CorePlayer.player_name == player_name)
            else:
                query = query.filter(CorePlayer.player_name.ilike("%s" % player_name.replace('*', '%')))
                # TODO maybe: order results on match quality rather than id
        query = query.order_by(-CorePlayer.player_id).limit(min(rows, 500))
        players = query.all()

        return players


@bp.route('/<int:player_id>', endpoint='entry')
class PlayerAPI(MethodView):
    class GetPlayerArgs(ma.Schema):
        include_total_match_time = ma.fields.Boolean(allow_none=True, dump_default=False, metadata=dict(description="Whether to include total match time"))

    @bp.arguments(GetPlayerArgs, location="query")
    @bp.response(http_client.OK)
    def get(self, args, player_id):
        """
        Single Player

        Retrieve information about a specific player
        """
        player = g.db.query(CorePlayer).get(player_id)
        if not player:
            abort(http_client.NOT_FOUND)

        ret = PlayerSchema(many=False).dump(player)

        if args.get("include_total_match_time"):
            match_time_query = g.db.query(func.sum(MatchPlayer.seconds)).filter(MatchPlayer.player_id == player_id)

            ret["total_match_time_seconds"] = match_time_query.scalar() or 0

        return ret

    @bp.arguments(PlayerPatchArgs)
    @bp.response(http_client.OK, PlayerSchema(many=False))
    def patch(self, args, player_id):
        """
        Update player name
        """
        return self._patch(player_id, args)

    @bp.arguments(PlayerPatchArgs)
    @bp.response(http_client.OK, PlayerSchema(many=False))
    def put(self, args, player_id):
        """
        Update player name

        This method is provided for backwards compatibility with old clients
        """
        return self._patch(player_id, args)

    def _patch(self, player_id, args):
        new_name = args.get('name')

        if player_id != current_user["player_id"]:
            abort(http_client.FORBIDDEN, message="That is not your player!")
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
    template_player_gamestate_url = url_for("player_gamestate.entry", player_id=1337, namespace="namespace", _external=True)
    template_player_gamestate_url = template_player_gamestate_url.replace("1337", "{player_id}")
    template_player_gamestate_url = template_player_gamestate_url.replace("namespace", "{namespace}")

    ret = {
        "players": url_for("players.list", _external=True),
        "my_player": None,
        "my_gamestates": None,
        "my_player_groups": None,
        "my_summary": None,
        "template_player_gamestate": template_player_gamestate_url,
    }

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
