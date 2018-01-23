# -*- coding: utf-8 -*-
"""
    Celery tasks for match queues.
"""
import logging
import datetime

from celery.utils.log import get_task_logger
from drift.core.extensions.celery import celery

from driftbase.tasks import tasks
from driftbase.db.models import MatchQueuePlayer, Match
from driftbase.matchqueue import process_match_queue


log = logging.getLogger(__name__)


# for mocking
def utcnow():
    return datetime.datetime.utcnow()


@celery.task
def cleanup_orphaned_matchqueues():
    """
    Find matches who have been reserved by the match queue but not joined
    for 10 minutes and make them available to other players
    """
    logger = get_task_logger("cleanup_orphaned_matchqueues")
    tenants = tasks.get_tenants()
    logger.info("Cleaning up match queues for %s tenants...", len(tenants))
    for tenant in tenants:
        tenant_name = tenant['tenant_name']

        with tasks.get_db_session(tenant) as session:
            sql = """
            SELECT m.* FROM gs_matches m
                INNER JOIN gs_servers s ON s.server_id = m.server_id
            WHERE m.status = 'queue' AND
                  m.status_date::timestamp < now()::timestamp - interval '5 minutes' AND
                  s.heartbeat_date::timestamp >= now()::timestamp - interval '2 minutes'
             ORDER BY m.match_id DESC
            """
            result = session.execute(sql)
            orphaned_matches = set()
            match = result.fetchone()
            while match:
                orphaned_matches.add(match.match_id)
                match = result.fetchone()
            if orphaned_matches:
                log.info("Tenant '%s' has %s orphaned matches", tenant_name, len(orphaned_matches))
            for match_id in orphaned_matches:
                match = session.query(Match).get(match_id)
                match.status = "idle"
                match.status_date = utcnow()
                matchqueueplayers = session.query(MatchQueuePlayer) \
                                           .filter(MatchQueuePlayer.match_id == match_id)
                for p in matchqueueplayers:
                    session.delete(p)
                logger.info("Cleaning up orphaned match '%s' in tenant '%s' and putting it "
                            "back into the pool", match_id, tenant_name)
            session.commit()

            # if we cleaned up any matches we should process the match queue in
            # case there are any players waiting
            if orphaned_matches:
                logger.info("Processing match queue")
                redis = tasks.get_redis(tenant)
                process_match_queue(redis, session)
