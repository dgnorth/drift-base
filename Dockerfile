# Extract the latest version from git tag and bake into the resulting container
FROM python:3
MAINTAINER Directive Games <info@directivegames.com>

WORKDIR /app

RUN pip install pipenv uwsgi

COPY Pipfile* ./
RUN pipenv install --system --deploy --dev

RUN addgroup --gid 1000 uwsgi
RUN useradd -ms /bin/bash uwsgi -g uwsgi

COPY . .

ARG VERSION
ARG BUILD_TIMESTAMP
ARG COMMIT_HASH
RUN echo '{"version": "'$VERSION'", "build_timestamp": "'$BUILD_TIMESTAMP'", "commit_hash": "'$COMMIT_HASH'"}' > .build_info

USER uwsgi

# run dconf to initialize the local drift config store
CMD dconf developer -r

CMD [ "uwsgi", "--ini", "/app/config/uwsgi.ini" ]
