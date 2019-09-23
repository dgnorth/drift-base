FROM python:3.7
MAINTAINER directivegames-north <dgnorth@directivegames.com>

RUN groupadd uwsgi && useradd -m -g uwsgi uwsgi

COPY config/uwsgi.ini /etc/uwsgi/uwsgi.ini
#ENV UWSGI_INI /etc/uwsgi/uwsgi.ini

RUN apt update
RUN apt install nano htop
RUN pip3 install pipenv uwsgi

WORKDIR /app
RUN chown uwsgi /app

COPY Pipfile* ./
RUN pipenv install --system --deploy

COPY . .

RUN chmod 777 -R /app

RUN echo net.core.somaxconn=4096 >> /etc/sysctl.conf

USER uwsgi

ENV DRIFT_CONFIG_URL=developer
ENV DRIFT_TIER=LOCALTIER
ENV DRIFT_DEFAULT_TENANT=localorg-localdev
ENV FLASK_APP=drift.devapp:app
ENV FLASK_ENV=development
ENV AWS_EXECUTION_ENV=1

RUN dconf developer

CMD [ "uwsgi", "--ini", "/app/uwsgi.ini" ]
