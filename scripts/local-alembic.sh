#!/bin/bash

DIR="${BASH_SOURCE%/*}"
if [[ ! -d "$DIR" ]]; then DIR="$PWD"; fi

set -a
source $DIR/local.config
set +a

docker run --rm -ti --network backend --env-file $DIR/local.env \
  --entrypoint /bin/bash \
  app_drift-base:latest \
  -c "alembic $(printf "${1+ %q}" "$@")"
