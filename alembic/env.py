# -*- coding: utf-8 -*-

import os, sys, socket
from os.path import abspath, join
import logging
from logging.config import fileConfig

from click import echo, secho
from alembic import context
from sqlalchemy import pool, create_engine
from drift.core.resources.postgres import format_connection_string
from drift.utils import get_tier_name
from driftconfig.util import get_default_drift_config

def get_ts():
    return get_default_drift_config()


USE_TWOPHASE = False

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
alembic_cfg = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(alembic_cfg.config_file_name)
db_names = alembic_cfg.get_main_option('databases')
conn_string = alembic_cfg.get_section_option(db_names, "sqlalchemy.url")
logger = logging.getLogger('alembic.env')

MASTER_USERNAME = 'postgres'
MASTER_PASSWORD = 'postgres'

# add your model's MetaData objects here
# for 'autogenerate' support.  These must be set
# up to hold just those tables targeting a
# particular database. table.tometadata() may be
# helpful here in case a "copy" of
# a MetaData is needed.
# from myapp import mymodel
# target_metadata = {
#       'engine1':mymodel.metadata1,
#       'engine2':mymodel.metadata2
# }
target_metadata = {}

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def get_engines():
    if conn_string:
        engines = {"dude": {"engine": create_engine(conn_string, echo=False,
                                                    poolclass=pool.NullPool),
                            "url": conn_string
                            }
                   }
        return engines
    engines = {}
    tenants = []
    ts = get_ts()
    tier = get_tier_name()
    tenants_table = ts.get_table('tenants').find({'deployable_name': 'drift-base'}) #!
    pick_tenant = context.get_x_argument(as_dictionary=True).get('tenant')
    if pick_tenant:
        echo('picking tenant %s' % pick_tenant)
    dry_run = context.get_x_argument(as_dictionary=True).get('dry-run')

    for t in tenants_table:
        if not t.get("postgres"):
            continue
        name = t["tenant_name"]
        if not (pick_tenant and name != pick_tenant) and name != "*" and t["tier_name"] == tier:
            tenants.append(t)

    for tenant_config in tenants:
        conn_info = tenant_config["postgres"]
        conn_info["username"] = MASTER_USERNAME
        conn_info["password"] = MASTER_PASSWORD
        this_conn_string = format_connection_string(conn_info)
        echo(this_conn_string)

        if this_conn_string not in [e["url"] for e in engines.values()]:
            engines["{}.{}".format(tenant_config["tier_name"],
                                   tenant_config["tenant_name"])] = rec = {"url": this_conn_string}

    # quick and dirty connectivity test before trying to upgrade all db's
    echo("Checking connectivity...")
    db_servers = set()
    for key, engine in engines.items():
        server = engine["url"].split("/")
        db_servers.add(server[2].split("@")[1].lower())
    err = False
    for db_server in db_servers:
        parts = db_server.split(":")
        db_server, port = parts[0], int(parts[1])
        sys.stdout.write(db_server + "... ")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((db_server, port))
        if result != 0:
            secho("Unable to connect to server '%s' on port %s" % (db_server, port), fg="red")
            err = True
        else:
            secho("OK", fg="green")
    if err:
        raise RuntimeError("Unable to connect to one or more db servers. Bailing out!")

    if dry_run:
        secho("Dry run, exiting without taking further action", fg="yellow")
        return {}

    for key in engines.keys():
        rec = engines[key]
        connection_string = rec["url"]
        logger.info("Connecting '{}'...".format(connection_string))
        rec['engine'] = create_engine(connection_string,
                                      echo=False,
                                      poolclass=pool.NullPool)
        rec['url'] = connection_string
    return engines


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    # for the --sql use case, run migrations for each URL into
    # individual files.

    engines = get_engines()

    for name, rec in engines.items():
        logger.info("Migrating database %s" % name)
        file_ = "%s.sql" % name
        logger.info("Writing output to %s" % file_)
        with open(file_, 'w') as buffer:
            context.configure(url=rec['url'], output_buffer=buffer,
                              target_metadata=target_metadata.get(name),
                              literal_binds=True)
            with context.begin_transaction():
                context.run_migrations(engine_name=name)


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    engines = get_engines()

    # for the direct-to-DB use case, start a transaction on all
    # engines, then run all migrations, then commit all transactions.
    for name, rec in engines.items():
        engine = rec['engine']
        rec['connection'] = conn = engine.connect()

        if USE_TWOPHASE:
            rec['transaction'] = conn.begin_twophase()
        else:
            rec['transaction'] = conn.begin()

    try:
        for name, rec in engines.items():
            logger.info("Migrating database %s" % name)
            context.configure(
                connection=rec['connection'],
                upgrade_token="%s_upgrades" % name,
                downgrade_token="%s_downgrades" % name,
                target_metadata=target_metadata.get(name)
            )
            context.run_migrations(engine_name=name)

        if USE_TWOPHASE:
            for rec in engines.values():
                rec['transaction'].prepare()

        for rec in engines.values():
            rec['transaction'].commit()
    except:
        for rec in engines.values():
            rec['transaction'].rollback()
        raise
    finally:
        for rec in engines.values():
            rec['connection'].close()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
