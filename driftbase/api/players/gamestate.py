import logging

import marshmallow as ma
from drift.utils import Url
from drift.utils import json_response
from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint, abort
from marshmallow_sqlalchemy import ModelSchema
from six.moves import http_client

from driftbase.models.db import GameState, GameStateHistory, PlayerJournal
from driftbase.players import can_edit_player

log = logging.getLogger(__name__)

bp = Blueprint("player_gamestate", __name__, url_prefix='/players', description="Datastore for game state information")

MAX_DATA_LEN = 1024 * 1024  # 1MB

TASK_VALIDATED = "validated"


class GameStateRequestSchema(ma.Schema):
    gamestate = ma.fields.Dict()
    journal_id = ma.fields.Integer(allow_none=True)


class GameStateSchema(ModelSchema):
    class Meta:
        strict = True
        model = GameState
    gamestate_url = Url('player_gamestate.entry',
                        player_id='<player_id>',
                        namespace='<namespace>',
                        doc="Url to the game state resource")
    gamestatehistory_url = Url('player_gamestate.historylist',
                               player_id='<player_id>',
                               namespace='<namespace>',
                               doc="Url to the game state history resource")


class GameStateHistorySchema(ModelSchema):
    class Meta:
        strict = True
        model = GameStateHistory
    gamestatehistoryentry_url = Url('player_gamestate.historyentry',
                                    player_id='<player_id>',
                                    namespace='<namespace>',
                                    gamestatehistory_id='<gamestatehistory_id>',
                                    doc="Url to the game state history resource")


@bp.route("/<int:player_id>/gamestates", endpoint="list")
class GameStatesAPI(MethodView):

    @bp.response(http_client.OK, GameStateSchema(many=True))
    def get(self, player_id):
        """
        Get a list of all gamestates for the player
        """
        can_edit_player(player_id)

        gamestates = g.db.query(GameState) \
                         .filter(GameState.player_id == player_id) \
                         .order_by(GameState.namespace)
        return gamestates


@bp.route("/<int:player_id>/gamestates/<string:namespace>", endpoint="entry")
class GameStateAPI(MethodView):

    @bp.response(http_client.OK, GameStateSchema())
    def get(self, player_id, namespace):
        """
        Get full dump of game state

        for the current player in namespace 'namespace'
        """
        can_edit_player(player_id)

        gamestates = g.db.query(GameState) \
                         .filter(GameState.player_id == player_id,
                                 GameState.namespace == namespace) \
                         .order_by(-GameState.gamestate_id)
        if gamestates.count() == 0:
            msg = "Gamestate '%s' for player %s not found" % (namespace, player_id)
            log.info(msg)
            abort(http_client.NOT_FOUND)

        elif gamestates.count() > 1:
            raise RuntimeError("Player %s has %s game states with namespace '%s'" %
                               (player_id, gamestates.count(), namespace))

        gamestate = gamestates.first()
        return gamestate

    @bp.arguments(GameStateRequestSchema())
    @bp.response(http_client.OK, GameStateSchema())
    def put(self, args, player_id, namespace):
        """
        Upload the gamestate state to the server
        """
        can_edit_player(player_id)

        data = args["gamestate"]
        journal_id = None
        if args.get("journal_id"):
            journal_id = int(args["journal_id"])

        if journal_id:
            journal_row = g.db.query(PlayerJournal) \
                .filter(PlayerJournal.player_id == player_id,
                        PlayerJournal.journal_id == journal_id,
                        PlayerJournal.deleted != True) \
                .first()
            if not journal_row:
                # Note: this might happen normally unless we serialize on the
                # client to ensure all journal entries
                # are acked before sending up the new state
                msg = "Journal entry %s for player %s not found!" % (journal_id, player_id)
                log.warning(msg)
                return json_response(msg, http_client.BAD_REQUEST)

        gamestate = g.db.query(GameState)\
            .filter(GameState.player_id == player_id, GameState.namespace == namespace) \
            .order_by(-GameState.gamestate_id).first()

        if gamestate:
            if journal_id and journal_id <= gamestate.journal_id:
                # TODO: Raise here?
                log.warning("Writing a new gamestate with an older journal_id, %s "
                            "than the current one", journal_id, extra=gamestate.as_dict())
            gamestate.version += 1
            gamestate.data = data
            gamestate.journal_id = journal_id
            log.info("Updated gamestate for player %s to version %s. journal_id = %s", player_id,
                     gamestate.version, journal_id)
        else:
            gamestate = GameState(player_id=player_id, data=data,
                                  journal_id=journal_id, namespace=namespace)
            g.db.add(gamestate)
            g.db.flush()
            log.info("Added new gamestate for player")

        # write new gamestate to the history table for safe keeping
        gamestatehistory_row = GameStateHistory(player_id=player_id,
                                                version=gamestate.version,
                                                data=gamestate.data,
                                                namespace=gamestate.namespace,
                                                journal_id=gamestate.journal_id)
        g.db.add(gamestatehistory_row)
        g.db.flush()

        gamestatehistory_id = gamestatehistory_row.gamestatehistory_id
        gamestate.gamestatehistory_id = gamestatehistory_id
        g.db.commit()

        return gamestate

    def delete(self, player_id, namespace):
        """
        Remove a gamestate from the player (it will still exist in the history table)
        """
        can_edit_player(player_id)
        gamestates = g.db.query(GameState) \
                         .filter(GameState.player_id == player_id,
                                 GameState.namespace == namespace)

        gamestates.delete()
        g.db.commit()

        log.info("Gamestate '%s' for player %s has been deleted", namespace, player_id)

        return "OK"


@bp.route("/<int:player_id>/gamestates/<string:namespace>/history", endpoint="historylist")
class GameStateHistoryListAPI(MethodView):

    @bp.response(http_client.OK, GameStateHistorySchema(many=True))
    def get(self, player_id, namespace):
        can_edit_player(player_id)

        rows = g.db.query(GameStateHistory) \
                   .filter(GameStateHistory.player_id == player_id,
                           GameStateHistory.namespace == namespace) \
                   .order_by(-GameStateHistory.gamestatehistory_id)
        if not rows:
            abort(http_client.NOT_FOUND)
        return rows


@bp.route("/<int:player_id>/gamestates/<string:namespace>/history/<int:gamestatehistory_id>",
                 endpoint="historyentry")
class GameStateHistoryEntryAPI(MethodView):

    @bp.response(http_client.OK, GameStateHistorySchema())
    def get(self, player_id, namespace, gamestatehistory_id):
        can_edit_player(player_id)

        row_gamestate = g.db.query(GameStateHistory)\
                            .filter(GameStateHistory.player_id == player_id,
                                    GameStateHistory.gamestatehistory_id == gamestatehistory_id) \
                            .first()
        if not row_gamestate:
            abort(http_client.NOT_FOUND)
        return row_gamestate
