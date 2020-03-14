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

## Docker on EC2

Launch config for Centos:

```bash
# Install, run and configue Docker
sudo amazon-linux-extras install docker
sudo service docker start
sudo usermod -a -G docker ec2-user

# Configure systemd service
echo '[Unit]
Description=Drift Base Server
After=syslog.target

[Service]
Type=notify
EnvironmentFile=/etc/environment
ExecStart=docker run --env-file=/etc/.env -p 8080:8080 directivegames/drift-base
Restart=on-failure
RestartSec=5
KillSignal=SIGQUIT
User=root
NotifyAccess=all

[Install]
WantedBy=multi-user.target
' > drift-docker.service

sudo ln drift-docker.service /etc/systemd/system/multi-user.target.wants

```

Launch config for Ubuntu:

```bash
# Install, run and configue Docker
sudo apt-get update
sudo apt install docker.io -y
sudo systemctl start docker
sudo systemctl enable docker

# Configure systemd service
echo '[Unit]
Description=Drift Base Server
After=docker.service
Requires=docker.service

[Service]
Restart=always
Type=simple
ExecStart=/usr/bin/docker run --name drift-base --rm -e DRIFT_TIER=DEVNORTH -e DRIFT_CONFIG_URL=redis://redis.devnorth.dg-api.com:6379/0?prefix=dgnorth -p 8080:8080 -p 10080:10080 directivegames/drift-base:latest
User=root

[Install]
WantedBy=multi-user.target
' > drift.service

sudo ln drift-docker.service /etc/systemd/system/multi-user.target.wants

echo '[Unit]
Description=Datadog Agent
Requires=docker.service
After=docker.service

[Service]
Restart=always
StartLimitInterval=0
RestartSec=5
ExecStart=/usr/bin/docker run --name datadog-agent \
           -e DD_API_KEY=11a5abdfc262789710896bdbb17663a3 \
           -e DD_LOGS_ENABLED=true \
           -e DD_LOGS_CONFIG_CONTAINER_COLLECT_ALL=true \
           -e DD_AC_EXCLUDE="name:datadog-agent" \
           -v /var/run/docker.sock:/var/run/docker.sock:ro \
           -v /proc/:/host/proc/:ro \
           -v /opt/datadog-agent/run:/opt/datadog-agent/run:rw \
           -v /sys/fs/cgroup/:/host/sys/fs/cgroup:ro \
           --rm \
           datadog/agent:latest

[Install]
WantedBy=multi-user.target' > dd-agent.service

```



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

