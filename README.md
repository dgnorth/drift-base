[![Build Status](https://travis-ci.org/dgnorth/drift-base.svg?branch=master)](https://travis-ci.org/dgnorth/drift-base)
[![codecov](https://codecov.io/gh/dgnorth/drift-base/branch/develop/graph/badge.svg)](https://codecov.io/gh/dgnorth/drift-base)


# drift-base
Base Services for Drift micro-framework.


## Installation:
Run the following commands to install this project in developer mode:

```bash
pip install --user pipenv
pipenv install --dev
```

Run the following commands to enable drift and drift-config in developer mode for this project:

```bash
pipenv shell  # Make sure the virtualenv is active

pip install -e "../drift[aws,test]"
pip install -e "../drift-config[s3-backend,redis-backend]"
```

## Run localserver
This starts a server on port 5000:

```bash
pipenv shell  # Make sure the virtualenv is active

export FLASK_APP=drift.devapplocal:app
flask run
```

Try it out here:
[http://localhost:5000/](http://localhost:5000/)

## Run docker-compose
docker-compose.yml contains the drift-base service and redis and postgres dependencies. If you install docker for desktop then docker compose is already included and you can simply run:
```bash
docker-compose up
```
This will download the latest version of drift-base along with postgres and redis and will run the server in local development mode.

Try it out here:
[http://localhost:8080/](http://localhost:8080/)

## Modifying library dependencies
Python package dependencies are maintained in **Pipfile**. If you make any changes there, update the **Pipfile.lock** file as well using the following command:

```bash
pipenv --rm && pipenv lock --verbose
```

## Working with AWS

Note! For any of the following commands to work, make sure the virtualenv is active and the proper configuration database and tier is selected:

```bash
pipenv shell
export DRIFT_CONFIG_URL=somecfg && export DRIFT_TIER=SOME_NAME
```

#### Create an AMI and deploy to AWS:

```bash
drift-admin ami bake
drift-admin ami run
```

#### Fetch logs straight from the EC2
```bash
drift-admin logs
```

#### Deploy local code changes directly to AWS:

```bash
drift-admin quickdeploy
```

#### Open SSH to the EC2:

```bash
drift-admin ssh drift-base
```

