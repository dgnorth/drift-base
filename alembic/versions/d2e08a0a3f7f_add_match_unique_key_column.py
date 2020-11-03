"""add match unique_key column

Revision ID: d2e08a0a3f7f
Revises: 553bdd8a749f
Create Date: 2020-11-03 17:40:23.083174

"""

# revision identifiers, used by Alembic.
revision = 'd2e08a0a3f7f'
down_revision = '553bdd8a749f'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    op.add_column('gs_matches', sa.Column('unique_key', sa.String(50), nullable=True))

def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    op.drop_column('gs_matches', 'unique_key')
