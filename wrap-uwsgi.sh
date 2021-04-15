#!/bin/bash

# Use this as the entrypoint in docker and docker-compose.

function tearDown() {
  # Kubernetes will stop routing requests to a container that's shutting
  # down, but that doesn't mean there's not one in flight between the router
  # and the app, so we give that a second to arrive.
  sleep 1
  # If the pid-file is still around, then we're probably not running in
  # Kubernetes, and we need to perform a graceful shutdown here.
  # With Kubernetes, the commands below should be run in the preStop script instead.
  if [[ -f /tmp/uwsgi.pid ]]; then
    # Gracefully shut down uWSGI
    echo q >/tmp/uwsgi-fifo
    # Wait for uWSGI to exit for up to 30 seconds
    # shellcheck disable=SC2046
    timeout 30 tail -f /dev/null --pid=$(cat /tmp/uwsgi.pid)
  fi
  exit 0
}

# When run as PID 1 (init) bash doesn't react to signals unless we explicitly trap them.
trap tearDown SIGTERM SIGINT

# Launch uWSGI in the background, and wait for it to finish
# If we just wait for uWSGI in the foreground, the trap above won't work
/home/uwsgi/.local/bin/uwsgi --ini /app/config/uwsgi.ini &
wait $!

# When running in Kubernetes, we sleep a bit before exiting so the preStop
# hook has a chance to exit cleanly.
sleep 2
