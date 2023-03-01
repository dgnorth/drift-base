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

import uuid
from alembic import op
from sqlalchemy.dialects.postgresql import UUID
import sqlalchemy as sa


def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    op.add_column('ck_players', sa.Column('player_uuid', UUID(as_uuid=True), default=uuid.uuid4))

def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    op.drop_column('ck_players', 'player_uuid')
