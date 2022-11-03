"""create unique constraint for invite tokens

Revision ID: 085d7e9a951c
Revises: 3b4283dcb935
Create Date: 2021-11-18 12:46:20.643669

"""

# revision identifiers, used by Alembic.
revision = "085d7e9a951c"
down_revision = "3b4283dcb935"
branch_labels = None
depends_on = None

from alembic import op


def upgrade(engine_name):
    print("Upgrading {}".format(engine_name))
    op.create_unique_constraint("uq_ck_friend_invites_token", "ck_friend_invites", ["token"])

def downgrade(engine_name):
    print("Downgrading {}".format(engine_name))
    op.drop_constraint("uq_ck_friend_invites_token", "ck_friend_invites")
