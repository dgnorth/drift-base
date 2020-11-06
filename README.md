[![Build Status](https://github.com/directivegames/drift-base/workflows/Build%20and%20Test/badge.svg)](https://github.com/directivegames/drift-base)
[![codecov](https://codecov.io/gh/directivegames/drift-base/branch/develop/graph/badge.svg)](https://codecov.io/gh/directivegames/drift-base)


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

### Building drift-base
Drift-base runs in docker. To build and push a docker image run the following:
```bash
make build
make push
```

This will create a docker image called `directivegames/drift-base:<branch-name>` and push it to dockerhub here: https://hub.docker.com/repository/docker/directivegames/drift-base/tags?page=1

You can run the container locally with the following command:
```bash
make run
```
Note that you must have the following environment variables set up: `DRIFT_TIER` and `DRIFT_CONFIG_URL`. See example.env.

drift-base docker images are automatically built by GutHub Actions on all branches and tagged by the branch name. If any git tag is pushed, a docker image will be built with that tag as well.

Versioned images are created in this way. Simply add a version tag to git and an image with correct version will be built. Any image built after this version tag push will export the same version in its root endpoint.

To create a new version of drift-base run:
```bash
git tag 1.2.3
git push --tags
```

Note that tiers will typically run a branch-tagged version of drift-base. A development tier will run `:develop` and a live tier `:master`. However, this behavior can be set per tier when the launch config and autoscaling group is set up (see next section).

The Watchtower <https://hub.docker.com/r/v2tec/watchtower/> service is running on the ec2 machines that serve drift-base and will automatically update the service every 5 minutes. This means that if you push to develop the development tier should have that version running within 5 minutes. You can see when this has been completed by inspecting the `build_info` key in the root endpoint of the service.

### Create an AMI
Since drift-base is running in docker it is not necessary to create new AMI's for every deployment. In fact, new ami's only need to be created when there are updates to the infrastructure or basic dependencies like datadog and watchtower.

To build an AMI you will need to have the current AWS profile set correctly so that you can create instances in the eu-west-1 region.

```bash
make buildami
```

This will build a new AMI image and make it available in the following regions:
- eu-west-1
- us-east-1
- ap-southeast-1

The built AMI will however not be used until it is added to autoscaling. For testing you can always launch it yourself however, and I would recommend using 'launch more like this' on an existing drift-base instance to get all the required settings but that is an exercise for the user.

AMI's are not versioned but their name contains the timestamp when they were created. 

There is no service or tier configuration baked into the AMI. All that information is added via user data when the AMI is launched (new launch config created) below.

### Launching AMI
Once a new AMI has been created it needs to be added into an autoscaling group in a tier.
To do this you can run the following command:
```bash
make launchami
```

Before you do this however, you will need to set up your environment. We recommend copying `example.env` to `.env` and running `pipenv shell`, which will source the `.env` file and makes things easier, but it's up to you how you set up the environment.

There are a few things you will need to add into the .env file such as the tier name, redis url of the drift config database, etc. You will need to gather these pieces of information from elsewhere.

Since building AMI's is a rare occurence there is no CI process for this and the AMI's will need to be built manually using this process.

If you want to change the docker tag that should be deployed to a tier you can use this process without needing to create a new AMI.

The command will only take a few seconds to run and a new AMI should be running in the tier via autoscaling within 5 minutes.
