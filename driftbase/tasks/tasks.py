import datetime
from celery.utils.log import get_task_logger
from flask import current_app, g
from drift.orm import sqlalchemy_session
from drift.core.extensions.celery import celery
from drift.core.resources.redis import RedisCache
from drift.core.resources.postgres import format_connection_string
from driftbase.api.players.counters import add_count
from driftbase.models.db import Counter, Client


DEFAULT_HEARTBEAT_TIMEOUT = 300


def drift_init_extension(app, api, **kwds):
    pass


def get_redis(tenant):
    cache = RedisCache(
        tenant=tenant['tenant_name'],
        service_name=current_app.config['name'],
        redis_config=tenant['redis']
    )
    return cache


def get_db_session(tenant):
    conn_string = format_connection_string(tenant['postgres'])
    return sqlalchemy_session(conn_string)


def get_tenants():
    """Return tenant configs for the current tier."""
    return g.conf.tenants


@celery.task
def update_online_statistics():
    """
    Get the current number of logged in users (heartbeat in the last minute)
    and save it into a counter
    """
    logger = get_task_logger(__name__)
    logger.info("Updating online statistics")
    tenants = g.conf.tenants
    logger.info("Updating online statistics for %s tenants...", len(tenants))

    try:
        num_updated = 0
        for tenant in g.conf.tenants:
            with get_db_session(tenant) as session:
                sql = """SELECT COUNT(DISTINCT(player_id)) AS cnt
                           FROM ck_clients
                          WHERE heartbeat > NOW() at time zone 'utc' - INTERVAL '1 minutes'"""
                try:
                    result = session.execute(sql)
                except Exception as e:
                    logger.error("Error fetching data from '%s': %s", format_connection_string(tenant["postgres"]), e)
                    continue
                cnt = result.fetchone()[0]
                if cnt:
                    num_updated += 1
                    tenant_name = tenant['tenant_name']
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

        if num_updated > 0 or 1:
            logger.info("Updated %s tenants with online user count", num_updated)
    except Exception as e:
        logger.exception(e)


@celery.task
def flush_request_statistics():
    try:
        logger = get_task_logger(__name__)
        tenants = get_tenants()

        num_updated = 0
        for tenant in tenants:
            tenant_name = tenant['tenant_name']

            cache = get_redis(tenant)
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

            with get_db_session(tenant) as session:
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

                for client_id, num in clients.items():
                    client_row = session.query(Client).get(client_id)
                    if not client_row:
                        logger.warning("Found no client row for client_id %s", client_id)
                        continue
                    client_row.num_requests += num

                    logger.info("Updated num_requests for client %s to %s. "
                                "Total requests number for client is now %s",
                                client_id, num, client_row.num_requests)
                session.commit()

        if num_updated:
            logger.info("Updated %s tenants with request statistics", num_updated)
    except Exception as e:
        logger.exception(e)


@celery.task
def flush_counters():
    try:
        logger = get_task_logger(__name__)
        tenants = get_tenants()

        logger.info("Flushing counters to DB for %s tenants...", len(tenants))
        for tenant in tenants:
            cache = get_redis(tenant)

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
                with get_db_session(tenant) as session:
                    row = session.query(Counter).filter(Counter.name == counter_name).first()
                    if not row:
                        row = Counter(name=counter_name, counter_type="count")
                        session.add(row)
                        session.commit()
                    counter_id = row.counter_id
                    add_count(counter_id, 0, timestamp, num, is_absolute=(counter_name == "absolute"),
                              db_session=session)
                session.commit()
    except Exception as e:
        logger.exception(e)


@celery.task
def timeout_clients():
    try:
        logger = get_task_logger(__name__)
        tenants = get_tenants()

        for tenant in tenants:
            num_timeout = 0
            heartbeat_timeout = current_app.config["heartbeat_timeout"]
            with get_db_session(tenant) as session:
                # find active clients who have exceeded timeout
                try:
                    min_heartbeat_timestamp = datetime.datetime.utcnow() - \
                        datetime.timedelta(seconds=heartbeat_timeout)
                    clients = session.query(Client) \
                                     .filter(Client.status == "active",
                                             Client.heartbeat < min_heartbeat_timestamp) \
                                     .all()
                except Exception as e:
                    logger.error("Error fetching data from '%s': %s", format_connection_string(tenant["postgres"]), e)
                    continue
                if clients:
                    cache = get_redis(tenant)
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
                logger.info("Timed out %s clients in %s", num_timeout, tenant['tenant_name'])
    except Exception as e:
        logger.exception(e)
