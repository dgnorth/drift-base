wsgi_app = 'driftbase.flask.driftbaseapp:app'

# log to stdout
accesslog = '-'

daemon=False
pidfile = '/tmp/gunicorn.pid'

bind='0.0.0.0:8080'
forwarded_allow_ips = '*'
proxy_protocol=True
proxy_allow_ips = '*'

workers=1
worker_class='gevent'
worker_connections=1000

graceful_timeout=30
keep_alive=2
timeout=30

access_log_format = '{"remote_address": "%(h)s", "@timestamp": "%(t)s", "method": "%(r)s", "status": "%(s)s"}'

# useful settings overrides
# --loglevel INFO --dogstatsd-tags tag,tag,tag --backlog 2048 --workers 1 --worker-connections 1000 --keep-alive 2 --graceful-timeout 30 --timeout 30
