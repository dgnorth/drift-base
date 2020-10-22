import logging

from flask import jsonify
from flask.views import MethodView
from flask_smorest import Blueprint, abort

from driftbase.players import can_edit_player

log = logging.getLogger(__name__)

bp = Blueprint("player_inventory", __name__, url_prefix='/players', description="Datastore for personal inventory metadata")


@bp.route("/<int:player_id>/inventory", endpoint="list")
class InventoryAPI(MethodView):

    def get(self, player_id):
        """
        Get a list of all inventory items for the player
        """
        can_edit_player(player_id)
        return jsonify([])

