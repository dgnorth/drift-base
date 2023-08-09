import http.client

import http.client as http_client
import logging
import uuid

from flask import g, current_app
from drift.blueprint import abort

from driftbase.models.db import User, CorePlayer, UserIdentity, UserRole
from driftbase.utils import UserCache

log = logging.getLogger(__name__)


def abort_unauthorized(description):
    """Raise an Unauthorized exception.
    """
    abort(http_client.UNAUTHORIZED, description=description)


def authenticate_with_provider(auth_info):
    """
    Supported schemas:
    provider: "uuid", provider_details: { key, secret } -> key
    provider: "device_id", provider_details: { uuid:username, password } -> uuid:username
    provider: "user+pass", provider_details: { username, password } -> username
    provider: "viveport", provider_details: { username, password } -> viveport:username
    provider: "hypereal", provider_details: { username, password } -> hypereal:username
    provider: "7663", provider_details: { username, password } -> 7663:username
    """
    provider = auth_info.get('provider')
    provider_details = auth_info.get('provider_details')
    automatic_account_creation = auth_info.get("automatic_account_creation", True)
    identity = None
    if provider_details is None:
        abort(http.client.BAD_REQUEST, "Bad Request. Missing expected argument.")

    if provider == 'uuid':
        try:
            identity = authenticate('uuid:' + provider_details['key'],
                                    provider_details['secret'],
                                    automatic_account_creation)
        except KeyError:
            abort(http.client.BAD_REQUEST, "Bad Request. Missing expected argument.")

    elif provider == 'device_id':
        try:
            key = provider_details['key']
            if not key.startswith('uuid:'):
                key = 'uuid:' + key
            identity = authenticate(key,
                                    provider_details['secret'],
                                    automatic_account_creation)
        except KeyError:
            abort(http.client.BAD_REQUEST, "Bad Request. Missing expected argument.")

    elif provider in ['user+pass']:
        try:
            identity = authenticate(provider_details['username'],
                                    provider_details['password'],
                                    automatic_account_creation)
        except KeyError:
            abort(http.client.BAD_REQUEST, "Bad Request. Missing expected argument.")

    elif provider == "viveport" and provider_details.get('provisional', False):
        if len(provider_details['username']) < 1:
            abort_unauthorized("Bad Request. 'username' cannot be an empty string.")
        username = "viveport:" + provider_details['username']
        password = provider_details['password']
        identity = authenticate(username, password, True or automatic_account_creation)

    elif provider == "hypereal" and provider_details.get('provisional', False):
        if len(provider_details['username']) < 1:
            abort_unauthorized("Bad Request. 'username' cannot be an empty string.")
        username = "hypereal:" + provider_details['username']
        password = provider_details['password']
        identity = authenticate(username, password, True or automatic_account_creation)

    elif provider == "7663":
        username = "7663:" + provider_details['username']
        password = provider_details['password']
        identity = authenticate(username, password, True or automatic_account_creation)

    else:
        abort_unauthorized(f"Bad Request. Unknown provider '{provider}'.")

    return identity


def authenticate(username, password, automatic_account_creation=True, fallback_username=None):
    """basic authentication"""
    identity_type = ""
    create_roles = set()
    lst = username.split(":")
    # old backwards compatible (non-identity)
    is_old = True
    if len(lst) > 1:
        identity_type = lst[0]
        is_old = False
    else:
        log.info(f"Old-style authentication for '{username}'")

    identity_id = 0

    my_identity = (
        g.db.query(UserIdentity)
            .filter(UserIdentity.name == username)
            .first()
    )

    if not my_identity and fallback_username:
        my_identity = (
            g.db.query(UserIdentity)
                .filter(UserIdentity.name == fallback_username)
                .first()
        )

    try:
        service_user = g.conf.tier.get('service_user')
        if not service_user and g.conf.tenant:
            service_user = g.conf.tenant.get('service_user')
    except Exception:
        log.exception("Getting service user was difficult")
        service_user = current_app.config.get("service_user")

    if not service_user:
        raise RuntimeError("service_user not found in config!")

    # if we do not have an identity, create one along with a user and a player
    if my_identity is None:
        # if this is a service user make sure the password
        # matches before creating the user
        if username == service_user["username"]:
            if password != service_user["password"]:
                log.error("Attempting to log in as service user without correct password!")
                abort(http_client.METHOD_NOT_ALLOWED,
                      message="Incorrect password for service user")
            else:
                create_roles.add("service")
        else:
            create_roles.add("player")

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
        log.info(f"User Identity '{username}' has been created with id {my_identity.identity_id}")
    else:
        if not my_identity.check_password(password):
            abort(http_client.METHOD_NOT_ALLOWED, message="Incorrect password")

    if my_identity:
        identity_id = my_identity.identity_id
        # upgrade the identity name if it's the fallback version
        if fallback_username and my_identity.name != username:
            my_identity.name = username
            g.db.flush()
            log.info(f"User Identity '{username}' has been upgraded from the legacy username format '{fallback_username}'")

    my_user = None
    my_player = None
    my_user_name = ""
    user_id = 0
    user_roles = []
    player_id = 0
    player_uuid = None
    player_name = ""
    if my_identity.user_id:
        my_user = g.db.query(User).get(my_identity.user_id)
        if my_user.status != "active":
            log.info(f"Logon identity is using an inactive user {my_user.user_id}, creating new one")
            my_user = None
        else:
            user_id = my_user.user_id

    if my_user is None:
        if not automatic_account_creation:
            log.info(
                f"User Identity '{my_identity.identity_id}' has no user"
                " but automatic_account_creation is false so user gets no user account")
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
            log.info(f"User '{username}' has been created with user_id {user_id}")

    if my_user:
        user_roles = [r.role for r in my_user.roles]
        if username != service_user["username"] and "player" not in user_roles:
            # Lazily add player role to existing users
            log.info(f"User {user_id} has no 'player' role, adding it")
            role = UserRole(user_id=user_id, role="player")
            g.db.add(role)
            user_roles.append("player")
        user_id = my_user.user_id

        if fallback_username and my_user.user_name == fallback_username:
            my_user.user_name = username
            g.db.flush()
            log.info(f"User '{username}' has been upgraded from the legacy username format '{fallback_username}'")

        my_user_name = my_user.user_name

        my_player = g.db.query(CorePlayer) \
            .filter(CorePlayer.user_id == user_id) \
            .first()

        if my_player is None:
            my_player = CorePlayer(user_id=user_id, player_name=u"")
            g.db.add(my_player)
            # this is so we can access the auto-increment key value
            g.db.flush()
            log.info(f"Player for user {my_user.user_id} has been created with player_id {my_player.player_id}"
                     f" and uuid {my_player.player_uuid}")

    if my_player:
        if my_player.player_uuid is None:
            # Add an uuid for existing players
            my_player.player_uuid = uuid.uuid4()
        player_id = my_player.player_id
        player_uuid = my_player.player_uuid
        player_name = my_player.player_name

    if my_user and not my_user.default_player_id:
        my_user.default_player_id = my_player.player_id

    g.db.commit()

    provider_id = user_id  # by default
    if identity_type and identity_type != 'user+pass':
        provider_id = lst[-1]

    # store the user information in the cache for later lookup
    ret = dict(
        user_name=my_user_name,
        user_id=user_id,
        identity_id=identity_id,
        provider_user_id=provider_id,
        player_id=player_id,
        player_name=player_name,
        player_uuid=player_uuid.hex if player_uuid else None,
        roles=user_roles
    )
    cache = UserCache()
    cache.set_all(user_id, ret)
    return ret


class AuthenticationException(Exception):
    def __init__(self, user_message):
        super().__init__(user_message)
        self.msg = user_message


class ServiceUnavailableException(AuthenticationException):
    """Suitable when dependent services or configuration cannot be reached"""
    pass


class InvalidRequestException(AuthenticationException):
    """Something about the request is malformed or incorrect"""
    pass


class UnauthorizedException(AuthenticationException):
    """Request was syntactically correct but did not resolve in a valid authentication"""
    pass
