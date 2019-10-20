############################################
### Extract info from git without bundling git into something.
FROM alpine/git as buildinfo
WORKDIR /buildinfo
ADD ./.git .
RUN echo '{"tag": "'$(git describe --tags)'", "tag_long": "'$(git describe --tags --long)'", "branch": "'$(git rev-parse --abbrev-ref HEAD)'", "commit_sha": "'$(git rev-parse HEAD | cut -c 1-8)'", "build_timestamp": "'$(date -u +"%Y-%m-%dT%H:%M:%SZ")'"}' > .buildinfo.json
RUN cat .buildinfo.json

FROM python:3.7
MAINTAINER directivegames-north <dgnorth@directivegames.com>

RUN groupadd uwsgi && useradd -m -g uwsgi uwsgi

RUN apt update
RUN apt install -y nano htop jq
RUN pip3 install pipenv uwsgi

WORKDIR /app
RUN chown uwsgi /app

COPY Pipfile* ./
RUN pipenv install --system --deploy --ignore-pipfile
# .git is not in .dockerignore so that we can access it in the `buildinfo` build stage.
RUN rm -rf .git

COPY --from=buildinfo /buildinfo/. .

COPY . .

RUN chmod 777 -R /app

# sadly this does not work so we are limited to 128 listen sockets in uwsgi config
RUN echo net.core.somaxconn=4096 >> /etc/sysctl.conf

RUN echo "dconf developer --shared && uwsgi --ini /app/config/uwsgi.ini" >> /app/run_local.sh

USER uwsgi

ENV AWS_EXECUTION_ENV=1

CMD [ "uwsgi", "--ini", "/app/config/uwsgi.ini" ]
