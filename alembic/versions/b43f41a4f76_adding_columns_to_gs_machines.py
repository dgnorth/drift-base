"""Adding columns to gs_machines

Revision ID: b43f41a4f76
Revises: 2232bbc0e668
Create Date: 2017-01-25 10:00:15.844153

"""

# revision identifiers, used by Alembic.
revision = 'b43f41a4f76'
down_revision = 'b43f41a4f75'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, INET, JSON
from drift.orm import ModelBase, utc_now, Base

def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    op.add_column('gs_machines', sa.Column('group_name', sa.String(50), nullable=True))

def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    op.drop_column('gs_machines', 'group_name')
