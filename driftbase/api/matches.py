import datetime
import logging
from contextlib import ExitStack

import marshmallow as ma
from drift.core.extensions.jwt import current_user, requires_roles
from drift.core.extensions.urlregistry import Endpoints
from flask import url_for, g, jsonify
from flask.views import MethodView
from flask_restx import reqparse
from flask_smorest import Blueprint, abort
import http.client as http_client

from driftbase.matchqueue import process_match_queue
from driftbase.models.db import Machine, Server, Match, MatchTeam, MatchPlayer, MatchQueuePlayer
from driftbase.utils import log_match_event
from driftbase.utils import url_player

log = logging.getLogger(__name__)

bp = Blueprint("matches", __name__, url_prefix="/matches", description="Realtime matches")
endpoints = Endpoints()

MATCH_HEARTBEAT_TIMEOUT_SECONDS = 60


def drift_init_extension(app, api, **kwargs):
    api.register_blueprint(bp)
    endpoints.init_app(app)


def utcnow():
    return datetime.datetime.utcnow()


@bp.route('/active', endpoint='active')
class ActiveMatchesAPI(MethodView):
    """UE4 matches available for matchmaking
    """
    get_args = reqparse.RequestParser()
    get_args.add_argument("ref", type=str, required=False)
    get_args.add_argument("placement", type=str, required=False)
    get_args.add_argument("realm", type=str, required=False)
    get_args.add_argument("version", type=str, required=False)
    get_args.add_argument("player_id", type=int, action='append')
    get_args.add_argument("rows", type=int, required=False)

    def get(self):
        """
        Get active matches

        This endpoint used by clients to fetch a list of matches available
        for joining
        """
        args = self.get_args.parse_args()
        num_rows = args.get("rows") or 100

        query = g.db.query(Match, Server, Machine)
        query = query.filter(Server.machine_id == Machine.machine_id,
                             Match.server_id == Server.server_id,
                             Match.status.notin_(["ended", "completed"]),
                             Server.status.in_(["started", "running", "active", "ready"]),
                             Server.heartbeat_date >= utcnow() - datetime.timedelta(
                                 seconds=MATCH_HEARTBEAT_TIMEOUT_SECONDS)
                             )
        if args.get("ref"):
            query = query.filter(Server.ref == args.get("ref"))
        if args.get("version"):
            query = query.filter(Server.version == args.get("version"))
        if args.get("placement"):
            query = query.filter(Machine.placement == args.get("placement"))
        if args.get("realm"):
            query = query.filter(Machine.realm == args.get("realm"))
        player_ids = []
        if args.get("player_id"):
            player_ids = args.get("player_id")

        query = query.order_by(-Match.num_players, -Match.server_id)
        query = query.limit(num_rows)
        rows = query.all()

        ret = []
        for row in rows:
            include = True
            if player_ids:
                include = False

            match = row[0]
            server = row[1]
            machine = row[2]
            record = {}
            record["create_date"] = match.create_date
            record["game_mode"] = match.game_mode
            record["map_name"] = match.map_name
            record["max_players"] = match.max_players
            record["match_status"] = match.status
            record["server_status"] = server.status
            record["public_ip"] = server.public_ip
            record["port"] = server.port
            record["version"] = server.version
            record["match_id"] = match.match_id
            record["server_id"] = match.server_id
            record["machine_id"] = server.machine_id
            record["heartbeat_date"] = server.heartbeat_date
            record["realm"] = machine.realm
            record["placement"] = machine.placement
            record["ref"] = server.ref
            record["match_url"] = url_for("matches.entry",
                                          match_id=match.match_id,
                                          _external=True)
            record["server_url"] = url_for("servers.entry",
                                           server_id=server.server_id,
                                           _external=True)
            record["machine_url"] = url_for("machines.entry",
                                            machine_id=server.machine_id,
                                            _external=True)
            conn_url = "%s:%s?player_id=%s?token=%s"
            record["ue4_connection_url"] = conn_url % (server.public_ip,
                                                       server.port,
                                                       current_user["player_id"],
                                                       server.token)
            player_array = []
            players = g.db.query(MatchPlayer) \
                .filter(MatchPlayer.match_id == match.match_id,
                        MatchPlayer.status.in_(["active"])) \
                .all()
            for player in players:
                player_array.append({
                    "player_id": player.player_id,
                    "player_url": url_player(player.player_id),
                })
                if player.player_id in player_ids:
                    include = True
            record["players"] = player_array
            record["num_players"] = len(player_array)

            if include:
                ret.append(record)

        return jsonify(ret)


def unique_key_in_use(unique_key):
    if unique_key:
        query = g.db.query(Match, Server)
        existing_unique_match = query.filter(Match.server_id == Server.server_id,
                                             Match.status.notin_(["ended", "completed"]),
                                             Match.unique_key == unique_key,
                                             Server.status.in_(["started", "running", "active", "ready"]),
                                             Server.heartbeat_date >= utcnow() - datetime.timedelta(
                                                 seconds=MATCH_HEARTBEAT_TIMEOUT_SECONDS)
                                             ).first()
        return existing_unique_match is not None
    return False


def lock(redis):
    # Moving this into a separate function so systems test can mock it out.
    return redis.lock("ensure_match_unique_key")


class MatchesPostRequestSchema(ma.Schema):
    server_id = ma.fields.Integer(required=True)

    num_players = ma.fields.Integer()
    max_players = ma.fields.Integer()
    map_name = ma.fields.String()
    game_mode = ma.fields.String()
    status = ma.fields.String()
    unique_key = ma.fields.String()
    match_statistics = ma.fields.Dict()
    details = ma.fields.Dict()
    num_teams = ma.fields.Integer()


class MatchPutRequestSchema(ma.Schema):
    status = ma.fields.String(required=True)

    server_id = ma.fields.Integer()
    num_players = ma.fields.Integer()
    max_players = ma.fields.Integer()
    map_name = ma.fields.String()
    game_mode = ma.fields.String()
    unique_key = ma.fields.String()
    match_statistics = ma.fields.Dict()
    details = ma.fields.Dict()


@bp.route('', endpoint='list')
class MatchesAPI(MethodView):
    """UE4 match
    """
    get_args = reqparse.RequestParser()
    get_args.add_argument("server_id", type=int, required=False)
    get_args.add_argument("rows", type=int, required=False)

    @requires_roles("service")
    def get(self):
        """This endpoint used by services and clients to fetch recent matches.
        Dump the DB rows out as json
        """
        args = self.get_args.parse_args()
        num_rows = args.get("rows") or 100

        query = g.db.query(Match)
        if args.get("server_id"):
            query = query.filter(Match.server_id == args.get("server_id"))
        query = query.order_by(-Match.match_id)
        query = query.limit(num_rows)
        rows = query.all()

        ret = []
        for row in rows:
            record = row.as_dict()
            record["url"] = url_for("matches.entry", match_id=row.match_id, _external=True)
            ret.append(record)
        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(MatchesPostRequestSchema)
    def post(self, args):
        """Register a new battle on the passed in match server.
        Each match server should always have a single battle.
        A match server will have zero matches only when it doesn't start up.
        Either the celery match server task (in normal EC2 mode) or the
        match server unreal process (in local development mode) will call
        this endpoint to create the battle resource.
        """
        server_id = args.get("server_id")
        unique_key = args.get("unique_key")
        details = args.get("details")

        with ExitStack() as stack:
            if unique_key:
                stack.enter_context(lock(g.redis))

            if unique_key_in_use(unique_key):
                log.info("Tried to set the unique key '{}' of a battle when one already exists".format(unique_key))
                abort(http_client.CONFLICT, description="An existing match with the same unique_key was found")

            match = Match(server_id=server_id,
                          num_players=args.get("num_players", 0),
                          max_players=args.get("max_players"),
                          map_name=args.get("map_name"),
                          game_mode=args.get("game_mode"),
                          status=args.get("status"),
                          status_date=utcnow(),
                          start_date=None,
                          match_statistics=args.get("match_statistics"),
                          details=details,
                          unique_key=unique_key,
                          )
            g.db.add(match)
            g.db.flush()
            # ! have to set this explicitly after the row is created
            match.start_date = None
            g.db.commit()
            match_id = match.match_id

            if args.get("num_teams"):
                for i in range(args.get("num_teams")):
                    team = MatchTeam(match_id=match_id,
                                     name="Team %s" % (i + 1)
                                     )
                    g.db.add(team)
                g.db.commit()

            resource_uri = url_for("matches.entry", match_id=match_id, _external=True)
            players_resource_uri = url_for("matches.players", match_id=match_id, _external=True)
            response_header = {
                "Location": resource_uri,
            }

            log.info("Created match %s for server %s", match_id, server_id)
            log_match_event(match_id, None, "gameserver.match.created",
                            details={"server_id": server_id})

            try:
                process_match_queue()
            except Exception:
                log.exception("Unable to process match queue")

            return jsonify({"match_id": match_id,
                            "url": resource_uri,
                            "players_url": players_resource_uri,
                            }), http_client.CREATED, response_header


@bp.route('/<int:match_id>', endpoint='entry')
class MatchAPI(MethodView):
    """
    Information about specific matches
    """

    @requires_roles("service")
    def get(self, match_id):
        """
        Find battle by ID

        Get information about a single battle. Dumps out the DB row as json
        URL's are provided for additional information about the battle for
        drilldown. Machine and matcheserver url's are also written out.
        """
        match = g.db.query(Match).get(match_id)
        if not match:
            abort(http_client.NOT_FOUND)

        ret = match.as_dict()
        ret["url"] = url_for("matches.entry", match_id=match_id, _external=True)

        server = g.db.query(Server).get(match.server_id)
        ret["server"] = None
        ret["server_url"] = None
        ret["machine_url"] = None
        if server:
            ret["server"] = server.as_dict()
            ret["server_url"] = url_for("servers.entry", server_id=server.server_id, _external=True)

            machine = g.db.query(Machine).get(server.machine_id)
            ret["machine"] = None
            if machine:
                ret["machine_url"] = url_for("machines.entry",
                                             machine_id=machine.machine_id, _external=True)

        teams = []
        rows = g.db.query(MatchTeam).filter(MatchTeam.match_id == match_id).all()
        for r in rows:
            team = r.as_dict()
            team["url"] = url_for("matches.team", match_id=match_id, team_id=r.team_id,
                                  _external=True)
            teams.append(team)
        ret["teams"] = teams

        ret["matchplayers_url"] = url_for("matches.players", match_id=match_id, _external=True)
        ret["teams_url"] = url_for("matches.teams", match_id=match_id, _external=True)

        players = []
        rows = g.db.query(MatchPlayer).filter(MatchPlayer.match_id == match_id).all()
        for r in rows:
            player = r.as_dict()
            player["matchplayer_url"] = url_for("matches.player", match_id=match_id,
                                                player_id=r.player_id, _external=True)
            player["player_url"] = url_player(r.player_id)
            players.append(player)
        ret["players"] = players
        ret["num_players"] = len(players)

        log.debug("Returning info for match %s", match_id)

        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(MatchPutRequestSchema)
    def put(self, args, match_id):
        """
        Update battle status

        The UE4 server calls this method to update its status and any
        metadata that the backend should know about
        """

        log.debug("Updating battle %s", match_id)
        unique_key = args.get("unique_key")

        with ExitStack() as stack:
            if unique_key:
                stack.enter_context(lock(g.redis))

            match = g.db.query(Match).get(match_id)
            if not match:
                abort(http_client.NOT_FOUND)
            new_status = args.get("status")
            if match.status == "completed":
                log.warning("Trying to update a completed battle %d. Ignoring update", match_id)
                abort(http_client.BAD_REQUEST, description="Battle has already been completed.")

            current_unique_key = match.unique_key
            if unique_key and current_unique_key:
                log.info("Tried to update the unique key of a battle with a non-empty unique key '{}'->'{}'".format(
                    current_unique_key, unique_key))
                abort(http_client.CONFLICT, description="Battle unique key must not be changed from a non-empty value")

            if unique_key_in_use(unique_key):
                log.info("Tried to set the unique key '{}' of a battle when one already exists".format(unique_key))
                abort(http_client.CONFLICT, description="An existing match with the same unique_key was found")

            if match.status != new_status:
                log.info("Changing status of match %s from '%s' to '%s'",
                         match_id, match.status, args["status"])
                if new_status == "started":
                    match.start_date = utcnow()
                elif new_status == "completed":
                    match.end_date = utcnow()
                    # ! TODO: Set leave_date on matchplayers who are still in the match
                match.status_date = utcnow()

            for arg in args:
                setattr(match, arg, args[arg])
            g.db.commit()

            resource_uri = url_for("matches.entry", match_id=match_id, _external=True)
            response_header = {
                "Location": resource_uri,
            }
            ret = {"match_id": match_id,
                   "url": resource_uri,
                   }

            log.info("Match %s has been updated.", match_id)

            return jsonify(ret), http_client.OK, response_header


class MatchTeamsPostRequestSchema(ma.Schema):
    name = ma.fields.String()
    statistics = ma.fields.Dict()
    details = ma.fields.Dict()


class MatchTeamPutRequestSchema(ma.Schema):
    name = ma.fields.String()
    statistics = ma.fields.Dict()
    details = ma.fields.Dict()


@bp.route('/<int:match_id>/teams', endpoint='teams')
class MatchTeamsAPI(MethodView):
    """
    All teams in a match
    """

    @requires_roles("service")
    def get(self, match_id):
        """
        Find teams by match
        """
        query = g.db.query(MatchTeam)
        query = query.filter(MatchTeam.match_id == match_id)
        rows = query.all()

        ret = []
        for row in rows:
            record = row.as_dict()
            record["url"] = url_for("matches.team",
                                    match_id=match_id,
                                    team_id=row.team_id,
                                    _external=True)
            ret.append(record)
        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(MatchTeamsPostRequestSchema)
    def post(self, args, match_id):
        """
        Add a team to a match
        """
        team = MatchTeam(match_id=match_id,
                         name=args.get("name"),
                         statistics=args.get("statistics"),
                         details=args.get("details"),
                         )
        g.db.add(team)
        g.db.commit()
        team_id = team.team_id
        resource_uri = url_for("matches.team", match_id=match_id, team_id=team_id, _external=True)
        response_header = {"Location": resource_uri}

        log.info("Created team %s for match %s", team_id, match_id)
        log_match_event(match_id,
                        None,
                        "gameserver.match.team_created",
                        details={"team_id": team_id})

        return jsonify({"team_id": team_id,
                        "url": resource_uri,
                        }), http_client.CREATED, response_header


@bp.route('/<int:match_id>/teams/<int:team_id>', endpoint='team')
class MatchTeamAPI(MethodView):
    """
    A specific team in a match
    """

    @requires_roles("service")
    def get(self, match_id, team_id):
        """
        Find a team in a match by ID's
        """
        query = g.db.query(MatchTeam)
        query = query.filter(MatchTeam.match_id == match_id,
                             MatchTeam.team_id == team_id)
        row = query.first()
        if not row:
            abort(http_client.NOT_FOUND)

        ret = row.as_dict()
        ret["url"] = url_for("matches.team", match_id=match_id, team_id=row.team_id, _external=True)

        query = g.db.query(MatchPlayer)
        query = query.filter(MatchPlayer.match_id == match_id,
                             MatchPlayer.team_id == team_id)
        rows = query.all()
        players = []
        for r in rows:
            player = r.as_dict()
            player["matchplayer_url"] = url_for("matches.player",
                                                match_id=match_id,
                                                player_id=r.player_id,
                                                _external=True)
            player["player_url"] = url_player(r.player_id)
            players.append(player)
        ret["players"] = players
        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(MatchTeamPutRequestSchema)
    def put(self, args, match_id, team_id):
        team = g.db.query(MatchTeam).get(team_id)
        if not team:
            abort(http_client.NOT_FOUND)
        for arg in args:
            setattr(team, arg, args[arg])
        g.db.commit()
        ret = team.as_dict()
        return jsonify(ret)


class MatchPlayerPostSchema(ma.Schema):
    player_id = ma.fields.Integer(required=True)
    team_id = ma.fields.Integer()


@bp.route('/<int:match_id>/players', endpoint='players')
class MatchPlayersAPI(MethodView):
    """
    Players in a specific match. The UE4 server will post to this endpoint
    to add a player to a match.
    """

    def get(self, match_id):
        """
        Get players from a match
        """
        rows = g.db.query(MatchPlayer) \
            .filter(MatchPlayer.match_id == match_id) \
            .all()
        ret = []
        for r in rows:
            player = r.as_dict()
            player["matchplayer_url"] = url_for("matches.player",
                                                match_id=match_id,
                                                player_id=r.player_id,
                                                _external=True)
            player["player_url"] = url_player(r.player_id)
            ret.append(player)

        return jsonify(ret)

    @requires_roles("service")
    @bp.arguments(MatchPlayerPostSchema)
    def post(self, args, match_id):
        """
        Add a player to a match
        """
        log.info(f"POST to MatchPlayersAPI with match_id {match_id} and args {args}")
        player_id = args["player_id"]
        team_id = args.get("team_id", None)

        log.info(f"  dug up player_id {player_id} (type {type(player_id)}) and team_id {team_id} (type {type(team_id)})")
        match = g.db.query(Match).get(match_id)
        if not match:
            log.warning(f" match {match_id} not found. Aborting")
            abort(http_client.NOT_FOUND, description="Match not found")

        if match.status == "completed":
            log.warning(f" match {match_id} is completed. Aborting")
            abort(http_client.BAD_REQUEST, description="You cannot add a player to a completed battle")

        num_players = g.db.query(MatchPlayer) \
            .filter(MatchPlayer.match_id == match.match_id,
                    MatchPlayer.status.in_(["active"])) \
            .count()
        if num_players >= match.max_players:
            log.warning(f" match {match_id} has {num_players} and maximum is {match.max_players}. Aborting")
            abort(http_client.BAD_REQUEST, description="Match is full")

        if team_id:
            team = g.db.query(MatchTeam).get(team_id)
            if not team:
                log.warning(f" team_id {team_id} not found. Aborting.")
                abort(http_client.NOT_FOUND, description="Team not found")
            if team.match_id != match_id:
                log.warning(f" team_id {team_id} doesn't belong to match {match_id}, it belongs to match {team.match_id}. Aborting.")
                abort(http_client.BAD_REQUEST,
                      description="Team %s is not in match %s" % (team_id, match_id))

        match_player = g.db.query(MatchPlayer) \
            .filter(MatchPlayer.match_id == match_id,
                    MatchPlayer.player_id == player_id) \
            .first()
        if not match_player:
            log.info(f" player {player_id} not found in match already. Adding him...")
            match_player = MatchPlayer(match_id=match_id,
                                       player_id=player_id,
                                       team_id=team_id,
                                       num_joins=0,
                                       seconds=0,
                                       status="active")
            g.db.add(match_player)
        match_player.num_joins += 1
        match_player.join_date = utcnow()
        match_player.status = "active"

        # remove the player from the match queue
        g.db.query(MatchQueuePlayer).filter(MatchQueuePlayer.player_id == player_id).delete()

        if match.start_date is None:
            match.start_date = utcnow()

        g.db.commit()

        # prepare the response
        resource_uri = url_for("matches.player",
                               match_id=match_id,
                               player_id=player_id,
                               _external=True)
        response_header = {"Location": resource_uri}
        log.info("Player %s has joined match %s in team %s.", player_id, match_id, team_id)

        log_match_event(match_id, player_id, "gameserver.match.player_joined",
                        details={"team_id": team_id})

        return jsonify({"match_id": match_id,
                        "player_id": player_id,
                        "team_id": team_id,
                        "url": resource_uri,
                        }), http_client.CREATED, response_header


@bp.route('/<int:match_id>/players/<int:player_id>', endpoint='player')
class MatchPlayerAPI(MethodView):
    """
    A specific player in a specific match
    """

    def get(self, match_id, player_id):
        """
        Get a specific player from a battle
        """
        player = g.db.query(MatchPlayer) \
            .filter(MatchPlayer.match_id == match_id, MatchPlayer.player_id == player_id) \
            .first()
        if not player:
            abort(http_client.NOT_FOUND)

        ret = player.as_dict()
        ret["team_url"] = None
        if player.team_id:
            ret["team_url"] = url_for("matches.team", match_id=match_id,
                                      team_id=player.team_id, _external=True)
        ret["player_url"] = url_player(player_id)
        return jsonify(ret)

    @requires_roles("service")
    def delete(self, match_id, player_id):
        """
        A player has left an ongoing battle
        """
        match_player = g.db.query(MatchPlayer) \
            .filter(MatchPlayer.match_id == match_id,
                    MatchPlayer.player_id == player_id) \
            .first()
        if not match_player:
            abort(http_client.NOT_FOUND)

        if match_player.status != "active":
            abort(http_client.BAD_REQUEST, description="Player status must be active, not '%s'" %
                                                       match_player.status)

        match = g.db.query(Match).get(match_id)
        if not match:
            abort(http_client.NOT_FOUND, description="Match not found")

        if match.status == "completed":
            log.warning("Attempting to remove player %s from battle %s which has already completed",
                        player_id, match_id)
            abort(http_client.BAD_REQUEST,
                  description="You cannot remove a player from a completed match")

        team_id = match_player.team_id

        match_player.status = "quit"
        num_seconds = (utcnow() - match_player.join_date).total_seconds()
        match_player.leave_date = utcnow()
        match_player.seconds += num_seconds

        g.db.commit()

        log.info("Player %s has left battle %s", player_id, match_id)
        log_match_event(match_id, player_id,
                        "gameserver.match.player_left",
                        details={"team_id": team_id})

        return jsonify({"message": "Player has left the battle"})


@endpoints.register
def endpoint_info(*args):
    ret = {
        "active_matches": url_for("matches.active", _external=True),
        "matches": url_for("matches.list", _external=True),
    }
    return ret
