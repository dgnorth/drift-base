from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from flask_marshmallow.fields import AbsoluteUrlFor
from driftbase.models.db import FriendInvite
from marshmallow import pre_dump, fields, post_dump


class InviteSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = FriendInvite
        load_instance = True
        include_fk = True
        ordered = True
        exclude = ("deleted", )
    issued_by_player_url = AbsoluteUrlFor("players.entry", player_id='<issued_by_player_id>')
    issued_by_player_name = fields.String()
    issued_to_player_url = AbsoluteUrlFor("players.entry", player_id='<issued_to_player_id>')
    issued_to_player_name = fields.String()

    @pre_dump
    def _populate_names(self, obj, many, **kwargs):
        obj, issued_to_player_name, issued_by_player_name = obj
        obj.issued_to_player_name = issued_to_player_name
        obj.issued_by_player_name = issued_by_player_name
        return obj


class FriendRequestSchema(InviteSchema):
    accept_url = AbsoluteUrlFor("friendships.list", player_id='<issued_to_player_id>')

