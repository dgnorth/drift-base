ARG PYTHON_VERSION=3.7
ARG BASE_IMAGE=buster

FROM python:${PYTHON_VERSION}-${BASE_IMAGE} as builder

WORKDIR /build

ENV PYTHONUSERBASE=/root/.app

RUN python -m pip install --upgrade pip \
    && pip install pipenv \
    && pip install --user --ignore-installed --no-warn-script-location uwsgi

COPY Pipfile* ./
# Pipenv will ignore qualifying system packages during install, so we need to route through pip to ensure everything
# really ends up in our /root/.local folder where we want it to be
RUN pipenv lock --keep-outdated -r >requirements.txt
RUN pip install --user --ignore-installed --no-warn-script-location -r requirements.txt

FROM python:${PYTHON_VERSION}-slim-${BASE_IMAGE} as app
LABEL Maintainer="Directive Games <info@directivegames.com>"

RUN addgroup --gid 1000 uwsgi && useradd -ms /bin/bash uwsgi -g uwsgi

RUN UWSGI_RUNTIME_DEPS=libxml2 \
    && apt-get update \
    && apt-get install -y --no-install-recommends ${UWSGI_RUNTIME_DEPS}

WORKDIR /app

COPY --chown=uwsgi:uwsgi --from=builder /root/.app/ /home/uwsgi/.local/
COPY . .

ARG VERSION
ARG BUILD_TIMESTAMP
ARG COMMIT_HASH

LABEL AppVersion="${VERSION}"
LABEL CommitHash="${COMMIT_HASH}"

# For runtime consumption
RUN echo '{"version": "'${VERSION}'", "build_timestamp": "'${BUILD_TIMESTAMP}'", "commit_hash": "'${COMMIT_HASH}'"}' > .build_info

USER uwsgi

ENV PATH /home/uwsgi/.local/bin:$PATH

CMD ["/home/uwsgi/.local/bin/uwsgi", "--ini", "/app/config/uwsgi.ini"]
