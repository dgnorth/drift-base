# -*- coding: utf-8 -*-

import datetime
from celery.utils.log import get_task_logger

from drift.utils import get_tier_name
from drift.flaskfactory import load_config, TenantNotFoundError
from drift.tenant import get_connection_string
from drift.orm import sqlalchemy_session
from drift.core.extensions.celery import celery
from drift.rediscache import RedisCache

from driftbase.players.counters.endpoints import add_count
from driftbase.db.models import Counter, Client

DEFAULT_HEARTBEAT_TIMEOUT = 300


def get_tenants():
    tier_name = get_tier_name()
    config = load_config()
    _tenants = config.get("tenants", [])
    tenants = []
    for t in _tenants:
        t["heartbeat_timeout"] = config.get("heartbeat_timeout", DEFAULT_HEARTBEAT_TIMEOUT)
        if t.get("name", "*") == "*":
            continue
        try:
            this_conn_string = get_connection_string(t, None, tier_name=tier_name)
        except TenantNotFoundError:
            continue
        t["conn_string"] = this_conn_string
        if config.get("redis_server", None):
            t["redis_server"] = config.get("redis_server")
        tenants.append(t)
    return tenants


@celery.task
def update_online_statistics():
    """
    Get the current number of logged in users (heartbeat in the last minute)
    and save it into a counter
    """
    logger = get_task_logger(__name__)

    tenants = get_tenants()

    logger.info("Updating online statistics for %s tenants...", len(tenants))
    num_updated = 0
    for tenant in tenants:
        with sqlalchemy_session(tenant["conn_string"]) as session:
            sql = """SELECT COUNT(DISTINCT(player_id)) AS cnt
                       FROM ck_clients
                      WHERE heartbeat > NOW() at time zone 'utc' - INTERVAL '1 minutes'"""
            try:
                result = session.execute(sql)
            except Exception as e:
                logger.error("Error fetching data from '%s': %s", tenant["conn_string"], e)
                continue
            cnt = result.fetchone()[0]
            if cnt:
                num_updated += 1
                tenant_name = tenant["name"]
                name = 'backend.numonline'
                row = session.query(Counter).filter(Counter.name == name).first()
                if not row:
                    row = Counter(name=name, counter_type="absolute")
                    session.add(row)
                    session.commit()
                counter_id = row.counter_id
                timestamp = datetime.datetime.utcnow()
                add_count(counter_id, 0, timestamp, cnt, is_absolute=True, db_session=session)
                session.commit()
                logger.info("Updated num_online for %s to %s" % (tenant_name, cnt))

    if num_updated > 0:
        logger.info("Updated %s tenants with online user count", num_updated)


@celery.task
def flush_request_statistics():
    logger = get_task_logger(__name__)
    tenants = get_tenants()

    num_updated = 0
    for tenant in tenants:
        tenant_name = tenant["name"]
        cache = RedisCache(tenant=tenant_name, redis_server=tenant['redis_server'])
        key_name = 'stats:numrequests'
        cnt = int(cache.get(key_name) or 0)
        if not cnt:
            continue

        timestamp = datetime.datetime.utcnow()
        cache.incr(key_name, -cnt)

        num_updated += 1

        clients = {}
        match = cache.make_key("stats:numrequestsclient:*")
        for client in cache.conn.scan_iter(match=match):
            num = int(cache.conn.get(client))
            client_id = int(client.split(":")[-1])
            clients[client_id] = num
            cache.conn.incr(client, -num)

        with sqlalchemy_session(tenant["conn_string"]) as session:
            # global num requests counter for tenant
            counter_name = 'backend.numrequests'
            row = session.query(Counter).filter(Counter.name == counter_name).first()
            if not row:
                row = Counter(name=counter_name, counter_type="count")
                session.add(row)
                session.commit()
            counter_id = row.counter_id
            add_count(counter_id, 0, timestamp, cnt, is_absolute=True, db_session=session)
            session.commit()
            logger.info("Tenant %s has flushed %s requests to db", tenant_name, cnt)

            for client_id, num in clients.iteritems():
                client_row = session.query(Client).get(client_id)
                client_row.num_requests += num

                logger.info("Updated num_requests for client %s to %s. "
                            "Total requests number for client is now %s",
                            client_id, num, client_row.num_requests)
            session.commit()

    if num_updated:
        logger.info("Updated %s tenants with request statistics", num_updated)


@celery.task
def flush_counters():
    logger = get_task_logger(__name__)
    tenants = get_tenants()

    logger.info("Flushing counters to DB for %s tenants...", len(tenants))
    for tenant in tenants:
        tenant_name = tenant["name"]
        cache = RedisCache(tenant=tenant_name, redis_server=tenant['redis_server'])

        # key = 'counters:%s:%s:%s:%s:%s' % (name, counter_type, player_id, timestamp, context_id)

        match = cache.make_key("counters:*")
        for counter in cache.conn.scan_iter(match=match):
            num = int(cache.conn.get(counter))
            cache.conn.delete(counter)
            parts = counter.split(":")
            counter_name = parts[2]
            counter_type = parts[3]
            player_id = int(parts[4])
            timestamp = datetime.datetime.strptime(parts[5], "%Y%m%d%H%M%S")

            logger.info("Counter %s %s %s %s %s" %
                        (counter_name, counter_type, player_id, timestamp, num))
            """
            TODO: Turn this on once we refactor the counter endpoint to use redis
            with sqlalchemy_session(tenant["conn_string"]) as session:
                row = session.query(Counter).filter(Counter.name==counter_name).first()
                if not row:
                    row = Counter(name=counter_name, counter_type="count")
                    session.add(row)
                    session.commit()
                counter_id = row.counter_id
                add_count(counter_id, 0, timestamp, num, is_absolute=(counter_name == "absolute"),
                          db_session=session)
            session.commit()
            """


@celery.task
def timeout_clients():
    logger = get_task_logger(__name__)
    tenants = get_tenants()

    for tenant in tenants:
        num_timeout = 0
        heartbeat_timeout = int(tenant["heartbeat_timeout"])
        with sqlalchemy_session(tenant["conn_string"]) as session:
            # find active clients who have exceeded timeout
            try:
                min_heartbeat_timestamp = datetime.datetime.utcnow() - \
                    datetime.timedelta(seconds=heartbeat_timeout)
                clients = session.query(Client) \
                                 .filter(Client.status == "active",
                                         Client.heartbeat < min_heartbeat_timestamp) \
                                 .all()
            except Exception as e:
                logger.error("Error fetching data from '%s': %s", tenant["conn_string"], e)
                continue
            if clients:
                cache = RedisCache(tenant=tenant["name"], redis_server=tenant['redis_server'])
                for client in clients:
                    logger.info("Logging out user %s with client %s who last heartbeat at '%s'",
                                client.user_id, client.client_id, client.heartbeat)
                    client.status = "timeout"

                    # remove the client from redis if needed
                    cache_key = "clients:uid_%s" % client.user_id
                    current_client_id = int(cache.get(cache_key) or 0)
                    if current_client_id == client.client_id:
                        logger.info("Deleting cache key '%s'" % cache_key)
                        cache.delete(cache_key)
                        num_timeout += 1

                session.commit()

        if num_timeout > 0:
            logger.info("Timed out %s clients in %s", num_timeout, tenant["name"])
