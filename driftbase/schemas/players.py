from flask_marshmallow.fields import AbsoluteURLFor
from marshmallow import pre_dump, fields
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from driftbase.models.db import CorePlayer
from flask import url_for


class PlayerSchema(SQLAlchemyAutoSchema):
    class Meta:
        strict = True
        include_fk = True # required to expose the 'user_id' field
        model = CorePlayer
        exclude = ('player_summary', 'user', 'clients')
        load_instance = True
        include_relationships = True

    is_online = fields.Boolean()

    player_url = AbsoluteURLFor(
        'players.entry',
        player_id='<player_id>',
    )

    gamestates_url = AbsoluteURLFor(
        'player_gamestate.list',
        player_id='<player_id>',
    )
    journal_url = AbsoluteURLFor(
        'player_journal.list',
        player_id='<player_id>',
    )
    user_url = AbsoluteURLFor(
        'users.entry',
        user_id='<user_id>',
    )
    messagequeue_url = fields.Str(
        description="Fully qualified URL of the players' message queue resource"
    )
    messagequeue2_url = fields.Str(
        description="Fully qualified URL of the players' message queue resource"
    )
    messages_url = AbsoluteURLFor(
        'messages.exchange',
        exchange='players',
        exchange_id='<player_id>',
    )
    summary_url = AbsoluteURLFor(
        'player_summary.list',
        player_id='<player_id>',
    )
    countertotals_url = AbsoluteURLFor(
        'player_counters.totals',
        player_id='<player_id>',
    )
    counter_url = AbsoluteURLFor(
        'player_counters.list',
        player_id='<player_id>',
    )
    tickets_url = AbsoluteURLFor(
        'player_tickets.list',
        player_id='<player_id>',
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
