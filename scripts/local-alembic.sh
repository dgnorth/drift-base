#!/bin/bash

docker run --rm -ti --network backend --env-file local.env \
  --entrypoint /bin/bash \
  dev \
  -c "alembic $(printf "${1+ %q}" "$@")"
