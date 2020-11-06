#!/bin/bash

set -a
source dev.config
set +a

docker run --rm -ti --network backend --env-file dev.env \
  --mount "type=bind,source=$CONFIG_STORE,target=$CONFIG_STORE" \
  --mount "type=bind,source=$CONFIG_ORIGIN,target=$CONFIG_ORIGIN" \
  --entrypoint bash dev -c "driftconfig provision-tenant $TENANT $DEPLOYABLE"
driftconfig cache $CONFIG
