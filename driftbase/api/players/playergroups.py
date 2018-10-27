import logging
import uuid

from six.moves import http_client

from flask import url_for, g, request, jsonify
from flask.views import MethodView
import marshmallow as ma
from flask_restplus import reqparse
from flask_rest_api import Blueprint, abort

from drift.core.extensions.schemachecker import simple_schema_request
from drift.core.extensions.jwt import current_user

from driftbase.models.db import CorePlayer, UserIdentity
from driftbase.players import get_playergroup, set_playergroup

log = logging.getLogger(__name__)

bp = Blueprint("playergroups", __name__, url_prefix='/players')


@bp.route("/<int:player_id>/player-groups/<string:group_name>", endpoint="group")
class PlayerGroupsAPI(MethodView):
    """
    Manage groups of players. Can be used as friends list and such.
    The groups are persisted for a period of 48 hours. Client apps should register
    a new group each time it connects (or initiates a session).
    """

    get_args = reqparse.RequestParser()
    get_args.add_argument("secret", type=str)

    def get(self, player_id, group_name):
        """
        Returns user identities group 'group_name' associated with 'player_id'.
        """
        args = self.get_args.parse_args()
        my_player_id = current_user['player_id']
        pg = get_playergroup(group_name, player_id)

        if player_id != my_player_id:
            secret_ok = pg['secret'] == args.get('secret')
            is_service = 'service' in current_user['roles']
            if not secret_ok and not is_service:
                message = "'player_id' does not match current user. " \
                    "A proper 'secret' or role 'service' is required to use arbitrary 'player_id'."
                abort(http_client.FORBIDDEN, message=message)

        return jsonify(pg)

    @simple_schema_request(
        {
            "identity_names": {"type": "array", "items": {"type": "string"}},
            "player_ids": {"type": "array", "items": {"type": "number"}},
        },
        required=[],
    )
    def put(self, player_id, group_name):
        """
        Create a player group.
        """
        args = request.json
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

        return jsonify(payload), http_client.OK, response_header
