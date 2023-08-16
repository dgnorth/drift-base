wsgi_app = 'driftbase.flask.driftbaseapp:app'

# log to stdout
accesslog = '-'

daemon=False
pidfile = '/tmp/gunicorn.pid'

bind='0.0.0.0:8080'
forwarded_allow_ips = '*'
proxy_protocol=True
proxy_allow_ips = '*'

# using two workers reduces the risk of a single long-running request blocking heartbeats
workers=2
# being mostly IO bound, gevent should work well for us
worker_class='gevent'
worker_connections=100

graceful_timeout=30
keep_alive=2
timeout=30

# access_log_format = '{\n\t"method (m)": "%(m)s",\n\t"path (U)": "%(U)s",\n\t"protocol (H)": "%(H)s",\n\t"request (r)": "%(r)s",\n\t"remote_address (h)": "%(h)s",\n\t"timestamp (t)": "%(t)s",\n\t"status_code (s)": "%(s)s",\n\t"response_size (B)": "%(B)i",\n\t"response_time_ms (M)": "%(M)i",\n\t"user_agent (a)": "%(a)s",\n\t"referer (f)": "%(f)s"\n}'

# useful settings overrides
# --loglevel INFO --dogstatsd-tags tag,tag,tag --backlog 2048 --workers 1 --worker-connections 1000 --keep-alive 2 --graceful-timeout 30 --timeout 30
