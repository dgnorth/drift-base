#!/usr/bin/env bash

DIR="${BASH_SOURCE%/*}"
if [[ ! -d "$DIR" ]]; then DIR="$PWD"; fi

set -a
source "$DIR/local.config"
set +a

rm -rf $CONFIG_ORIGIN $CONFIG_STORE

export DRIFT_USE_LOCAL_SERVERS=1
export DRIFT_TIER=$TIER
export DRIFT_CONFIG_URL=$CONFIG

driftconfig create --display-name "Local Development" "$CONFIG" "file://$CONFIG_ORIGIN"
dconf tier add $TIER --is-dev

dconf organization add monkeyworks mw -d "Monkey Works"
dconf product add $PRODUCT
driftconfig push -f $CONFIG

driftconfig register

# These inputs are queried in random order
expect <<EOF
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

# set a custom default DB user for the tier
dconf set --location $TIER --raw "{\"resources\": { \"drift.core.resources.postgres\": { \"username\": \"drift_tier_user\", \"password\": \"tier-pw\" }}}"

# TODO: replace this with tooling, driftconfig assign-product $DEPLOYABLE --products $PRODUCT
dconf set --location products.$PRODUCT --raw "{\"deployables\": [\"$DEPLOYABLE\"]}"
driftconfig push -f $CONFIG

driftconfig create-tenant $TENANT $PRODUCT $TIER
# set a custom DB user for the tenant
dconf set --location tenants.$TIER.$DEPLOYABLE.$TENANT --raw "{\"postgres\": { \"username\": \"drift_tenant_user\", \"password\": \"tenant-pw\" }}"

driftconfig provision-tenant $TENANT $DEPLOYABLE

dconf set --location $TIER --raw cache="redis://127.0.0.1:6379?prefix=$CONFIG"

driftconfig push -f $CONFIG
driftconfig cache $CONFIG
