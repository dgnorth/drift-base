"""adding column to match

Revision ID: 2232bbc0e668
Revises:
Create Date: 2016-12-22 11:58:39.412616

"""

# revision identifiers, used by Alembic.
revision = '2232bbc0e668'
down_revision = '56e4cab9b63e'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    op.add_column('gs_matches', sa.Column('total_players', sa.Integer, nullable=True))

def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    op.drop_column('gs_matches', 'total_players')