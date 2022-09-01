import logging
import http.client as http_client

from flask import g, current_app
from drift.blueprint import abort

from drift.core.extensions.jwt import query_current_user

from driftbase.models.db import Client

log = logging.getLogger(__name__)


def before_request():
    current_user = query_current_user()
    if not current_user:
        return

    # we do not log off service users
    if current_user.get("is_service"):
        return
    if current_user["roles"] == "service":  # Legacy service user
        return

    if not current_user.get("client_id"):
        log.debug("User has no client_id. Let's skip this check")
        return

    client_id = current_user["client_id"]
    user_id = current_user["user_id"]

    cache_key = "clients:uid_%s" % user_id
    current_client_id = int(g.redis.get(cache_key) or 0)
    if current_client_id != client_id:
        # we are no longer logged in
        client_status = g.db.query(Client).get(client_id).status
        log.warning("Denying access for user %s on client %s. client status = '%s'", user_id, client_id, client_status)
        abort(http_client.FORBIDDEN,
              error_code="client_session_terminated",
              description="Your client, %s is no longer registered here. Status is '%s'" % (client_id, client_status),
              reason=client_status,
              )


def register_extension(app):
    app.before_request(before_request)
