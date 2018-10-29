from operator import itemgetter
from dateutil import parser
import datetime
import logging

from six.moves import http_client

from flask import request, g, url_for, jsonify
from flask.views import MethodView
import marshmallow as ma
from flask_restplus import reqparse
from flask_rest_api import Blueprint, abort

from drift.utils import json_response
from drift.core.extensions.jwt import current_user

from driftbase.models.db import PlayerJournal, GameState
from driftbase.players import write_journal, JournalError
from driftbase.players import can_edit_player

log = logging.getLogger(__name__)

bp = Blueprint("player_journal", __name__, url_prefix='/players')


@bp.route("/<int:player_id>/journal", endpoint="list")
class JournalAPI(MethodView):
    get_args = reqparse.RequestParser()
    get_args.add_argument("rows", type=int)
    get_args.add_argument("include_deleted", type=bool)

    def get(self, player_id):
        """
        Get a list of recent journal entries for the player
        """
        DEFAULT_ROWS = 100
        args = self.get_args.parse_args()
        can_edit_player(player_id)

        # TODO: Custom filters
        query = g.db.query(PlayerJournal)
        query = query.filter(PlayerJournal.player_id == player_id)
        if not getattr(args, "include_deleted", False):
            query = query.filter(PlayerJournal.deleted == False)  # noqa: E711
        query = query.order_by(-PlayerJournal.journal_id, -PlayerJournal.sequence_id)
        query = query.limit(args.rows or DEFAULT_ROWS)
        ret = []
        for entry in query:
            e = entry.as_dict()
            ret.append(e)
        return jsonify(ret)

    def post(self, player_id):
        """
        Add a journal entry
        """
        if not can_edit_player(player_id):
            abort(http_client.METHOD_NOT_ALLOWED, message="That is not your player!")

        args_list = request.json
        if not isinstance(args_list, list):
            raise RuntimeError("Arguments should be a list")
        for a in args_list:
            if "journal_id" not in a:
                abort(http_client.BAD_REQUEST)
        ret = []
        now = datetime.datetime.utcnow()
        MAX_DRIFT = 60
        args_list.sort(key=itemgetter('journal_id'))
        client_current_time = args_list[0].get("client_current_time")
        if not client_current_time:
            log.warning("Client is uploading journal entries without a client_current_time")
        else:
            client_current_time = parser.parse(client_current_time)
            diff = (client_current_time.replace(tzinfo=None) - now).total_seconds()
            if abs(diff) > MAX_DRIFT:
                log.warning("Client's clock is %.0f seconds out of sync. "
                            "Client system time: '%s', Server time: '%s'",
                            diff, client_current_time, now)
        for args in args_list:
            # Special handling if this is a rollback event.
            # We mark all journal entries higher than the event to rollback to
            # as deleted (as an optimization) and then add the rollback event itself.
            if "rollback_to_journal_id" in args:
                to_journal_id = int(args.get("rollback_to_journal_id"))
                # TODO: Check if there are any gamestates persisted after the id
                gamestate = get_player_gamestate(player_id)
                if not gamestate:
                    log.warning("Player is rebasing journal entries but doesn't"
                                "have any gamestate.")

                elif gamestate.journal_id > to_journal_id:
                    return json_response("Journal has already been persisted into home base!",
                                         http_client.BAD_REQUEST)

                entry = get_journal_entry(player_id, to_journal_id)
                if not entry.first():
                    log.warning("Rolling back to journal entry %s which doesn't exist")
                elif entry.first().deleted:
                    log.warning("Rolling back to journal entry %s which has been rolled back")

                g.db.query(PlayerJournal).filter(PlayerJournal.player_id == player_id,
                                                 PlayerJournal.journal_id > to_journal_id) \
                                         .update({"deleted": True})

            # report if the client's clock is out of sync with the server
            timestamp = parser.parse(args["timestamp"])
            diff = (timestamp.replace(tzinfo=None) - now).total_seconds()
            if abs(diff) > MAX_DRIFT:
                log.info("Client is sending journal info for journal entry %s '%s' which "
                         "is %.0f seconds out of sync. "
                         "Client journal timestamp: '%s', Server timestamp: '%s'",
                         args["journal_id"], args["action"], diff, args["timestamp"], now)

            try:
                journal = write_journal(player_id, args["action"], args["journal_id"],
                                        args["timestamp"],
                                        details=args.get("details"), steps=args.get("steps"),
                                        actor_id=current_user["player_id"])
            except JournalError as e:
                # TODO: We now reject the journal entry and subsequent entries instead of
                # rolling the entire thing back. Is that what we want?
                log.warning("Error writing to journal. Rejecting entry. Error was: %s", e)
                abort(http_client.BAD_REQUEST, description=str(e))

            ret.append({"journal_id": journal["journal_id"],
                        "url": url_for("player_journal.entry",
                                       player_id=player_id,
                                       journal_id=journal["journal_id"],
                                       _external=True)
                        })
        return jsonify(ret), http_client.CREATED


def get_journal_entry(player_id, journal_id):
    entry = g.db.query(PlayerJournal) \
                .filter(PlayerJournal.player_id == player_id,
                        PlayerJournal.journal_id == journal_id)
    return entry


def get_player_gamestate(player_id):
    gamestate = g.db.query(GameState) \
                    .filter(GameState.player_id == player_id) \
                    .order_by(-GameState.journal_id) \
                    .first()
    return gamestate


@bp.route("/<int:player_id>/journal/<int:journal_id>", endpoint="entry")
class JournalEntryAPI(MethodView):
    def get(self, player_id, journal_id):
        """
        Get a specific journal entry for the player
        """
        can_edit_player(player_id)

        entry = get_journal_entry(player_id, journal_id)
        if not entry.first():
            return json_response("Journal entry not found", http_client.NOT_FOUND)
        ret = entry.first().as_dict()
        return jsonify(ret)
