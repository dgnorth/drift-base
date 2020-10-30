"""add friendships table

Revision ID: 6f74c797dbd0
Revises: b43f41a4f76
Create Date: 2017-10-16 14:24:33.050913

"""

# revision identifiers, used by Alembic.
revision = '6f74c797dbd0'
down_revision = 'b43f41a4f76'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
import datetime


utc_now = sa.text("(now() at time zone 'utc')")


def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    # your upgrade script goes here
    op.execute(sa.schema.CreateSequence(sa.Sequence('ck_friendships_id_seq')))
    op.create_table(
        'ck_friendships',
        sa.Column('id', sa.BigInteger, sa.Sequence('ck_friendships_id_seq'), primary_key=True, server_default=sa.text("nextval('ck_friendships_id_seq'::regclass)")),
        sa.Column('player1_id', sa.Integer, sa.ForeignKey('ck_players.player_id'), nullable=False, index=True),
        sa.Column('player2_id', sa.Integer, sa.ForeignKey('ck_players.player_id'), nullable=False, index=True),
        sa.Column('create_date', sa.DateTime, nullable=False, server_default=utc_now),
        sa.Column('modify_date', sa.DateTime, nullable=False, server_default=utc_now, onupdate=datetime.datetime.utcnow),
        sa.Column('status', sa.String(20), nullable=False, server_default="active"),
        sa.CheckConstraint('player1_id < player2_id'),
    )
    sql = "GRANT INSERT, SELECT, UPDATE, DELETE ON TABLE ck_friendships to zzp_user;"
    op.execute(sql)
    sql = "GRANT ALL ON SEQUENCE ck_friendships_id_seq TO zzp_user;"
    op.execute(sql)


def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    # your downgrade script goes here
    op.drop_table('ck_friendships')
    op.execute(sa.schema.DropSequence(sa.Sequence('ck_friendships_id_seq')))
