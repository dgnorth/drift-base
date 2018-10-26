import logging
from six.moves import http_client

from flask import url_for, request, g, jsonify
from flask.views import MethodView
import marshmallow as ma
from flask_restplus import reqparse
from flask_rest_api import Blueprint, abort

from drift.utils import json_response
from drift.core.extensions.schemachecker import simple_schema_request

from driftbase.players import can_edit_player
from driftbase.models.db import GameState, GameStateHistory, PlayerJournal

log = logging.getLogger(__name__)

bp = Blueprint("player_gamestate", __name__, url_prefix='/players', description="Datastore for game state information")

MAX_DATA_LEN = 1024 * 1024  # 1MB

TASK_VALIDATED = "validated"


@bp.route("/<int:player_id>/gamestates", endpoint="list")
class GameStatesAPI(MethodView):

    def get(self, player_id):
        """
        Get a list of all gamestates for the player
        """
        can_edit_player(player_id)

        gamestates = g.db.query(GameState) \
                         .filter(GameState.player_id == player_id) \
                         .order_by(GameState.namespace)

        ret = []
        for gamestate in gamestates:
            entry = {
                "namespace": gamestate.namespace,
                "gamestate_id": gamestate.gamestate_id,
                "gamestate_url": url_for("player_gamestate.entry", player_id=player_id,
                                         namespace=gamestate.namespace, _external=True)
            }
            ret.append(entry)

        return jsonify(ret)


@bp.route("/<int:player_id>/gamestates/<string:namespace>", endpoint="entry")
class GameStateAPI(MethodView):

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
        ret = gamestate.as_dict()
        ret["gamestatehistory_url"] = url_for("player_gamestate.historylist",
                                              player_id=player_id, namespace=namespace,
                                              _external=True)
        return jsonify(ret)

    @simple_schema_request({
        "gamestate": {"type": "object"},
        "journal_id": {"type": ["number", "null"]},
    }, required=["gamestate"])
    def put(self, player_id, namespace):
        """
        Upload the gamestate state to the server
        """
        can_edit_player(player_id)

        args = request.json
        data = args["gamestate"]
        journal_id = None
        if args.get("journal_id"):
            journal_id = int(args["journal_id"])

        if journal_id:
            journal_row = g.db.query(PlayerJournal) \
                .filter(PlayerJournal.player_id == player_id,
                        PlayerJournal.journal_id == journal_id,
                        PlayerJournal.deleted is not True) \
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

        return jsonify(gamestate.as_dict())

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

    def get(self, player_id, namespace):
        can_edit_player(player_id)

        rows = g.db.query(GameStateHistory) \
                   .filter(GameStateHistory.player_id == player_id,
                           GameStateHistory.namespace == namespace) \
                   .order_by(-GameStateHistory.gamestatehistory_id)
        if not rows:
            abort(http_client.NOT_FOUND)
        ret = []
        for row in rows:
            entry = {
                "gamestatehistory_id": row.gamestatehistory_id,
                "gamestatehistoryentry_url": url_for("player_gamestate.historyentry",
                                                     player_id=player_id,
                                                     namespace=namespace,
                                                     gamestatehistory_id=row.gamestatehistory_id,
                                                     _external=True),
                "create_date": row.create_date
            }
            ret.append(entry)
        return jsonify(ret)


@bp.route("/<int:player_id>/gamestates/<string:namespace>/history/<int:gamestatehistory_id>",
                 endpoint="historyentry")
class GameStateHistoryEntryAPI(MethodView):

    def get(self, player_id, namespace, gamestatehistory_id):
        can_edit_player(player_id)

        row_gamestate = g.db.query(GameStateHistory)\
                            .filter(GameStateHistory.player_id == player_id,
                                    GameStateHistory.gamestatehistory_id == gamestatehistory_id) \
                            .first()
        if not row_gamestate:
            abort(http_client.NOT_FOUND)
        ret = row_gamestate.as_dict()
        return jsonify(ret)
