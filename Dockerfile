# Extract the latest version from git tag and bake into the resulting container
FROM python:3
MAINTAINER Directive Games <info@directivegames.com>

RUN pip3 install pipenv uwsgi
ARG VERSION
WORKDIR /app

COPY Pipfile* ./
RUN pipenv install --system --deploy --dev

RUN addgroup --gid 1000 uwsgi
RUN useradd -ms /bin/bash uwsgi -g uwsgi

COPY . .
RUN echo $VERSION > VERSION

USER uwsgi

# run dconf to initialize the local drift config store
CMD dconf developer -r

CMD [ "uwsgi", "--ini", "/app/config/uwsgi.ini" ]
