# -*- coding: utf-8 -*-

import logging
from six.moves import http_client
from flask import Blueprint, url_for, g
from flask_restful import Api, Resource, abort
from drift.utils import url_user, url_player
from driftbase.models.db import User, CorePlayer, UserIdentity
from drift.urlregistry import register_endpoints

log = logging.getLogger(__name__)
bp = Blueprint("users", __name__)
api = Api(bp)


class UsersListAPI(Resource):
    """
    list users
    """
    def get(self):
        """

        """
        ret = []
        users = g.db.query(User).order_by(-User.user_id).limit(10)
        for row in users:
            user = {
                "user_id": row.user_id,
                "user_url": url_user(row.user_id)
            }
            ret.append(user)
        return ret


class UsersAPI(Resource):
    """

    """
    def get(self, user_id):
        """

        """
        user = g.db.query(User).filter(User.user_id == user_id).first()
        if not user:
            abort(http_client.NOT_FOUND)

        data = user.as_dict()
        data["client_url"] = None
        if user.client_id:
            data["client_url"] = url_for("client", client_id=user.client_id, _external=True)
        players = g.db.query(CorePlayer).filter(CorePlayer.user_id == user_id)
        data["players"] = []
        for player in players:
            data["players"].append({"player_id": player.player_id,
                                    "player_name": player.player_name,
                                    "player_url": url_player(player.player_id)
                                    })
        identities = g.db.query(UserIdentity).filter(UserIdentity.user_id == user_id)
        data["identities"] = []
        for identity in identities:
            data["identities"].append({"identity_id": identity.identity_id,
                                       "name": identity.name,
                                       "type": identity.identity_type,
                                       "logon_date": identity.logon_date,
                                       "num_logons": identity.num_logons,
                                       })

        return data


api.add_resource(UsersListAPI, "/users", endpoint="users")
api.add_resource(UsersAPI, '/users/<int:user_id>', endpoint="user")


@register_endpoints
def endpoint_info(current_user):
    ret = {"users": url_for("users.users", _external=True), }
    ret["my_user"] = None
    if current_user:
        ret["my_user"] = url_for("users.user", user_id=current_user["user_id"], _external=True)
    return ret
