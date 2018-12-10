import logging

from flask import current_app

from drift.core.extensions.jwt import query_current_user


log = logging.getLogger(__name__)


def _update_analytics():
    client_id = None
    current_user = query_current_user()
    if current_user:
        user_id = current_user["user_id"]
        client_id = current_user.get("client_id")
        if not client_id:
            log.debug("client_id not found in JWT for user %s. Not updating client stats." % user_id)

    # As we are doing this 'after request' we should only acquire the redis session if it's
    # already available. A "hard" reference on g.redis could have side effects in this
    # context.
    redis = current_app.extensions['redis'].get_session_if_available()
    if redis:
        # use redis pipeline to minimize roundtrips
        pipe = redis.conn.pipeline()
        k = redis.make_key('stats:numrequests')
        pipe.incr(k)
        pipe.expire(k, 3600)
        if client_id:
            k = redis.make_key('stats:numrequestsclient:{}'.format(client_id))
            pipe.incr(k)
            pipe.expire(k, 3600)
        pipe.execute()


def after_request(response):
    _update_analytics()
    return response


def register_extension(app):
    app.after_request(after_request)
