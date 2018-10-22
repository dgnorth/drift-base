import logging
from six.moves import http_client

from flask import url_for, g
from flask_restplus import Namespace, Resource, reqparse, abort
from flask_restplus.errors import ValidationError

from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints

from driftbase.utils import url_player
from driftbase.models.db import CorePlayer
from driftbase.models.responses import player_model
from driftbase.players import get_playergroup_ids
from driftbase.api.players import counters, gamestate, journal, playergroups, summary, tickets

log = logging.getLogger(__name__)

namespace = Namespace("players", "Player Management")
endpoints = Endpoints()


def drift_init_extension(app, api, **kwargs):
    api.add_namespace(namespace)
    endpoints.init_app(app)
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


@namespace.route('', endpoint='players')
class PlayersListAPI(Resource):
    """
    list players
    """
    get_args = reqparse.RequestParser()
    get_args.add_argument("player_id", type=int, action="append",
                          help="Filter on player ID")
    get_args.add_argument("rows", type=int, default=10,
                          help="Number of rows to return, maximum of 100")
    get_args.add_argument("player_group", type=str,
                          help="The player group the players should belong to (see player-group api)")
    get_args.add_argument("key", type=str, action="append",
                          help="Only return these columns")

    @namespace.expect(get_args)
    @namespace.marshal_with(player_model)
    def get(self):
        args = self.get_args.parse_args()
        query = g.db.query(CorePlayer)
        rows = min(args.rows or 10, 100)
        if args.player_id:
            query = query.filter(CorePlayer.player_id.in_(args.player_id))
        elif args.player_group:
            player_ids = get_playergroup_ids(args.player_group, caress_in_predicate=False)
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


@namespace.route('/<int:player_id>', endpoint='player')
class PlayersAPI(Resource):
    """
    Individual players
    """
    @namespace.marshal_with(player_model)
    def get(self, player_id):
        """
        Retrieve information about a specific player
        """
        player = g.db.query(CorePlayer).get(player_id)
        if not player:
            abort(http_client.NOT_FOUND)

        return player

    patch_args = reqparse.RequestParser()
    patch_args.add_argument("name",
                            type=validate_length(MIN_NAME_LEN, MAX_NAME_LEN),
                            help="New name for player")

    @namespace.expect(patch_args)
    @namespace.marshal_with(player_model)
    def patch(self, player_id):
        """
        Update player name
        """
        return self._patch(player_id)

    @namespace.expect(patch_args)
    @namespace.marshal_with(player_model)
    def put(self, player_id):
        """
        Update player name (backwards compatibility with old clients)
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
