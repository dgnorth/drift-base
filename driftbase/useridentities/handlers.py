# -*- coding: utf-8 -*-

import logging

import six
from six.moves import http_client

from flask import Blueprint, url_for, g, request
from flask import make_response, jsonify
from flask_restful import Api, Resource, reqparse, abort

from drift.urlregistry import register_endpoints
from drift.core.extensions.schemachecker import simple_schema_request
from drift.core.extensions.jwt import current_user, get_cached_token

from driftbase.models.db import User, CorePlayer, UserIdentity

log = logging.getLogger(__name__)
bp = Blueprint("useridentities", __name__)
api = Api(bp)


class UserIdentitiesAPI(Resource):

    get_args = reqparse.RequestParser()
    get_args.add_argument("name", type=six.text_type, action='append')
    get_args.add_argument("player_id", type=int, action='append')

    def get(self):
        """
        Convert user identities to player_ids
        """
        args = self.get_args.parse_args()
        player_ids = args.get("player_id")
        names = args.get("name")
        if player_ids and names:
            abort(http_client.BAD_REQUEST,
                  message="You cannot ask for 'name' and 'player_id'. Pick one.")
        if not any([player_ids, names]):
            abort(http_client.BAD_REQUEST,
                  message="Endpoint expects 'name' or 'player_id'.")

        ret = []
        rows = []
        if names:
            rows = g.db.query(UserIdentity, CorePlayer) \
                       .filter(UserIdentity.name.in_(names),
                               CorePlayer.user_id == UserIdentity.user_id) \
                       .all()
        elif player_ids:
            rows = g.db.query(UserIdentity, CorePlayer) \
                       .filter(CorePlayer.player_id.in_(player_ids),
                               CorePlayer.user_id == UserIdentity.user_id) \
                       .all()
        for r in rows:
            d = {
                "player_id": r[1].player_id,
                "player_url": url_for("players.player", player_id=r[1].player_id, _external=True),
                "player_name": r[1].player_name,
                "identity_name": r[0].name,
            }
            ret.append(d)
        return ret

    @simple_schema_request({
        "link_with_user_id": {"type": "number", },
        "link_with_user_jti": {"type": "string", },
    })
    def post(self):
        """
        Associate the current user identity (in the auth header context) with
        the passed in user. We use the JTI for an identity associated with that
        user to verify that the caller is indeed the owner of the user
        """
        args = request.json
        link_with_user_id = args["link_with_user_id"]
        link_with_user_jti = args["link_with_user_jti"]

        my_user_id = current_user["user_id"]
        my_identity_id = current_user["identity_id"]

        if my_user_id == link_with_user_id:
            log.warning("User identity %s is already linked with user_id %s in the JWT. "
                     "Rejecting the switch",
                     my_identity_id, link_with_user_id)
            abort(http_client.BAD_REQUEST, message="Identity is already associated with user %s" %
                  link_with_user_id)

        # my_user_id is 0 if I am a game center guy without a user

        link_with_user = g.db.query(User).get(link_with_user_id)
        if not link_with_user:
            abort(http_client.NOT_FOUND, message="User %s not found" % link_with_user_id)

        if link_with_user.status != "active":
            abort(http_client.NOT_FOUND, message="User %s is not active" % link_with_user_id)

        # Verify that link_with_user_id matches user_id in link_with_user_jti
        link_with_user_jti_payload = get_cached_token(link_with_user_jti)
        if link_with_user_jti_payload["user_id"] != link_with_user_id:
            log.warning("Request for a user identity switch with user_id %s which does not "
                     "match user_id %s from JWT",
                     link_with_user_id, link_with_user_jti_payload["user_id"])
            abort(http_client.BAD_REQUEST, message="User does not match JWT user")

        link_with_player = g.db.query(CorePlayer) \
                               .filter(CorePlayer.user_id == link_with_user_id) \
                               .first()

        if not link_with_player:
            abort(http_client.NOT_FOUND, message="Player for user %s not found" % link_with_user_id)

        if link_with_player.status != "active":
            abort(http_client.NOT_FOUND, message="Player for user %s is not active" % link_with_user_id)

        link_with_player_id = link_with_player.player_id

        my_identity = g.db.query(UserIdentity).get(my_identity_id)

        if my_identity.user_id:
            if my_identity.user_id == link_with_user_id:
                log.warning("User identity %s is already linked with user_id %s in the db. "
                         "Looks like the caller is trying to make an association again",
                         my_identity_id, link_with_user_id)
                abort(http_client.BAD_REQUEST, message="Identity is already associated with user %s" %
                      link_with_user_id)

            log.warning("Caller with identity %s already has a user_id %s associated with the "
                     "identity. This user will probably become orphaned",
                     my_identity_id, my_user_id)

        # If we are associating a gamecenter identity with an existing user, then that
        # user cannot have another game center association already in place.
        # In other words: A user can have one, and only one game center identity.
        # Because of reasons.
        # Note that this _only_ applies to gamecenter and not other identity types.
        if my_identity.identity_type == "gamecenter":
            other_identities = g.db.query(UserIdentity) \
                                   .filter(UserIdentity.user_id == link_with_user_id,
                                           UserIdentity.identity_type == "gamecenter") \
                                   .all()
            if other_identities:
                log.info("User Identity %s of type '%s' cannot associate with user %s because "
                         "an identity of the same type with identity_id %s is already "
                         "associated with the user",
                         my_identity_id, my_identity.identity_type, link_with_user_id,
                         other_identities[0].identity_id)
                # Note: Temporary workaround for 0.7.x clients
                status = http_client.FORBIDDEN
                ret = {
                    "code": "linked_account_already_claimed",
                    "message": "An identity of the same type is already associated with this user",
                    "status": status,
                    "status_code": status,
                    "error": {
                        "description": "An identity of the same type is already "
                                       "associated with this user",
                        "code": "linked_account_already_claimed",
                    }
                }
                return make_response(jsonify(ret), status)
                # !Temp hack done

                abort(http_client.FORBIDDEN,
                      code='linked_account_already_claimed',
                      description="An identity of the same type is "
                                  "already associated with this user"
                      )

        my_identity.user_id = link_with_user.user_id
        g.db.commit()

        log.info("User identity %s has been switched from user_id %s to "
                 "user_id %s who has player_id %s",
                 my_identity_id, my_user_id, link_with_user_id, link_with_player_id)

        # TODO: We should log this into the db but we don't have db logging set up yet

        return "OK"


api.add_resource(UserIdentitiesAPI, '/user-identities', endpoint="useridentities")


# TODO: Remove legacy name "user-identities" once all clients has been patched to use the new name

@register_endpoints
def endpoint_info(current_user):
    ret = {
        "user_identities": url_for("useridentities.useridentities", _external=True),
        "user-identities": url_for("useridentities.useridentities", _external=True),
    }
    return ret
