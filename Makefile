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

# Helper targets

.PHONY: ENV_GUARD

env-guard-%: ENV_GUARD
	@if [ -z '${${*}}' ]; then echo 'Environment variable $* not set' && exit 1; fi

# Build targets

.PHONY: build push test

build: env-guard-REGISTRY
	docker build \
	    --tag ${IMAGE_NAME}:latest \
	    --tag ${IMAGE_NAME}:${BRANCH_TAG} \
	    --tag ${IMAGE_NAME}:${VERSION} \
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

~/.drift/config/local/domain.json: create-config.sh
	./create-config.sh

local-config: ~/.drift/config/local/domain.json
	pipenv run driftconfig cache local

run-app: run-backend local-config
	docker-compose -p app -f ./compose-app.yml up

run-appd: run-backend local-config
	docker-compose -p app -f ./compose-app.yml up -d

stop-app:
	docker-compose -p app -f ./compose-app.yml down

run-backend:
	docker-compose -p backend -f ./compose-backend.yml up -d

stop-backend:
	docker-compose -p backend -f ./compose-backend.yml down

stop-all: stop-app stop-backend
