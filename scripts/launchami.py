"""
Cr"""
import os
import sys
import operator
from datetime import datetime

from click import echo, secho
import boto3

IAM_ROLE = "ec2"


def abort(txt):
    secho(txt, fg="red")
    sys.exit(1)


try:
    DRIFT_CONFIG_URL = os.environ["DRIFT_CONFIG_URL"]
    DRIFT_TIER = os.environ["DRIFT_TIER"]
    DD_API_KEY = os.environ["DD_API_KEY"]
    DOCKER_IMAGE = os.environ["DOCKER_IMAGE"]
    INSTANCE_TYPE = os.environ["INSTANCE_TYPE"]
    AWS_REGION = os.environ["AWS_REGION"]
    SSH_KEY_NAME = os.environ["SSH_KEY_NAME"]
    SERVICE_NAME = os.environ["SERVICE_NAME"]
    MIN_INSTANCES = int(os.environ.get("MIN_INSTANCES", 1))
    MAX_INSTANCES = int(os.environ.get("MAX_INSTANCES", 1))
    DESIRED_INSTANCES = int(os.environ.get("DESIRED_INSTANCES", 1))
    DRIFT_PORT = os.environ.get("DRIFT_PORT", 10080)
except KeyError as ex:
    abort(f"Environment not set up. Please see example.env: {ex}")


def filterize(d):
    """
    Return dictionary 'd' as a boto3 "filters" object by unfolding it to a list of
    dict with 'Name' and 'Values' entries.
    """
    return [{"Name": k, "Values": [v]} for k, v in d.items()]


def _find_latest_ami():
    ec2 = boto3.resource("ec2", region_name=AWS_REGION)
    filters = [{"Name": "tag:service-name", "Values": ["driftapp"]}]
    amis = list(ec2.images.filter(Owners=["self"], Filters=filters))
    if not amis:
        abort("No AMI found")

    ami = max(amis, key=operator.attrgetter("creation_date"))
    return ami


def run_command():

    ami = _find_latest_ami()
    echo("AMI: {} [{}]".format(ami.id, ami.name))

    ec2 = boto3.resource("ec2", region_name=AWS_REGION)

    # Get all 'private' subnets
    filters = {"tag:tier": DRIFT_TIER, "tag:realm": "private"}
    subnets = list(ec2.subnets.filter(Filters=filterize(filters)))
    if not subnets:
        abort("Error: No subnet available matching filter {}".format(filters))

    # Get the "one size fits all" security group
    filters = {"tag:tier": DRIFT_TIER, "tag:Name": "{}-private-sg".format(DRIFT_TIER)}
    security_group = list(ec2.security_groups.filter(Filters=filterize(filters)))[0]

    target_name = f"{DRIFT_TIER}-{SERVICE_NAME}-auto"

    tags = {
        "Name": target_name,
        "tier": DRIFT_TIER,
        "service-name": SERVICE_NAME,
        "service-type": "web-app",
        "config-url": DRIFT_CONFIG_URL,
        "app-root": "",
        "launched-by": boto3.client("sts").get_caller_identity()["Arn"],
        "api-target": SERVICE_NAME,
        "api-port": str(DRIFT_PORT),
        "api-status": "online",
        "docker-image": DOCKER_IMAGE
    }

    user_data = f"""#!/bin/bash
# Environment variables set by drift-admin run command:
export DRIFT_CONFIG_URL={DRIFT_CONFIG_URL}
export DRIFT_TIER={DRIFT_TIER}
export DD_API_KEY={DD_API_KEY}
export DOCKER_IMAGE={DOCKER_IMAGE}

sudo bash -c "echo DRIFT_CONFIG_URL=$DRIFT_CONFIG_URL >> /etc/environment"
sudo bash -c "echo DRIFT_TIER=$DRIFT_TIER >> /etc/environment"
sudo bash -c "echo DD_API_KEY=$DD_API_KEY >> /etc/environment"
sudo bash -c "echo DOCKER_IMAGE=$DOCKER_IMAGE >> /etc/environment"
sudo bash -c "echo HOST_ADDRESS=$(hostname -i) >> /etc/environment"

"""

    user_data = user_data.replace("\r\n", "\n")

    client = boto3.client("autoscaling", region_name=AWS_REGION)
    launch_config_name = "{}-{}-launchconfig-{}".format(
        DRIFT_TIER, SERVICE_NAME, datetime.utcnow()
    )
    launch_config_name = launch_config_name.replace(":", ".")

    kwargs = dict(
        LaunchConfigurationName=launch_config_name,
        ImageId=ami.id,
        KeyName=SSH_KEY_NAME,
        SecurityGroups=[security_group.id],
        InstanceType=INSTANCE_TYPE,
        IamInstanceProfile=IAM_ROLE,
        InstanceMonitoring={"Enabled": True},
        UserData=user_data,
    )

    client.create_launch_configuration(**kwargs)

    echo(f"Launch configuration {launch_config_name} has been created")

    # Update current autoscaling group or create a new one if it doesn't exist.
    groups = client.describe_auto_scaling_groups(AutoScalingGroupNames=[target_name])

    kwargs = dict(
        AutoScalingGroupName=target_name,
        LaunchConfigurationName=launch_config_name,
        MinSize=MIN_INSTANCES,
        MaxSize=MAX_INSTANCES,
        DesiredCapacity=DESIRED_INSTANCES,
        VPCZoneIdentifier=",".join([subnet.id for subnet in subnets]),
    )

    if not groups["AutoScalingGroups"]:
        echo(f"Creating a new autoscaling group {target_name}")
        client.create_auto_scaling_group(**kwargs)
    else:
        echo(f"Updating current autoscaling group {target_name}")
        client.update_auto_scaling_group(**kwargs)

    # Prepare tags which get propagated to all new instances
    tagsarg = [
        {
            "ResourceId": tags["Name"],
            "ResourceType": "auto-scaling-group",
            "Key": k,
            "Value": v,
            "PropagateAtLaunch": True,
        }
        for k, v in tags.items()
    ]
    echo("Updating tags on autoscaling group that get propagated to all new instances.")
    client.create_or_update_tags(Tags=tagsarg)

    # Define a 2 min termination cooldown so api-router can drain the connections.
    echo("Configuring lifecycle hook.")
    drain_minutes = 4
    response = client.put_lifecycle_hook(
        LifecycleHookName=f"Wait-{drain_minutes}-minutes-on-termination",
        AutoScalingGroupName=target_name,
        LifecycleTransition="autoscaling:EC2_INSTANCE_TERMINATING",
        HeartbeatTimeout=drain_minutes*60,
        DefaultResult="CONTINUE",
    )

    echo("Terminating instances in autoscaling group. New ones will be launched.")
    echo(f"Old instances will linger for {drain_minutes} minutes while connections are drained.")
    asg = client.describe_auto_scaling_groups(AutoScalingGroupNames=[target_name])
    for instance in asg["AutoScalingGroups"][0]["Instances"]:
        response = client.terminate_instance_in_auto_scaling_group(
            InstanceId=instance["InstanceId"], ShouldDecrementDesiredCapacity=False
        )
        echo("   " + response["Activity"]["Description"])

    secho("Done!", fg="green")


if __name__ == "__main__":
    run_command()
