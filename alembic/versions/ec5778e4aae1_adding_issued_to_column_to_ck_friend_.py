"""adding 'issued_to_player_id' column to ck_friend_invites

Revision ID: ec5778e4aae1
Revises: d2e08a0a3f7f
Create Date: 2020-12-01 12:36:31.819747

"""

# revision identifiers, used by Alembic.
revision = 'ec5778e4aae1'
down_revision = 'd2e08a0a3f7f'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    op.add_column('ck_friend_invites', sa.Column('issued_to_player_id', sa.Integer, sa.ForeignKey('ck_players.player_id'), nullable=True, index=True))

def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    op.drop_column('ck_friend_invites', 'issued_to_player_id')
