import logging
import httplib

from flask import g
from flask_restful import abort

from drift.auth.jwtchecker import query_current_user

from driftbase.db.models import Client

log = logging.getLogger(__name__)


def before_request():
    current_user = query_current_user()
    if not current_user:
        return

    # we do not log off service users
    if "service" in current_user["roles"]:
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
        log.warn("Denying access for user %s on client %s. client status = '%s'", user_id, client_id, client_status)
        abort(httplib.FORBIDDEN,
              code="client_session_terminated",
              description="Your client, %s is no longer registered here. Status is '%s'" % (client_id, client_status),
              reason=client_status,
              )


def register_extension(app):
    app.before_request(before_request)
