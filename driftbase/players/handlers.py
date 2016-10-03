# -*- coding: utf-8 -*-

import logging
import httplib

from flask import Blueprint, url_for, g, request
from flask_restful import Api, Resource, abort, reqparse

from drift.auth.jwtchecker import current_user
from drift.urlregistry import register_endpoints
from drift.utils import url_player, url_user
from drift.core.extensions.schemachecker import simple_schema_request

from driftbase.db.models import CorePlayer, Client, User
from driftbase.players.playergroups import get_playergroup_ids

log = logging.getLogger(__name__)
bp = Blueprint("players", __name__)
api = Api(bp)

MIN_NAME_LEN = 3
MAX_NAME_LEN = 20


def get_player_entry(recordset, columns=None):
    player = recordset[0]
    user = recordset[1]
    client = recordset[2]
    entry = player.as_dict()
    entry["player_url"] = url_player(player.player_id)
    entry["user_url"] = url_user(player.user_id)
    entry["counter_url"] = url_for("playercounters.list", player_id=player.player_id,
                                   _external=True)
    entry["countertotals_url"] = url_for("playercounters.totals", player_id=player.player_id,
                                         _external=True)
    entry["gamestates_url"] = url_for("gamestate.gamestates", player_id=player.player_id,
                                      _external=True)
    entry["journal_url"] = url_for("journal.list", player_id=player.player_id,
                                   _external=True)
    entry["messages_url"] = url_for("messages.exchange", exchange="players",
                                    exchange_id=player.player_id, _external=True)
    entry["messagequeue_url"] = url_for("messages.exchange", exchange="players",
                                        exchange_id=player.player_id, _external=True) + "/{queue}"
    entry["summary_url"] = url_for("summary.summary", player_id=player.player_id, _external=True)
    entry["tickets_url"] = url_for("tickets.list", player_id=player.player_id, _external=True)
    is_online = False
    if client:
        is_online = client.is_online
    entry["is_online"] = is_online

    if columns:
        columns = set(columns)
        # player_id should always be returned
        columns.add("player_id")
        ret = {}
        for c in columns:
            ret[c] = entry.get(c, None)
    else:
        ret = entry
    return ret


def validate_player_name(name):
    if len(name) < MIN_NAME_LEN:
        abort(httplib.METHOD_NOT_ALLOWED,
              message="Player name is too short. It needs to be at least %s characters" %
              MIN_NAME_LEN)
    if len(name) > MAX_NAME_LEN:
        abort(httplib.METHOD_NOT_ALLOWED,
              message="Player name is too long. It cannot exceed %s characters" % MAX_NAME_LEN)
    # TODO: More validation


class PlayersListAPI(Resource):
    """
    list players
    """
    # GET args
    get_args = reqparse.RequestParser()
    get_args.add_argument("player_id", type=int, action="append", help="Filter on player ID.")
    get_args.add_argument("rows", type=int)
    get_args.add_argument("player_group", type=str)
    get_args.add_argument("key", type=str, action="append")

    def get(self):
        args = self.get_args.parse_args()
        query = g.db.query(CorePlayer, User, Client)
        query = query.join(User, User.user_id == CorePlayer.user_id)
        query = query.outerjoin(Client, User.client_id == Client.client_id)
        rows = args.rows or 500
        if args.player_id:
            query = query.filter(CorePlayer.player_id.in_(args.player_id))
        elif args.player_group:
            player_ids = get_playergroup_ids(args.player_group, caress_in_predicate=False)
            if not player_ids:
                # Note! This is a particular optimization in case where player group is empty
                return []
            query = query.filter(CorePlayer.player_id.in_(player_ids))
        players = query.order_by(-CorePlayer.player_id).limit(min(rows, 500))

        return [get_player_entry(row, args.key) for row in players]


class PlayersAPI(Resource):
    """

    """
    def get(self, player_id):
        """
        """
        query = g.db.query(CorePlayer, User, Client)
        query = query.join(User, User.user_id == CorePlayer.user_id)
        query = query.filter(CorePlayer.player_id == player_id)
        query = query.outerjoin(Client, User.client_id == Client.client_id)
        recordset = query.first()

        if not recordset:
            abort(httplib.NOT_FOUND)

        return get_player_entry(recordset)

    @simple_schema_request({"name": {"type": "string"}})
    def patch(self, player_id):
        """
        Update player name
        """
        new_name = request.json["name"]
        if player_id != current_user["player_id"]:
            abort(httplib.METHOD_NOT_ALLOWED, message="That is not your player!")
        validate_player_name(new_name)
        my_player = g.db.query(CorePlayer).get(player_id)
        if not my_player:
            abort(httplib.NOT_FOUND)
        old_name = my_player.player_name
        my_player.player_name = new_name
        g.db.commit()
        log.info("Player changed name from '%s' to '%s'", old_name, new_name)
        return my_player.as_dict()


api.add_resource(PlayersListAPI, "/players", endpoint="players")
api.add_resource(PlayersAPI, '/players/<int:player_id>', endpoint="player")


@register_endpoints
def endpoint_info(current_user):
    ret = {"players": url_for("players.players", _external=True)}
    ret["my_player"] = None
    if current_user:
        ret["my_player"] = url_player(current_user["player_id"])
    return ret
