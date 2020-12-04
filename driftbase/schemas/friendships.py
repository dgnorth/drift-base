from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from flask_marshmallow.fields import UrlFor
from driftbase.models.db import FriendInvite


class InviteSchema(SQLAlchemyAutoSchema):
    class Meta:
        model = FriendInvite
        load_instance = True
        include_fk = True
        ordered = True
        exclude = ("deleted", )
    issued_by_player_id = UrlFor("players.entry", player_id='<issued_by_player_id>')
    issued_to = UrlFor("players.entry", player_id='<issued_to>')

class FriendRequestSchema(InviteSchema):
    accept_url = UrlFor("friendships.list", player_id='<issued_to>')

