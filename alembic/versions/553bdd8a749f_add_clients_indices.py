"""add friendships table

Revision ID: 553bdd8a749f
Revises: 553bdd8a749e
Create Date: 2018-04-19 14:24:33.050913

"""

# revision identifiers, used by Alembic.
revision = '553bdd8a749f'
down_revision = '553bdd8a749e'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


utc_now = sa.text("(now() at time zone 'utc')")


def upgrade(engine_name):
    print "Upgrading {}".format(engine_name)
    # your upgrade script goes here
    op.create_index('ix_ck_clients_ip_address', 'ck_clients', ['ip_address'])
    op.create_index('ix_ck_clients_user_id', 'ck_clients', ['user_id'])
    op.create_index('ix_ck_clients_player_id', 'ck_clients', ['player_id'])
    op.create_index('ix_ck_clients_build', 'ck_clients', ['build'])
    op.create_index('ix_ck_clients_identity_id', 'ck_clients', ['identity_id'])


def downgrade(engine_name):
    print "Downgrading {}".format(engine_name)
    op.drop_index('ix_ck_clients_ip_address')
    op.drop_index('ix_ck_clients_user_id')
    op.drop_index('ix_ck_clients_player_id')
    op.drop_index('ix_ck_clients_build')
    op.drop_index('ix_ck_clients_identity_id')
