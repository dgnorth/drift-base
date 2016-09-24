<%!
import re

%>"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""

# revision identifiers, used by Alembic.
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

def upgrade(engine_name):
    print "Upgrading {}".format(engine_name)
    # your upgrade script goes here
    # see http://alembic.readthedocs.org/en/latest/tutorial.html for examples

def downgrade(engine_name):
    print "Downgrading {}".format(engine_name)
    # your downgrade script goes here
