PACKAGE_NAME = driftbase
IMAGE_NAME = directivegames/drift-base

BRANCH ?= $(shell git rev-parse --abbrev-ref HEAD)
VERSION ?= $(shell git tag --sort=committerdate | grep -E '^[0-9]' | tail -1)

CI_COMMIT_REF_NAME ?= $(shell git rev-parse --abbrev-ref HEAD)
CI_COMMIT_SHORT_SHA ?= $(shell git rev-parse HEAD | cut -c 1-8)
BUILD_TIMESTAMP = $(shell date -u +"%Y-%m-%dT%H:%M:%SZ")

export FLASK_APP=${PACKAGE_NAME}.app:app

.PHONY: auth push build clean info release

build:
	docker build -t ${IMAGE_NAME} . --build-arg VERSION='${VERSION}' --build-arg BUILD_TIMESTAMP='${BUILD_TIMESTAMP}' --build-arg COMMIT_HASH='${CI_COMMIT_SHORT_SHA}'
	docker tag ${IMAGE_NAME} ${IMAGE_NAME}:${BRANCH}
	docker push ${IMAGE_NAME}:latest
	docker push ${IMAGE_NAME}:${BRANCH}

buildami:
	cd aws && packer build packer.json

launchami:
	python scripts/launchami.py

git-tag:
	git tag ${VERSION}		
	git push origin --tags -o ci.skip

run:
	docker run -e DRIFT_TIER=${DRIFT_TIER} \
			   -e DRIFT_CONFIG_URL=${DRIFT_CONFIG_URL} \
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
