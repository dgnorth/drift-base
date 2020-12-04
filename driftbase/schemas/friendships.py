from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from flask_marshmallow.fields import AbsoluteUrlFor
from driftbase.models.db import FriendInvite


class InviteSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = FriendInvite
        load_instance = True
        include_fk = True
        ordered = True
        exclude = ("deleted", )
    issued_by_player_id = AbsoluteUrlFor("players.entry", player_id='<issued_by_player_id>')
    issued_to = AbsoluteUrlFor("players.entry", player_id='<issued_to>')

class FriendRequestSchema(InviteSchema):
    accept_url = AbsoluteUrlFor("friendships.list", player_id='<issued_to>')

