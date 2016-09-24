# -*- coding: utf-8 -*-

import logging
import httplib

from werkzeug.security import pbkdf2_hex

from flask import g, current_app
from flask_restful import abort

from driftbase.db.models import User, CorePlayer, UserIdentity, UserRole
from driftbase.utils import UserCache

log = logging.getLogger(__name__)


def authenticate(username, password):
    """basic authentication"""
    identity_type = ""
    create_roles = []
    lst = username.split(":")
    # old backwards compatible (non-identity)
    is_old = True
    if len(lst) > 1:
        identity_type = lst[0]
        is_old = False
    else:
        log.info("Old-style authentication for '%s'", username)
    automatic_account_creation = True
    if identity_type.lower() == "gamecenter":
        automatic_account_creation = False
        username = pbkdf2_hex(username, "staticsalt", iterations=25000)
        username = "%s:%s" % (identity_type, username)
        log.info("Hashed gamecenter username: %s", username)

    identity_id = 0

    my_identity = g.db.query(UserIdentity) \
                      .filter(UserIdentity.name == username) \
                      .first()

    service_user = current_app.config.get("service_user")
    if not service_user:
        raise RuntimeError("service_user not found in config!")

    # if we do not have an identity, create one along with a user and a player
    if my_identity is None:
        # if this is a service user make sure the password
        # matches before creating the user
        if username == service_user["username"]:
            if password != service_user["password"]:
                log.error("Attempting to log in as service "
                          "user without correct password!")
                abort(httplib.METHOD_NOT_ALLOWED,
                      message="Incorrect password for service user")
            else:
                create_roles.append("service")

        my_identity = UserIdentity(name=username, identity_type=identity_type)
        my_identity.set_password(password)
        if is_old:
            my_user = g.db.query(User) \
                          .filter(User.user_name == username) \
                          .first()
            if my_user:
                my_identity.user_id = my_user.user_id
                log.info("Found an old-style user. Hacking it into identity")

        g.db.add(my_identity)
        g.db.flush()
        log.info("User Identity '%s' has been created with id %s",
                 username, my_identity.identity_id)
    else:
        if not my_identity.check_password(password):
            abort(httplib.METHOD_NOT_ALLOWED, message="Incorrect password")
            return

    if my_identity:
        identity_id = my_identity.identity_id

    my_user = None
    my_player = None
    my_user_name = ""
    user_id = 0
    user_roles = []
    player_id = 0
    player_name = ""
    if my_identity.user_id:
        my_user = g.db.query(User).get(my_identity.user_id)
        if my_user.status != "active":
            log.info("Logon identity is using an inactive user %s, "
                     "creating new one", my_user.user_id)
            my_user = None
        else:
            user_id = my_user.user_id

    if my_user is None:
        if not automatic_account_creation:
            log.info("User Identity %s has no user but "
                     "automatic_account_creation is false so he "
                     "gets no user account",
                     my_identity.identity_id)
        else:
            my_user = User(user_name=username)
            g.db.add(my_user)
            # this is so we can access the auto-increment key value
            g.db.flush()
            user_id = my_user.user_id
            for role_name in create_roles:
                role = UserRole(user_id=user_id, role=role_name)
                g.db.add(role)
            my_identity.user_id = user_id
            log.info("User '%s' has been created with user_id %s",
                     username, user_id)

    if my_user:
        user_roles = [r.role for r in my_user.roles]
        user_id = my_user.user_id
        my_user_name = my_user.user_name

        my_player = g.db.query(CorePlayer) \
                        .filter(CorePlayer.user_id == user_id) \
                        .first()

        if my_player is None:
            my_player = CorePlayer(user_id=user_id, player_name=u"")
            g.db.add(my_player)
            # this is so we can access the auto-increment key value
            g.db.flush()
            log.info("Player for user %s has been created with player_id %s",
                     my_user.user_id, my_player.player_id)

    if my_player:
        player_id = my_player.player_id
        player_name = my_player.player_name

    if my_user and not my_user.default_player_id:
        my_user.default_player_id = my_player.player_id

    g.db.commit()

    # store the user information in the cache for later lookup
    ret = {
        "user_name": my_user_name,
        "user_id": user_id,
        "identity_id": identity_id,
        "player_id": player_id,
        "player_name": player_name,
        "roles": user_roles,
    }
    cache = UserCache()
    cache.set_all(user_id, ret)
    return ret


def private_key():
    # To generate: ssh-keygen -t rsa -b 768 -C "drift-base@dg-api.com"
    return current_app.config.get("private_key")
