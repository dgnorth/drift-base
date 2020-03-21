PACKAGE_NAME = driftbase
IMAGE_NAME = directivegames/drift-base

BRANCH = $(shell git rev-parse --abbrev-ref HEAD)
VERSION = $(shell cat ${PACKAGE_NAME}/VERSION)

CI_COMMIT_REF_NAME ?= $(shell git rev-parse --abbrev-ref HEAD)
CI_COMMIT_SHORT_SHA ?= $(shell git rev-parse HEAD | cut -c 1-8)
BUILD_TIMESTAMP = $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")

export FLASK_APP=${PACKAGE_NAME}.app:app

.PHONY: auth push build clean info release release-master

build:
	docker build -t ${IMAGE_NAME} .
	docker tag ${IMAGE_NAME} ${IMAGE_NAME}:${BRANCH}

git-tag:
	git tag ${VERSION}		
	git push origin --tags -o ci.skip

run:
	docker run -e DRIFT_TIER=DEVNORTH \
			   -e DRIFT_CONFIG_URL='redis://redis.devnorth.dg-api.com:6379/0?prefix=dgnorth' \
			   -e DRIFT_DEFAULT_TENANT=dg-daedalus-devnorth \
			   -e DEBUG=True \
			   -p 10080:10080 \
			   -p 8080:8080 \
			   -p 9191:9191 \
			   ${IMAGE_NAME}:latest

serve: 
	export FLASK_ENV=development && export DRIFT_OUTPUT=text && export LOGLEVEL=info && \
	dconf developer -r -s

upgrade:
	pipenv run flask db upgrade 

black:
	black -l 100 -S ${PACKAGE_NAME}
