"""
Flask app with gevent monkey patching.
"""
from gevent import monkey
monkey.patch_all()
from psycogreen.gevent import patch_psycopg
patch_psycopg()

import drift.contrib.flask.datadogapp
app = drift.contrib.flask.datadogapp.app
