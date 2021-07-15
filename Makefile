# Configuration

PACKAGE_NAME = driftbase
IMAGE_NAME = $(REGISTRY)/drift-base

# Overridable defaults

# REF accepts either the full ref refs/heads/branch/name, or just the short name branch/name
REF ?= $(shell git rev-parse --abbrev-ref HEAD)

# BRANCH must always be just the short name
BRANCH ?= $(subst refs/heads/,,$(REF))

# VERSION is the semantic version, and will use the latest version-like tag if one exists
VERSION ?= $(shell git tag --sort=committerdate | grep -E '^v[0-9]' | tail -1)

CI_COMMIT_REF_NAME ?= $(shell git rev-parse --abbrev-ref HEAD)
CI_COMMIT_SHORT_SHA ?= $(shell git rev-parse --short=8 HEAD)

BUILD_TIMESTAMP = $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")

# Docker tags must not contain slashes
BRANCH_TAG = $(subst /,_,$(BRANCH))

# An empty REGISTRY means we're making builds for local consumption
REGISTRY ?=

TAGS = ${BRANCH_TAG} ${VERSION}
# If no registry has been specified, tag the image so that it will work with docker-compose automatically
ifeq ($(strip ${REGISTRY}),)
TAG_ARGS = --tag app_drift-base:latest
else
TAG_ARGS = $(foreach TAG,${TAGS},--tag ${IMAGE_NAME}:${TAG})
endif

# Helper targets

.PHONY: ENV_GUARD

# Ensures that an environment variable has been defined. Depend on env-guard-VAR_NAME to check for VAR_NAME.
env-guard-%: ENV_GUARD
	@if [ -z '${${*}}' ]; then echo 'Environment variable $* not set' && exit 1; fi

# Build targets

.PHONY: build push test

# Expect there to be a file ./.env at this point which we can pass in to docker as a secret,
# holding the credentials required for connecting to private dependency repositories
build:
	docker build \
		${TAG_ARGS} \
		--build-arg VERSION='${VERSION}' \
		--build-arg BUILD_TIMESTAMP='${BUILD_TIMESTAMP}' \
		--build-arg COMMIT_HASH='${CI_COMMIT_SHORT_SHA}' \
		--secret id=pip-credentials,src=.env \
		.

push: env-guard-REGISTRY
	docker push ${IMAGE_NAME}:latest
	docker push ${IMAGE_NAME}:${BRANCH_TAG}
	docker push ${IMAGE_NAME}:${VERSION}

test: run-backend
	pipenv run pytest .

# Convenience targets

.PHONY: local-config run-app run-appd run-backend stop-app stop-backend stop-all

~/.drift/config/local/domain.json: scripts/create-config.sh
	pipenv run ./scripts/create-config.sh

local-config: ~/.drift/config/local/domain.json
	pipenv run driftconfig cache local

# Run app in Flask with logs to stdout, CTRL+C to stop
run-flask: run-backend local-config
	DRIFT_CONFIG_URL=local \
	DRIFT_TIER=LOCAL \
	FLASK_APP=driftbase.flask.driftbaseapp:app \
	FLASK_RUN_PORT=8080 \
	pipenv run flask run

# Run app in Docker with logs to stdout, CTRL+C to stop
run-app: run-backend local-config
	docker-compose -p app -f ./compose-app.yml up

# Run app in Docker in the background, make stop-app to stop
run-appd: run-backend local-config
	docker-compose -p app -f ./compose-app.yml up -d

# Stop app in Docker
stop-app:
	docker-compose -p app -f ./compose-app.yml down

# Run backend support functions in Docker
run-backend:
	docker-compose -p backend -f ./compose-backend.yml up -d

# Stop backend support functions in Docker
stop-backend: stop-app
	docker-compose -p backend -f ./compose-backend.yml down

stop-all: stop-app stop-backend

# Remove the local config
clean-local:
	./scripts/clean-config.sh
