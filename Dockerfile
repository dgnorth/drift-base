ARG PYTHON_VERSION=3.7
ARG BASE_IMAGE=buster

FROM python:${PYTHON_VERSION}-${BASE_IMAGE} as builder

WORKDIR /build

RUN pip install pipenv && pip install --user --no-warn-script-location uwsgi

COPY Pipfile* ./
# To ensure all packages we need end up in .local for copying, we tell pipenv to install in system mode, meaning not in
# a virtual env. But then we also tell pip to install in --user mode, which forces install to $HOME/.local. Finally we
# ignore preinstalled modules so that .local actually ends up containing everything we want
RUN PIP_USER=1 PIP_IGNORE_INSTALLED=1 pipenv install --deploy --system

FROM python:${PYTHON_VERSION}-slim-${BASE_IMAGE} as app
LABEL Maintainer="Directive Games <info@directivegames.com>"

RUN addgroup --gid 1000 uwsgi && useradd -ms /bin/bash uwsgi -g uwsgi

RUN UWSGI_RUNTIME_DEPS=libxml2 \
    && apt-get update \
    && apt-get install -y --no-install-recommends ${UWSGI_RUNTIME_DEPS}

WORKDIR /app

COPY --chown=uwsgi:uwsgi --from=builder /root/.local/ /home/uwsgi/.local/
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

# run dconf to initialize the local drift config store
# CMD dconf developer -r

CMD ["/home/uwsgi/.local/bin/uwsgi", "--ini", "/app/config/uwsgi.ini"]
