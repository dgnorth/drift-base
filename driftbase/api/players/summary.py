import logging

from six.moves import http_client

from flask import request, g, abort
from flask_restplus import Namespace, Resource

from driftbase.models.db import PlayerSummary, PlayerSummaryHistory, CorePlayer
from driftbase.players import log_event, can_edit_player

log = logging.getLogger(__name__)

namespace = Namespace("players")


def get_player(player_id):
    player = g.db.query(CorePlayer).get(player_id)
    return player


@namespace.route("/<int:player_id>/summary", endpoint="players_summary")
class Summary(Resource):

    def get(self, player_id):
        """
        """
        can_edit_player(player_id)
        if not get_player(player_id):
            abort(http_client.NOT_FOUND)
        summary = g.db.query(PlayerSummary).filter(PlayerSummary.player_id == player_id)
        ret = {}
        for row in summary:
            ret[row.name] = row.value

        return ret

    # TODO: schema
    def put(self, player_id):
        """
        Full update of summary fields, deletes fields from db that are not included
        """
        if not can_edit_player(player_id):
            abort(http_client.METHOD_NOT_ALLOWED, message="That is not your player!")

        if not get_player(player_id):
            abort(http_client.NOT_FOUND)

        old_summary = g.db.query(PlayerSummary).filter(PlayerSummary.player_id == player_id).all()

        new_summary = []
        updated_ids = set()
        for name, val in request.json.items():
            for row in old_summary:
                if row.name == name:
                    updated_ids.add(row.id)
                    if val != row.value:
                        row.value = val
                    break
            else:
                log.info("Adding a new summary field, '%s' with value '%s'", name, val)
                summary_row = PlayerSummary(player_id=player_id, name=name, value=val)
                g.db.add(summary_row)
                g.db.flush()
                updated_ids.add(summary_row.id)
        g.db.commit()

        for row in old_summary:
            if row.id not in updated_ids:
                log.info("Deleting summary field '%s' with id %s which had the value '%s'",
                         row.name, row.id, row.value)
                g.db.delete(row)
        g.db.commit()

        new_summary = g.db.query(PlayerSummary).filter(PlayerSummary.player_id == player_id).all()

        request_txt = ""
        for k, v in request.json.items():
            request_txt += "%s = %s, " % (k, v)
        if request_txt:
            request_txt = request_txt[:-2]

        new_summary_txt = ""
        for row in new_summary:
            new_summary_txt += "%s = %s, " % (row.name, row.value)
        if new_summary_txt:
            new_summary_txt = new_summary_txt[:-2]
        log.info("Updating summary for player %s. Request is '%s'. New summary is '%s'",
                 player_id, request_txt, new_summary_txt)

        ret = []
        return ret

    # TODO: schema
    def patch(self, player_id):
        """
        Partial update of summary fields.
        """
        if not can_edit_player(player_id):
            abort(http_client.METHOD_NOT_ALLOWED, message="That is not your player!")

        if not get_player(player_id):
            abort(http_client.NOT_FOUND)
        old_summary = g.db.query(PlayerSummary).filter(PlayerSummary.player_id == player_id).all()
        old_summary_txt = ""
        for row in old_summary:
            old_summary_txt += "%s = %s, " % (row.name, row.value)

        changes = {}
        for name, val in request.json.items():
            for row in old_summary:
                if row.name == name:
                    if val != row.value:
                        changes[name] = {"old": row.value, "new": val}
                        row.value = val
                    break
            else:
                log.info("Adding a new summary field, '%s' with value '%s'", name, val)
                changes[name] = {"old": None, "new": val}
                summary_row = PlayerSummary(player_id=player_id, name=name, value=val)
                g.db.add(summary_row)

            # if this summary stat changes we write it into our history log
            if name in changes:
                summaryhistory_row = PlayerSummaryHistory(player_id=player_id, name=name, value=val)
                g.db.add(summaryhistory_row)

            g.db.commit()

        new_summary = g.db.query(PlayerSummary).filter(PlayerSummary.player_id == player_id).all()

        log_event(player_id, "event.player.summarychanged", changes)
        request_txt = ""
        for k, v in request.json.items():
            request_txt += "%s = %s, " % (k, v)
        if request_txt:
            request_txt = request_txt[:-2]

        if old_summary_txt:
            old_summary_txt = old_summary_txt[:-2]
        new_summary_txt = ""
        for row in new_summary:
            new_summary_txt += "%s = %s, " % (row.name, row.value)
        if new_summary_txt:
            new_summary_txt = new_summary_txt[:-2]
        log.info("Updating summary. Request is '%s'. Old summary is '%s'. New summary is '%s'",
                 request_txt, old_summary_txt, new_summary_txt)

        return [r.as_dict() for r in new_summary]
