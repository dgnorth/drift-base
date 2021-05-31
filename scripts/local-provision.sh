#!/bin/bash

DIR="${BASH_SOURCE%/*}"
if [[ ! -d "$DIR" ]]; then DIR="$PWD"; fi

set -a
source $DIR/local.config
set +a

# Perform provisioning of a tenant from the container
# Config store and origin are mapped to the host, so the host config state gets modified as needed
# Cache must be run from the host, as the cache URL doesn't resolve from within the container
# In a live environment the config would get pulled from remote storage, and the cache would resolve properly

docker run --rm -ti --network backend --env-file local.env \
  --mount "type=bind,source=$CONFIG_STORE,target=$CONFIG_STORE" \
  --mount "type=bind,source=$CONFIG_ORIGIN,target=$CONFIG_ORIGIN" \
  --entrypoint /bin/bash \
  dev \
  -c "driftconfig provision-tenant $TENANT $DEPLOYABLE"
driftconfig cache $CONFIG

