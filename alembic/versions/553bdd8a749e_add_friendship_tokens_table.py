"""add friend invites table

Revision ID: 553bdd8a749e
Revises: 6f74c797dbd0
Create Date: 2017-10-20 10:06:36.730512

"""

# revision identifiers, used by Alembic.
revision = '553bdd8a749e'
down_revision = '6f74c797dbd0'
branch_labels = None
depends_on = None

import datetime
from alembic import op
import sqlalchemy as sa


utc_now = sa.text("(now() at time zone 'utc')")


def upgrade(engine_name):
    print "Upgrading {}".format(engine_name)
    # your upgrade script goes here
    op.execute(sa.schema.CreateSequence(sa.Sequence('ck_friend_invites_id_seq')))
    op.create_table(
        'ck_friend_invites',
        sa.Column('id', sa.BigInteger, sa.Sequence('ck_friend_invites_id_seq'), primary_key=True, server_default=sa.text("nextval('ck_friend_invites_id_seq'::regclass)")),
        sa.Column('issued_by_player_id', sa.Integer, sa.ForeignKey('ck_players.player_id'), nullable=False, index=True),
        sa.Column('token', sa.String(50), nullable=False, index=True),
        sa.Column('expiry_date', sa.DateTime, nullable=False),
        sa.Column('deleted', sa.Boolean, nullable=True, default=False),

        sa.Column('create_date', sa.DateTime, nullable=False, server_default=utc_now),
        sa.Column('modify_date', sa.DateTime, nullable=False, server_default=utc_now, onupdate=datetime.datetime.utcnow),
    )
    sql = "GRANT INSERT, SELECT, UPDATE, DELETE ON TABLE ck_friend_invites to zzp_user;"
    op.execute(sql)
    sql = "GRANT ALL ON SEQUENCE ck_friend_invites_id_seq TO zzp_user;"
    op.execute(sql)


def downgrade(engine_name):
    print "Downgrading {}".format(engine_name)
    # your downgrade script goes here
    op.drop_table('ck_friend_invites')
    op.execute(sa.schema.DropSequence(sa.Sequence('ck_friend_invites_id_seq')))
