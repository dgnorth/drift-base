#!/bin/bash

set -a
source local.config
set +a

rm -rf $CONFIG_ORIGIN $CONFIG_STORE

export DRIFT_USE_LOCAL_SERVERS=1
export DRIFT_TIER=$TIER
export DRIFT_CONFIG_URL=$CONFIG

driftconfig create --display-name "Local Development" "$CONFIG" "file://$CONFIG_ORIGIN"
dconf tier add $TIER --is-dev

dconf organization add monkeyworks mw -d "Monkey Works"
dconf product add $PRODUCT
driftconfig push -f $CONFIG >/dev/null

driftconfig register >/dev/null

# These inputs are queried in random order
expect >/dev/null <<EOF
spawn driftconfig assign-tier $DEPLOYABLE --tiers $TIER
expect {
"* drift.core.resources.postgres.server:" { send -- "postgres\r" ; exp_continue }
"* drift.core.resources.redis.host:" { send -- "redis\r" ; exp_continue }
"* drift.core.resources.awsdeploy.region:" { send -- "eu-west-1\r" ; exp_continue }
"* drift.core.resources.awsdeploy.ssh_key:" { send -- "my-ssh-key\r" ; exp_continue }
"* drift.core.resources.sentry.dsn:" { send -- "\r" ; exp_continue }
"* driftbase.resources.staticdata.repository:" { send -- "git@github.com:foo/bar\r" ; exp_continue }
"* driftbase.resources.staticdata.revision:" { send -- "\r" ; exp_continue }
"* driftbase.resources.gameserver.build_bucket_url:" { send -- "s3://builds-bucket\r" ; exp_continue }
}
EOF

dconf set --location $TIER --raw "{\"resources\": { \"drift.core.resources.postgres\": { \"username\": \"postgres\", \"password\": \"\" }}}"

dconf set --location products.$PRODUCT --raw "{\"deployables\": [\"$DEPLOYABLE\"]}" >/dev/null
#driftconfig assign-product $DEPLOYABLE --products $PRODUCT
driftconfig push -f $CONFIG >/dev/null

driftconfig create-tenant $TENANT $PRODUCT $TIER >/dev/null

driftconfig provision-tenant $TENANT $DEPLOYABLE >/dev/null

dconf set --location $TIER --raw cache="redis://127.0.0.1:6379?prefix=$CONFIG" >/dev/null
driftconfig push -f $CONFIG >/dev/null

driftconfig cache $CONFIG
