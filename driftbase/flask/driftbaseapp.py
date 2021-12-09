"""
Flask app with gevent monkey patching.
"""
# Always patch_all first
from gevent import monkey
monkey.patch_all()

# Additionally patch psycopg
from psycogreen.gevent import patch_psycopg
patch_psycopg()

import os

# Optionally enable Metrics
if os.environ.get('ENABLE_DATADOG_METRICS', '0') == '1':
    from ddtrace.runtime import RuntimeMetrics
    RuntimeMetrics.enable()

# Optionally enable APM
if os.environ.get('ENABLE_DATADOG_APM', '0') == '1':
    import ddtrace
    ddtrace.patch_all(logging=True)

from drift.flaskfactory import drift_app
app = drift_app()
