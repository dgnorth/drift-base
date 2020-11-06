#!/bin/bash

docker run --rm -ti --network backend --env-file dev.env \
  --entrypoint /bin/bash dev -c "alembic $(printf "${1+ %q}" "$@")"
