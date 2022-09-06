"""
    List of players waiting for a match
"""

import datetime
import http.client as http_client
import logging
import marshmallow as ma
from flask import g, url_for, jsonify
from flask.views import MethodView
from drift.blueprint import Blueprint, abort

from drift.core.extensions.jwt import current_user
from drift.core.extensions.urlregistry import Endpoints
from drift.utils import json_response
from driftbase.matchqueue import process_match_queue
from driftbase.models.db import CorePlayer, MatchQueuePlayer, Match, Client, Server
from driftbase.utils import url_player

log = logging.getLogger(__name__)

bp = Blueprint("matchqueue", "matchqueue", url_prefix="/matchqueue")

endpoints = Endpoints()


def drift_init_extension(app, **kwargs):
    app.register_blueprint(bp)
    endpoints.init_app(app)


def make_matchqueueplayer_response(player, matchqueue_entry, server=None):
    player_id = player.player_id
    ret = {
        "player_id": player_id,
        "player_url": url_player(player_id),
        "player_name": player.player_name,
        "match_id": matchqueue_entry.match_id,
        "match_url": None,
        "ue4_connection_url": None,
        "status": matchqueue_entry.status,
        "matchqueueplayer_url": url_for("matchqueue.player", player_id=player_id, _external=True),
        "create_date": matchqueue_entry.create_date,
        "criteria": matchqueue_entry.criteria,
    }
    if matchqueue_entry.match_id:
        ret["match_url"] = url_for("matches.entry", match_id=matchqueue_entry.match_id,
                                   _external=True)
    if server:
        ret["ue4_connection_url"] = "%s:%s?player_id=%s?token=%s" % (server.public_ip,
                                                                     server.port,
                                                                     player_id,
                                                                     server.token)
    return ret


class MatchQueuePostSchema(ma.Schema):
    player_id = ma.fields.Integer(required=True)
    criteria = ma.fields.Dict()
    placement = ma.fields.String()
    ref = ma.fields.String()
    token = ma.fields.String()


class MatchQueueGetQuerySchema(ma.Schema):
    status = ma.fields.List(ma.fields.String(), load_default=["waiting"])


@bp.route('', endpoint='queue')
class MatchQueueAPI(MethodView):
    no_jwt_check = ["GET"]

    @bp.arguments(MatchQueuePostSchema)
    def post(self, args):
        """
        Add a player to the queue

        Registers the current player into the match queue ready for a match
        """
        criteria = args.get("criteria")
        placement = args.get("placement")
        ref = args.get("ref")
        token = args.get("token")
        player_id = args["player_id"]
        if player_id != current_user["player_id"]:
            log.error("Trying to add another player, %s to the match queue", player_id)
            abort(http_client.METHOD_NOT_ALLOWED, message="This is not your player")
        client_id = current_user["client_id"]

        my_player = g.db.query(CorePlayer).filter(CorePlayer.player_id == player_id).first()

        # if we already have an outstanding match request, delete it
        my_matchqueueplayer = g.db.query(MatchQueuePlayer) \
            .filter(MatchQueuePlayer.player_id == player_id,
                    MatchQueuePlayer.status.in_(["waiting", "matched"]))
        if my_matchqueueplayer.count() > 0:
            log.info("Removing old request from %s", my_matchqueueplayer[0].create_date)
            for r in my_matchqueueplayer:
                g.db.delete(r)
                # Notify other matched players. So, let's notify the other one
                # if applicable.
                # This match is basically a dud
                # Note that this assumes two player battles and will force everyone
                # out of queues for more than 2 players!
                if r.match_id:
                    other_matchqueueplayer = g.db.query(MatchQueuePlayer) \
                        .filter(MatchQueuePlayer.match_id == r.match_id)
                    for r_other in other_matchqueueplayer:
                        g.db.delete(r_other)

            g.db.commit()

        my_matchqueueplayer = MatchQueuePlayer(player_id=player_id,
                                               client_id=client_id,
                                               status="waiting",
                                               criteria=criteria,
                                               placement=placement,
                                               ref=ref,
                                               token=token,
                                               )
        g.db.add(my_matchqueueplayer)
        g.db.commit()

        try:
            process_match_queue()
        except Exception:
            # if we were unable to process the match queue remove our player and return an error
            log.exception("Unable to process match queue")
            my_matchqueueplayer = g.db.query(MatchQueuePlayer) \
                .filter(MatchQueuePlayer.player_id == player_id,
                        MatchQueuePlayer.status == "waiting")
            if my_matchqueueplayer.count() > 0:
                for r in my_matchqueueplayer:
                    r.status = "error"
                g.db.commit()

            # This is hiding the error. Systems tests don't get any feedback
            abort(http_client.BAD_REQUEST,
                  message="There was an error processing the match queue. Please try again.")

        if my_matchqueueplayer.match_id:
            log.info("Player %d has joined the Match Queue and was matched into match %d",
                     player_id, my_matchqueueplayer.match_id)
        else:
            log.info("Player %d has joined the Match Queue and is waiting to be matched", player_id)

        ret = make_matchqueueplayer_response(my_player, my_matchqueueplayer)

        response_header = {
            "Location": ret["matchqueueplayer_url"],
        }
        return jsonify(ret), http_client.CREATED, response_header

    @bp.arguments(MatchQueueGetQuerySchema, location='query')
    def get(self, args):
        """
        Get players in the queue

        Returns all players in the queue list, no matter what their status,
        as long as they are online
        """
        statuses = args['status']

        matchqueue_players = g.db.query(CorePlayer, MatchQueuePlayer, Client) \
            .filter(CorePlayer.player_id == MatchQueuePlayer.player_id,
                    MatchQueuePlayer.status.in_(statuses),
                    Client.client_id == MatchQueuePlayer.client_id,
                    Client.heartbeat >= datetime.datetime.utcnow() -
                    datetime.timedelta(seconds=30)) \
            .all()
        ret = []
        for player in matchqueue_players:
            entry = make_matchqueueplayer_response(player[0], player[1])
            ret.append(entry)
        return jsonify(ret)


class MatchQueueEntryDeleteQuerySchema(ma.Schema):
    force = ma.fields.Boolean(load_default=False)


@bp.route('/<int:player_id>', endpoint='player')
class MatchQueueEntryAPI(MethodView):
    no_jwt_check = ["GET"]

    def get(self, player_id):
        """
        Find a player in the queue by ID
        """
        result = g.db.query(MatchQueuePlayer, CorePlayer) \
            .join(CorePlayer, CorePlayer.player_id == MatchQueuePlayer.player_id) \
            .filter(MatchQueuePlayer.player_id == player_id) \
            .order_by(-MatchQueuePlayer.id).first()

        if not result:
            abort(http_client.NOT_FOUND, message="Player is not in the match queue")

        server = None
        my_matchqueueplayer, my_player = result
        if current_user and \
            current_user["player_id"] == my_matchqueueplayer.player_id and \
            my_matchqueueplayer.match_id:
            match = g.db.query(Match).get(my_matchqueueplayer.match_id)
            log.debug("Looking for %s" % match.server_id)
            server = g.db.query(Server).get(match.server_id)
            if not server:
                log.error("Could not find a server for match %s", my_matchqueueplayer.match_id)
        return jsonify(make_matchqueueplayer_response(my_player, my_matchqueueplayer, server))

    @bp.arguments(MatchQueueEntryDeleteQuerySchema, location='query')
    def delete(self, args, player_id):
        """
        Remove a player from the queue
        """
        if player_id != current_user["player_id"] and "service" not in current_user["roles"]:
            abort(http_client.BAD_REQUEST, message="This is not your player")

        force = args['force']

        log.info("Removing player %d from the match queue", player_id)

        my_matchqueueplayer = g.db.query(MatchQueuePlayer) \
            .filter(MatchQueuePlayer.player_id == player_id) \
            .order_by(-MatchQueuePlayer.id).first()

        if not my_matchqueueplayer:
            abort(http_client.NOT_FOUND, message="Player is not in the queue",
                  error_code="player_not_in_queue")

        if my_matchqueueplayer.status == "matched" and not force:
            abort(http_client.BAD_REQUEST, message="Player has already been matched",
                  error_code="player_already_matched")

        g.db.delete(my_matchqueueplayer)
        g.db.commit()

        return json_response("Player is no longer in the match queue", http_client.OK)


@endpoints.register
def endpoint_info(*args):
    return {"matchqueue": url_for("matchqueue.queue", _external=True)}
