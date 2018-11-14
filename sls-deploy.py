#!/usr/bin/env python
import sys
import os
from six.moves.urllib.parse import urlsplit
from datetime import datetime
import subprocess
import json
import shutil

import boto3
import click
from click import echo, secho
from jinja2 import Environment, PackageLoader, FileSystemLoader
from driftconfig.util import get_drift_config
from driftconfig.config import push_to_origin, get_redis_cache_backend
from drift.utils import get_config, pretty


@click.command()
@click.option(
    '--tier-name', '-t', help='Tier name.'
)
@click.option('--preview', '-p', is_flag=True, help="Preview, do not run 'sls' command.")
@click.option('--keep-file', '-k', is_flag=True, help="Do not delete serverless.yml.")
@click.version_option('1.0')
def cli(tier_name, preview, keep_file):
    """Generate settings for Serverless lambdas and deploy to AWS.
    """

    conf = get_config(tier_name=tier_name)
    ts = conf.table_store
    tier = conf.tier
    tier_name = tier['tier_name']

    if 'organization_name' not in tier:
        secho(
            "Note: Tier {} does not define 'organization_name'.".format(tier_name)
        )

    if 'aws' not in tier or 'region' not in tier['aws']:
        click.secho(
            "Note: Tier {} does not define aws.region. Skipping.".format(tier_name)
        )
        return

    click.secho("Processing {}".format(tier_name), bold=True)

    # Figure out in which aws region this config is located
    aws_region = tier['aws']['region']
    ec2 = boto3.resource('ec2', aws_region)
    filters = [
        {'Name': 'tag:tier', 'Values': [tier_name]},
        {
            'Name': 'tag:Name',
            'Values': [
                tier_name + '-private-subnet-1',
                tier_name + '-private-subnet-2',
            ],
        },
    ]
    subnets = list(ec2.subnets.filter(Filters=filters))
    vpc_id = subnets[0].vpc_id
    subnet_ids = [subnet.id for subnet in subnets]

    filters = [
        {'Name': 'tag:tier', 'Values': [tier_name]},
        {'Name': 'tag:Name', 'Values': [tier_name + '-private-sg']},
    ]

    security_groups = list(ec2.security_groups.filter(Filters=filters))
    security_groups = [sg.id for sg in security_groups]

    # To auto-generate Redis cache url, we create the Redis backend using our config,
    # and then ask for a url representation of it:
    config_url = get_redis_cache_backend(ts, tier_name).get_url()

    # Find Cloudwatch log forwarding lambda
    tags_client = boto3.client('resourcegroupstaggingapi', region_name=aws_region)
    functions = tags_client.get_resources(
        TagFilters=[
            {
            'Key': 'tier', 'Values': ['DEVNORTH']
            },
            {
            'Key': 'service-type', 'Values': ['log-forwarder']
            },
        ],
        ResourceTypeFilters=['lambda:function']
    )['ResourceTagMappingList']
    log_forwarding_arn = functions[0]['ResourceARN'] if functions else None

    # Sum it up
    #
    # Template input parameters:
    # tier:
    #     tier_name
    #     config_url
    #     aws_region
    #     vpc_id
    #     security_groups
    #     subnets
    # deployable:
    #     deployable_name
    #
    # wsgiapp: true|false
    #
    # events: (array of:)
    #     function_name     Actual Python function name, must be unique for the deployable
    #     event_type        One of s3, schedule, sns, sqs
    #
    #     # S3 specifics
    #     bucket            bucket name
    #
    #     # schedule specifics
    #     rate              rate or cron https://amzn.to/2yFynEA
    #
    #     # sns specifics
    #     topicName
    #
    #     # sqs specifics
    #     arn                arn:aws:sqs:region:XXXXXX:myQueue
    #     batchSize          10

    tier_args = {
        'tier': {
            'tier_name': tier_name,
            'config_url': config_url,
            'aws_region': aws_region,
            'vpc_id': vpc_id,
            'security_groups': security_groups,
            'subnets': subnet_ids,
        },
        'deployable': {'deployable_name': conf.drift_app['name']},
        'wsgiapp': True,
        'events': [],
        'log_forwarding_arn': log_forwarding_arn,
    }

    package = {
        'name': '{}-lambda'.format(conf.drift_app['name']),
        'dependencies': {
            'serverless-python-requirements': '^4.2.5',
            'serverless-log-forwarding': '^1.2.1',
        }
    }

    # env = Environment(loader=PackageLoader('driftconfig', package_path='templates'))
    secho("\nTemplate parameters:\n----------------------------", bold=True)
    secho(pretty(tier_args, 'json'))
    secho("\npackage.json:\n----------------------------", bold=True)
    secho(pretty(package, 'json'))
    env = Environment(loader=FileSystemLoader(searchpath="./"))
    template = env.get_template('serverless.jinja.yml')
    settings_text = template.render(**tier_args)
    secho("\nserverless.yml:\n----------------------------", bold=True)
    secho(pretty(settings_text, 'yaml'))

    secho("----------------------------")
    filename_yaml = 'serverless.yml'
    with open(filename_yaml, 'w') as f:
        f.write(settings_text)
    filename_json = 'package.json'
    with open(filename_json, 'w') as f:
        json.dump(package, f)

    try:
        if preview:
            secho("Preview only. Exiting now.")
            sys.exit(1)

        for plugin_name in ['serverless-python-requirements', 'serverless-log-forwarding']:
            cmd = ['sls', 'plugin', 'install', '--name', plugin_name]
            echo("Running command: {}".format(' '.join(cmd)))
            subprocess.call(cmd)

        cmd = ['sls', 'deploy']
        echo("Running command: {}".format(' '.join(cmd)))
        subprocess.call(cmd)
    except FileNotFoundError as e:
        secho(str(e))
        secho("Is serverless installed? npm install -g serverless", bold=True)
    finally:
        if not keep_file:
            os.unlink(filename_yaml)
            os.unlink(filename_json)
            shutil.rmtree('.serverless', ignore_errors=True)
            shutil.rmtree('./node_modules', ignore_errors=True)


if __name__ == '__main__':
    cli()
