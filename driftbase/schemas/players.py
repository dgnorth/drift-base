from marshmallow import pre_dump, fields
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from sqlalchemy.sql import func
from driftbase.models.db import CorePlayer, MatchPlayer
from drift.utils import Url
from flask import url_for, g


class PlayerSchema(SQLAlchemyAutoSchema):
    class Meta:
        strict = True
        include_fk = True # required to expose the 'user_id' field
        model = CorePlayer
        exclude = ('player_summary', 'user', 'clients')
        load_instance = True
        include_relationships = True

    is_online = fields.Boolean()

    player_url = Url(
        'players.entry',
        doc="Fully qualified URL of the player resource",
        player_id='<player_id>',
    )

    gamestates_url = Url(
        'player_gamestate.list',
        doc="Fully qualified URL of the players' gamestate resource",
        player_id='<player_id>',
    )
    journal_url = Url(
        'player_journal.list',
        doc="Fully qualified URL of the players' journal resource",
        player_id='<player_id>',
    )
    user_url = Url(
        'users.entry',
        doc="Fully qualified URL of the players' user resource",
        user_id='<user_id>',
    )
    messagequeue_url = fields.Str(
        description="Fully qualified URL of the players' message queue resource"
    )
    messagequeue2_url = fields.Str(
        description="Fully qualified URL of the players' message queue resource"
    )
    messages_url = Url(
        'messages.exchange',
        doc="Fully qualified URL of the players' messages resource",
        exchange='players',
        exchange_id='<player_id>',
    )
    summary_url = Url(
        'player_summary.list',
        doc="Fully qualified URL of the players' summary resource",
        player_id='<player_id>',
    )
    countertotals_url = Url(
        'player_counters.totals',
        doc="Fully qualified URL of the players' counter totals resource",
        player_id='<player_id>',
    )
    counter_url = Url(
        'player_counters.list',
        doc="Fully qualified URL of the players' counter resource",
        player_id='<player_id>',
    )
    tickets_url = Url(
        'player_tickets.list',
        doc="Fully qualified URL of the players' tickets resource",
        player_id='<player_id>',
    )

    total_match_time_seconds = fields.Integer(
        description="Generated field. The total match time of the player in seconds",
    )

    @pre_dump
    def populate_urls(self, obj, many=False):
        obj.messagequeue_url = (
            url_for(
                'messages.exchange',
                exchange='players',
                exchange_id=obj.player_id,
                _external=True,
            )
            + '/{queue}'
        )
        return obj

    @pre_dump
    def populate_total_match_time(self, obj, many=False):
        match_time_query = g.db.query(func.sum(MatchPlayer.leave_date - MatchPlayer.join_date)).filter(MatchPlayer.player_id == obj.player_id)

        time_delta = match_time_query.scalar()

        seconds = 0
        if time_delta:
            seconds = time_delta.total_seconds()

        obj.total_match_time_seconds = seconds

        return obj
