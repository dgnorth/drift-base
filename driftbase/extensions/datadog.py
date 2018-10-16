
from flask_datadog import API, StatsD


def register_extension(app):
    print('Registering datadog')
    app.config['STATSD_HOST'] = 'localhost'
    app.config['DATADOG_API_KEY'] = '752f68dc06809442338acbfea43638c7'
    app.config['DATADOG_APP_KEY'] = 'f42fb9fed4b9dd98ba3c53271c30ed03b44a6d49'
    statsd = StatsD(app)
    dogapi = API(app)
