"""dummy

Revision ID: 56e4cab9b63e
Revises: 
Create Date: 2016-12-22 11:58:39.412616

"""

# revision identifiers, used by Alembic.
revision = '56e4cab9b63e'
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade(engine_name):
    print "Upgrading {}".format(engine_name)
    

def downgrade(engine_name):
    print "Downgrading {}".format(engine_name)