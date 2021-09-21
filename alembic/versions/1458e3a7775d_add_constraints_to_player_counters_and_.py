"""Add constraints to player counters and counter entries

Revision ID: 1458e3a7775d
Revises: ec5778e4aae1
Create Date: 2021-09-19 14:20:01.627955

"""

# revision identifiers, used by Alembic.
revision = '1458e3a7775d'
down_revision = 'ec5778e4aae1'
branch_labels = None
depends_on = None

from alembic import op


def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    # TODO: Find violations in existing data and fix them
    op.create_unique_constraint('ck_playercounters_counter_id_player_id_key', 'ck_playercounters',
                                ['counter_id', 'player_id'])
    op.create_unique_constraint('ck_counterentries_counter_id_player_id_period_date_time_key', 'ck_counterentries',
                                ['counter_id', 'player_id', 'period', 'date_time'])


def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    op.drop_constraint('ck_counterentries_counter_id_player_id_period_date_time_key', 'ck_counterentries')
    op.drop_constraint('ck_playercounters_counter_id_player_id_key', 'ck_playercounters')
