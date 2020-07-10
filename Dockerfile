FROM python:3.7-buster as builder

WORKDIR /build

RUN pip install --no-warn-script-location pipenv && pip install --user --no-warn-script-location uwsgi

COPY Pipfile* ./
# To ensure all packages we need end up in .local for copying, we tell pipenv to install in system mode, meaning not in
# a virtual env. But then we also tell pip to install in --user mode, which forces install to $HOME/.local. Finally we
# ignore preinstalled modules so that .local actually ends up containing everything we want
RUN PIP_USER=1 PIP_IGNORE_INSTALLED=1 pipenv install --deploy --system

FROM python:3.7-slim-buster as app
LABEL maintainer="Directive Games <info@directivegames.com>"

RUN addgroup --gid 1000 uwsgi
RUN useradd -ms /bin/bash uwsgi -g uwsgi

# Supposed to prevent a harmless warning from apt-get install, but currently doesn't seem to work
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y libxml2

WORKDIR /app

COPY --chown=uwsgi:uwsgi --from=builder /root/.local/ /home/uwsgi/.local/
COPY . .

ARG VERSION
ARG BUILD_TIMESTAMP
ARG COMMIT_HASH
RUN echo '{"version": "'$VERSION'", "build_timestamp": "'$BUILD_TIMESTAMP'", "commit_hash": "'$COMMIT_HASH'"}' > .build_info

USER uwsgi

ENV PATH /home/uwsgi/.local/bin:$PATH

# run dconf to initialize the local drift config store
# CMD dconf developer -r

CMD ["/home/uwsgi/.local/bin/uwsgi", "--ini", "/app/config/uwsgi.ini"]
