from raven.contrib.flask import Sentry
import raven


def register_extension(app):
    print('Registering sentry')
    client = raven.Client(include_paths=[app.config['name'], 'drift', 'flask', 'driftbase'],
                          release='0.1.0',
                          tags=[])
    print("DSN %s" % app.config.get("SENTRY_DSN"))
    Sentry(app, client=client)
