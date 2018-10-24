## For OSX

```bash
brew install serverless
```

Install plugins:

```bash
sls plugin install --name serverless-python-requirements
sls plugin install --name serverless-wsgi
```


Deploy and view logs:

```bash
sls deploy && sls logs -f app -t
```

## Lambdas with API Gateway

Shittons of stuff:

- API GW:
  - endpoint type: private
  - resource: ANY / on lambda function
  - resource policy: allow any?
  - stage: main (here is the https url)

- VPC needs Endpoint:
  - service name: com.amazonaws.eu-west-1.execute-api
  - subnet: private subnet
  - security group: allow 10.x.x.x

the api can be curled in two ways:
https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-private-apis.html#apigateway-private-api-test-invoke-url

from within the vpc like this:
`https://{restapi-id}.execute-api.{region}.vpce.amazonaws.com/{stage}`

accessing the api outside the vpc through a vpn means using a different name but the host must be set to the original one:
`https://{vpce-id}.execute-api.{region}.vpce.amazonaws.com/{stage} -H'Host:{restapi-id}}.execute-api.{region}.vpce.amazonaws.com'`





"headers": {
        "Accept": "*/*",
        "Content-Length": "0",
        "Host": "bnuxz6zgo4.execute-api.eu-west-1.amazonaws.com",
        "User-Agent": "curl/7.58.0",
        "X-Amzn-Cipher-Suite": "ECDHE-RSA-AES128-GCM-SHA256",
        "X-Amzn-Vpc-Id": "vpc-6458d901",
        "X-Amzn-Vpce-Config": "1",
        "X-Amzn-Vpce-Id": "vpce-05d0829ef39b4d2b8",
        "X-Forwarded-For": "10.50.1.140"
    },



{
    "APPLICATION_ROOT": "/",
    "DISABLE_JWT": "0",
    "ENV": "production",
    "EXPLAIN_TEMPLATE_LOADING": "False",
    "JSONIFY_MIMETYPE": "application/json",
    "JSONIFY_PRETTYPRINT_REGULAR": "True",
    "JSON_AS_ASCII": "True",
    "JSON_SORT_KEYS": "True",
    "MAX_CONTENT_LENGTH": "None",
    "MAX_COOKIE_SIZE": "4093",
    "PERMANENT_SESSION_LIFETIME": "31 days, 0:00:00",
    "PORT": "10080",
    "PREFERRED_URL_SCHEME": "http",
    "PRESERVE_CONTEXT_ON_EXCEPTION": "None",
    "PROPAGATE_EXCEPTIONS": "None",
    "RESTPLUS_MASK_HEADER": "X-Fields",
    "RESTPLUS_MASK_SWAGGER": "True",
    "SECRET_KEY": "None",
    "SEND_FILE_MAX_AGE_DEFAULT": "12:00:00",
    "SERVER_NAME": "None",
    "SESSION_COOKIE_DOMAIN": "None",
    "SESSION_COOKIE_HTTPONLY": "True",
    "SESSION_COOKIE_NAME": "session",
    "SESSION_COOKIE_PATH": "None",
    "SESSION_COOKIE_SAMESITE": "None",
    "SESSION_COOKIE_SECURE": "False",
    "SESSION_REFRESH_EACH_REQUEST": "True",
    "TEMPLATES_AUTO_RELOAD": "None",
    "TESTING": "False",
    "TRAP_BAD_REQUEST_ERRORS": "None",
    "TRAP_HTTP_EXCEPTIONS": "False",
    "USE_X_SENDFILE": "False",
    "app_root": "/var/task",
    "apps": "['driftbase.tasks.tasks', 'driftbase.api.players', 'driftbase.api.users', 'driftbase.api.clients', 'driftbase.api.clientlogs', 'driftbase.api.events', 'driftbase.api.counters', 'driftbase.api.friendships', 'driftbase.api.useridentities', 'driftbase.api.matches', 'driftbase.api.servers', 'driftbase.api.machines', 'driftbase.api.staticdata', 'driftbase.api.runconfigs', 'driftbase.api.machinegroups', 'driftbase.api.matchqueue', 'driftbase.tasks.matchqueue', 'driftbase.api.messages', 'drift.core.apps.schemas', 'drift.core.apps.provision', 'drift.core.apps.healthcheck', 'drift.contrib.apps.servicestatus']",
    "default_timeout": "5",
    "extensions": "['driftbase.clientsession', 'driftbase.analytics']",
    "heartbeat_period": "30",
    "heartbeat_timeout": "300",
    "name": "drift-base",
    "resource_attributes": "{'drift.core.resources.apitarget': {'api': 'drift', 'requires_api_key': True}, 'drift.core.resources.postgres': {'models': ['driftbase.models.db']}}",
    "resources": "['drift.core.resources.driftconfig', 'drift.core.resources.awsdeploy', 'drift.core.resources.postgres', 'drift.core.resources.redis', 'drift.core.resources.apitarget', 'drift.core.resources.jwtsession', 'driftbase.resources.staticdata', 'driftbase.resources.gameserver', 'driftbase.auth']",
    "systest_db": "{'server': 'localhost:5432'}",
    "private_key": "..."
}
