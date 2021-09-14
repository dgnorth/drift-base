#!/bin/bash

docker run --rm -ti --network backend --env-file local.env \
  --entrypoint /bin/bash \
  app_drift-base:latest \
  -c "alembic $(printf "${1+ %q}" "$@")"
