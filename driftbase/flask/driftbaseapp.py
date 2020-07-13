"""
Flask app with gevent monkey patching.
"""
import logging

from gevent import monkey
monkey.patch_all()
from psycogreen.gevent import patch_psycopg
patch_psycopg()

from drift.flaskfactory import drift_app

app = drift_app()
