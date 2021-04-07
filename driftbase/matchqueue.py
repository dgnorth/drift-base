import datetime
import collections

from flask import g

from driftbase.api.servers import SERVER_HEARTBEAT_TIMEOUT_SECONDS
from driftbase.models.db import Match, MatchQueuePlayer, Client, Server, Machine

import logging

log = logging.getLogger(__name__)


def utcnow():
    return datetime.datetime.utcnow()


def lock(redis):
    # Moving this into a separate function so systems test can mock it out.
    return redis.lock("process_match_queue")


def check_ref_and_placement(player, match, server, machine):
    if player.ref and player.ref != server.ref:
        log.debug("player %s wants a match in ref '%s' but match %s is in '%s'" %
                  (player.player_id, player.ref, match.match_id, server.ref))
        return False
    if player.placement and player.placement != machine.placement:
        log.debug("player %s wants a match in placement '%s' but match %s is in '%s'" %
                  (player.player_id, player.placement, match.match_id, machine.placement))
        return False
    return True


def process_match_queue(redis=None, db_session=None):
    log.info("process_match_queue...")
    if redis is None:
        redis = g.redis
    if db_session is None:
        db_session = g.db
    with lock(redis):
        # find all valid players waiting in the queue
        queued_players = db_session.query(MatchQueuePlayer, Client) \
            .filter(Client.client_id == MatchQueuePlayer.client_id,
                    MatchQueuePlayer.status == "waiting",
                    MatchQueuePlayer.match_id == None) \
            .order_by(MatchQueuePlayer.id) \
            .all()  # noqa: E711
        query = db_session.query(Machine, Server, Match)
        query = query.filter(Match.server_id == Server.server_id,
                             Server.machine_id == Machine.machine_id,
                             Match.num_players == 0,
                             Match.status == "idle",
                             Server.server_id == Match.server_id,
                             Server.heartbeat_date >= utcnow() - datetime.timedelta(
                                 seconds=SERVER_HEARTBEAT_TIMEOUT_SECONDS))
        idle_matches = query.all()

        eligible_players = []
        challenge_players = collections.defaultdict(list)
        for r in queued_players:
            player, client = r
            log.debug("Found %s in the queue", r[0].player_id)
            if client.heartbeat < utcnow() - datetime.timedelta(seconds=60):
                log.info("Player %s is in the queue but has missed his heartbeat. "
                         "Removing him from the queue", player.player_id)
                db_session.delete(player)
            elif not player.token:
                eligible_players.append(player)
            else:
                challenge_players[player.token].append(player)
        db_session.commit()

        matched_players = set()
        for machine, server, match in idle_matches:
            possibly_matched_players = []
            # start by processing player challenges
            for token, players in list(challenge_players.items()):
                if len(players) < match.max_players:
                    continue

                # if either player specifies a ref or placement, use that for picking match
                check_player = players[0]
                if players[1].ref or players[1].placement:
                    check_player = players[1]
                if not check_ref_and_placement(check_player, match, server, machine):
                    continue

                possibly_matched_players.extend(players)
                del challenge_players[token]

            if len(possibly_matched_players) == 0:
                for p in eligible_players:
                    if p.player_id in matched_players:
                        continue

                    if not check_ref_and_placement(p, match, server, machine):
                        continue

                    possibly_matched_players.append(p)

                    log.debug("Possibly adding player %s to match %s",
                              player.player_id, match.match_id)
                    if len(possibly_matched_players) == match.max_players:
                        break

            # if we found enough players to populate this match, mark them as matched and add them
            # to the match. Also set the match to the 'queue' status.
            if len(possibly_matched_players) >= match.max_players:
                for p in possibly_matched_players:
                    matched_players.add(p.player_id)
                    p.match_id = match.match_id
                    p.status = "matched"
                    log.info("Adding player %s to match %s", p.player_id, match.match_id)

                match.status = "queue"
                match.status_date = utcnow()
                db_session.commit()
            elif len(possibly_matched_players) > 0:
                log.info("Only found %s players for match %s which needs %s players "
                         "so I cannot populate it",
                         len(possibly_matched_players), match.match_id, match.max_players)
