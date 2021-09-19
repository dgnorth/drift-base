"""Migrate counter ids to BigInt

Revision ID: 3b4283dcb935
Revises: 1458e3a7775d
Create Date: 2021-09-19 22:59:57.965743

"""

# revision identifiers, used by Alembic.
revision = '3b4283dcb935'
down_revision = '1458e3a7775d'
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    op.alter_column('ck_playercounters', 'id', type_=sa.BigInteger)
    op.alter_column('ck_counterentries', 'id', type_=sa.BigInteger)


def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    op.alter_column('ck_counterentries', 'id', type_=sa.Integer)
    op.alter_column('ck_playercounters', 'id', type_=sa.Integer)
