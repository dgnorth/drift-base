import logging
import uuid

import marshmallow as ma
from drift.core.extensions.jwt import current_user
from drift.utils import Url
from flask import url_for, g
from flask.views import MethodView
from flask_smorest import Blueprint, abort, utils
import http.client as http_client

from driftbase.models.db import CorePlayer, UserIdentity
from driftbase.players import get_playergroup, set_playergroup

log = logging.getLogger(__name__)

bp = Blueprint("playergroups", __name__, url_prefix='/players/<int:player_id>/player-groups')


class PlayerGroupGetRequestSchema(ma.Schema):
    secret = ma.fields.String(metadata=dict(description="Shared secret for this group"))


class PlayerGroupPutRequestSchema(ma.Schema):
    identity_names = ma.fields.List(ma.fields.String())
    player_ids = ma.fields.List(ma.fields.Integer())


class PlayerGroupPlayerSchema(ma.Schema):
    player_id = ma.fields.Integer()
    player_url = Url('players.entry', player_id='<player_id>', doc='Player resource')
    player_name = ma.fields.String()
    identity_name = ma.fields.String()


class PlayerGroupResponseSchema(ma.Schema):
    group_name = ma.fields.String()
    player_id = ma.fields.Integer()
    players = ma.fields.List(ma.fields.Nested(PlayerGroupPlayerSchema()))
    secret = ma.fields.String()


@bp.route("/<string:group_name>", endpoint="group")
class PlayerGroupsAPI(MethodView):
    """
    Manage groups of players. Can be used as friends list and such.
    The groups are persisted for a period of 48 hours. Client apps should register
    a new group each time it connects (or initiates a session).
    """

    @bp.arguments(PlayerGroupGetRequestSchema, location='query')
    @bp.response(http_client.OK, PlayerGroupResponseSchema)
    def get(self, args, player_id, group_name):
        """
        Get group for player

        Returns user identities group 'group_name' associated with 'player_id'.
        """
        my_player_id = current_user['player_id']
        pg = get_playergroup(group_name, player_id)

        if player_id != my_player_id:
            secret_ok = pg['secret'] == args.get('secret')
            is_service = 'service' in current_user['roles']
            if not secret_ok and not is_service:
                message = "'player_id' does not match current user. " \
                    "A proper 'secret' or role 'service' is required to use arbitrary 'player_id'."
                abort(http_client.FORBIDDEN, message=message)
        return pg

    @bp.arguments(PlayerGroupPutRequestSchema)
    @bp.response(http_client.OK, PlayerGroupResponseSchema)
    def put(self, args, player_id, group_name):
        """
        Create a player group

        Creates a new player group for the player. Can only be called by the
        player or from a service.
        """
        if not args:
            abort(http_client.BAD_REQUEST, message="JSON body missing.")

        my_player_id = current_user['player_id']

        if 'service' not in current_user['roles'] and player_id != my_player_id:
            abort(http_client.BAD_REQUEST,
                  message="Role 'service' is required to use arbitrary 'player_id'.")

        # Map identity names to player ids
        rows = []
        if 'identity_names' in args and len(args['identity_names']):
            rows += g.db.query(UserIdentity, CorePlayer) \
                        .filter(UserIdentity.name.in_(args['identity_names']),
                                CorePlayer.user_id == UserIdentity.user_id) \
                        .all()

        if 'player_ids' in args and len(args['player_ids']):
            rows += g.db.query(UserIdentity, CorePlayer) \
                        .filter(CorePlayer.player_id.in_(args['player_ids']),
                                CorePlayer.user_id == UserIdentity.user_id) \
                        .all()

        # Populate a dict keyed to player_id to eliminate duplicates
        player_group = {
            player_row.player_id: {
                "player_id": player_row.player_id,
                "player_url": url_for("players.entry",
                                      player_id=player_row.player_id,
                                      _external=True),
                "player_name": player_row.player_name,
                "identity_name": user_row.name,
            }
            for user_row, player_row in rows
        }
        player_group = list(player_group.values())
        payload = {
            "group_name": group_name,
            "player_id": player_id,
            "players": player_group,
            "secret": str(uuid.uuid4()).replace("-", ""),
        }

        set_playergroup(group_name, player_id, payload)
        resource_uri = url_for("playergroups.group", group_name=group_name,
                               player_id=player_id, _external=True)
        response_header = {"Location": resource_uri}
        log.info("Created user group %s for player %s", group_name, player_id)
        utils.get_appcontext().setdefault('headers', {}).update(response_header)
        return payload
