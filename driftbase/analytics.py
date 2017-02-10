import logging

from flask import g

from drift.auth.jwtchecker import query_current_user


log = logging.getLogger(__name__)


def _update_analytics():
    client_id = None
    current_user = query_current_user()
    if current_user:
        user_id = current_user["user_id"]
        client_id = current_user.get("client_id")
        if not client_id:
            log.debug("client_id not found in JWT for user %s. Not updating client stats." % user_id)

    if hasattr(g, 'redis') and g.redis and g.redis.conn:
        # use redis pipeline to minimize roundtrips
        pipe = g.redis.conn.pipeline()
        k = g.redis.make_key('stats:numrequests')
        pipe.incr(k)
        pipe.expire(k, 3600)
        if client_id:
            k = g.redis.make_key('stats:numrequestsclient:{}'.format(client_id))
            pipe.incr(k)
            pipe.expire(k, 3600)
        pipe.execute()


def after_request(response):
    _update_analytics()
    return response


def register_extension(app):
    app.after_request(after_request)
