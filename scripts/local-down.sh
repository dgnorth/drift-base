#!/bin/bash

docker-compose -p app -f compose-app.yml down
docker-compose -p backend -f compose-backend.yml down
