"""adding player_uuid

Revision ID: 58c1b2a9640f
Revises: 085d7e9a951c
Create Date: 2023-03-01 14:34:57.266504

"""

# revision identifiers, used by Alembic.
revision = '58c1b2a9640f'
down_revision = '085d7e9a951c'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    # your upgrade script goes here
    # see http://alembic.readthedocs.org/en/latest/tutorial.html for examples

def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    # your downgrade script goes here
