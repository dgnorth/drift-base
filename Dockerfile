FROM python:3.7

RUN pip3 install pipenv pytest

WORKDIR /app

COPY Pipfile* ./
RUN pipenv install --system --deploy --dev

COPY . .

CMD dconf developer -r
