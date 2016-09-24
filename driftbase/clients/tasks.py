# -*- coding: utf-8 -*-

import datetime
from celery.utils.log import get_task_logger

from drift.utils import get_tier_name
from drift.flaskfactory import load_config, TenantNotFoundError
from drift.tenant import get_connection_string
from drift.orm import sqlalchemy_session
from drift.core.extensions.celery import celery

from driftbase.players.counters.endpoints import add_count
from driftbase.db.models import Counter


@celery.task
def update_online_statistics():
    """

    """
    logger = get_task_logger("update_statistics")

    tier_name = get_tier_name()
    config = load_config()
    tenants = config.get("tenants", [])
    logger.info("Updating statistics for %s tenants...", len(tenants))
    num_updated = 0
    for tenant_config in tenants:
        if tenant_config.get("name", "*") == "*":
            continue
        try:
            this_conn_string = get_connection_string(tenant_config, None, tier_name=tier_name)

        except TenantNotFoundError:
            continue

        with sqlalchemy_session(this_conn_string) as session:
            result = session.execute("""SELECT COUNT(DISTINCT(player_id)) AS cnt
                                          FROM ck_clients
                                         WHERE heartbeat > NOW() - INTERVAL '1 minutes'""")
            cnt = result.fetchone()[0]
            if cnt:
                num_updated += 1
                tenant_name = tenant_config["name"]
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
                print "Updated num_online for %s to %s" % (tenant_name, cnt)

    logger.info("Updated %s tenants with online user count", num_updated)
