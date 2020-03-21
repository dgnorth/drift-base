# Extract the version from git tag and bake into the resulting container
FROM python:3 as build_info
WORKDIR /
ADD ./.git .
RUN git tag --sort=committerdate | grep -E '^[0-9]' | tail -1 > VERSION

FROM python:3
MAINTAINER Directive Games <matti@directivegames.com>

RUN pip3 install pipenv uwsgi

WORKDIR /app

COPY Pipfile* ./
RUN pipenv install --system --deploy --dev

RUN addgroup --gid 1000 uwsgi
RUN useradd -ms /bin/bash uwsgi -g uwsgi

COPY . .
COPY --from=build_info VERSION driftbase/

USER uwsgi

# run dconf to initialize the local drift config store
CMD dconf developer -r

CMD [ "uwsgi", "--ini", "/app/config/uwsgi.ini" ]
