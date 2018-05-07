#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import os.path
import json
import logging
from datetime import datetime
import mimetypes
import subprocess
from urlparse import urlparse
import re
import copy
from driftconfig.util import get_default_drift_config
from drift.utils import get_tier_name

import click

STATIC_DATA_ROOT_FOLDER = 'static-data'  # Root folder on S3


@click.group(context_settings=dict(help_option_names=['-h', '--help']))
def cli():
    """Static data management tools.

    These sets of commands help you with publishing and testing Static Data.
    """


@cli.command()
@click.option(
    '--repository',
    help="The name of the source repository that contains the static data files. If not "
         "specified then the name will be extracted from the url path from `git config "
         "--get remote.origin.url`.")
@click.option(
    '--user',
    help="A user name. The current version of static data on local disk will be published "
         "under /user-<user name>/. If not specified, then all referencable versions "
         "will be published.")
@click.option(
    '--region',
    default='eu-west-1',
    help="AWS region, default is 'eu-west-1'.")
@click.option(
    '--bucket',
    default='directive-tiers.dg-api.com',
    help="Bucket name, default is 'directive-tiers.dg-api.com'.")
def publish(repository, user, region, bucket):
    """Publish static data files to S3.

    Publish static data files by uploading to S3 and update the index file. All referencable
    versions will be published (i.e. all ).
    """
    print "=========== STATIC DATA COMPRESSION ENABLED ==========="
    from boto.s3 import connect_to_region
    from boto.s3.connection import OrdinaryCallingFormat
    from boto.s3.key import Key

    conn = connect_to_region(region, calling_format=OrdinaryCallingFormat())
    bucket = conn.get_bucket(bucket)

    origin_url = None
    if not repository:
        try:
            cmd = 'git config --get remote.origin.url'
            print "No repository specified. Using git to figure it out:", cmd
            origin_url = subprocess.check_output(cmd.split(' ')).strip()
            if origin_url.startswith("http"):
                repository, _ = os.path.splitext(urlparse(origin_url).path)
            elif origin_url.startswith("git@"):
                repository = "/" + origin_url.split(":")[1].split(".")[0]
            else:
                raise Exception("Unknown origin url format")
        except Exception as e:
            logging.exception(e)
            print "Unable to find repository from origin url '{}'".format(origin_url)
            raise e
        print "Found repository '{}' from '{}'".format(repository, origin_url)
    else:
        print u"Using repository: {}".format(repository)

    s3_upload_batch = []  # List of [filename, data] pairs to upload to bucket.
    repo_folder = "{}{}/data/".format(STATIC_DATA_ROOT_FOLDER, repository)

    if user:
        print "User defined reference ..."
        to_upload = set()
        # TODO: This will crash. No serialno??
        s3_upload_batch.append(["user-{}/{}".format(user, serialno)])
    else:
        # We need to checkout a few branches. Let's remember which branch is currently active
        cmd = 'git symbolic-ref --short HEAD'
        print "Get all tags and branch head revisions for this repo using:", cmd
        try:
            current_branch = subprocess.check_output(cmd.split(' '), stderr=subprocess.STDOUT).strip()
        except subprocess.CalledProcessError as e:
            print "Failed to detect the current branch for '{}':\n{}".format(origin_url, e.output)
            raise e

        # Get all references
        to_upload = set()  # Commit ID's to upload to S3
        indexes = []  # Full list of git references to write to index.json

        print "Index file:"
        ls_remote = subprocess.check_output('git ls-remote --quiet'.split(' ')).strip()
        now = datetime.utcnow()
        for refline in ls_remote.split('\n'):
            commit_id, ref = refline.split("\t")
            # We are only interested in head revision of branches, and tags
            if not ref.startswith("refs/heads/") and not ref.startswith("refs/tags/"):
                continue

            # We want a dereferenced tag
            if ref.startswith("refs/tags/") and not ref.endswith("^{}"):
                continue

            # Prune any "dereference" markers from the ref string.
            ref = ref.replace("^{}", "")

            print "    {:<50}{}".format(ref, commit_id)
            to_upload.add(commit_id)
            indexes.append({"commit_id": commit_id, "ref": ref})

        # List out all subfolders under the repo name to see which commits are already there.
        # Prune the 'to_upload' list accordingly.
        for key in bucket.list(prefix=repo_folder, delimiter="/"):
            # See if this is a commit_id formatted subfolder
            m = re.search("^.*/([a-f0-9]{40})/$", key.name)
            if m:
                commit_id = m.groups()[0]
                to_upload.discard(commit_id)

        # For any referenced commit on git, upload it to S3 if it is not already there.
        print "\nNumber of commits to upload: {}".format(len(to_upload))
        for commit_id in to_upload:
            cmd = "git checkout {}".format(commit_id)
            print "Running git command:", cmd
            print subprocess.check_output(cmd.split(' ')).strip()
            try:
                types_str = json.dumps(load_types())
                schemas_str = json.dumps(load_schemas())
                s3_upload_batch.append(["{}/types.json".format(commit_id), types_str])
                s3_upload_batch.append(["{}/schemas.json".format(commit_id), schemas_str])
            except Exception as e:
                logging.exception(e)
                print "Not uploading {}: {}".format(commit_id, e)
                raise e

        cmd = "git checkout {}".format(current_branch)
        print "Reverting HEAD to original state: "
        print subprocess.check_output(cmd.split(' ')).strip()

    # Upload to S3
    for key_name, data in s3_upload_batch:
        key = Key(bucket)
        mimetype, encoding = mimetypes.guess_type(key_name)
        if not mimetype and key_name.endswith(".json"):
            mimetype = "application/json"
        if mimetype:
            key.set_metadata('Content-Type', mimetype)
        key.set_metadata('Cache-Control', "max-age=1000000")
        key.key = "{}{}".format(repo_folder, key_name)
        print "Uploading: {}".format(key.key)
        key.set_contents_from_string(data)
        key.set_acl('public-read')

    # Upload index
    refs_index = {"created": now.isoformat() + "Z",
                  "repository": repository,
                  "index": indexes,
                  }
    key = Key(bucket)
    key.set_metadata('Content-Type', "application/json")
    key.set_metadata('Cache-Control', "max-age=0, no-cache, no-store")
    key.key = "{}{}/index.json".format(STATIC_DATA_ROOT_FOLDER, repository)
    print "Uploading: {}".format(key.key)
    key.set_contents_from_string(json.dumps(refs_index))
    key.set_acl('public-read')

    print "All done!"


@cli.command()
@click.option(
    '--region',
    default='eu-west-1',
    help="AWS region, default is 'eu-west-1'.")
@click.option(
    '--bucket',
    default='directive-tiers.dg-api.com',
    help="Source bucket name, default is 'directive-tiers.dg-api.com'.")
def mirror(region, bucket):
    """Mirror static data to other CDNs."""

    #ts = get_default_drift_config()
    bucket = get_s3_bucket(region, bucket)
    keys = set()
    for key in bucket.list(prefix="static-data/", delimiter="/"):
        if key.name == "static-data/":
            continue
        if key.name == "static-data/logs/":
            continue
        for key2 in bucket.list(prefix=key.name, delimiter=""):
            keys.add(key2.name)

    print "{} s3 objects loaded".format(len(keys))

    mirror_alicloud(copy.copy(keys), bucket)

    print "ALL DONE!"


def get_s3_bucket(region, bucket):
    from boto.s3 import connect_to_region
    from boto.s3.connection import OrdinaryCallingFormat

    conn = connect_to_region(region, calling_format=OrdinaryCallingFormat())
    bucket = conn.get_bucket(bucket)
    return bucket


ALICLOUD_ENDPOINT = "http://oss-cn-shanghai.aliyuncs.com"
ALICLOUD_BUCKETNAME = "directive-tiers"


def mirror_alicloud(keys, s3_bucket):
    print "mirroring to alicloud..."
    access_key = os.environ.get("OSS_ACCESS_KEY_ID", "")
    if not access_key:
        raise RuntimeError("Missing environment variable 'OSS_ACCESS_KEY_ID' "
                           "for alicloud access key")

    access_secret = os.environ.get("OSS_SECRET_ACCESS_KEY", "")
    if not access_secret:
        raise RuntimeError("Missing environment variable 'OSS_SECRET_ACCESS_KEY' "
                           "for alicloud access secret")

    try:
        import oss2
    except ImportError as e:
        print e
        print "You need to install it using `pip install oss2`."
        return

    auth = oss2.Auth(access_key, access_secret)
    bucket = oss2.Bucket(auth, ALICLOUD_ENDPOINT, ALICLOUD_BUCKETNAME)

    for object_info in oss2.ObjectIterator(bucket):
        # always update the index file
        if "index.json" in object_info.key:
            continue

        if object_info.key in keys and 1:
            keys.discard(object_info.key)

    index = 0
    for key in keys:
        source = s3_bucket.get_key(key)

        headers = {
            "x-oss-object-acl": "public-read",
        }

        # copy the headers
        if source.content_type:
            headers["Content-Type"] = source.content_type

        if source.cache_control:
            headers["Cache-Control"] = source.cache_control

        if source.content_encoding:
            headers["Content-Encoding"] = source.content_encoding

        if source.content_language:
            headers["Content-Language"] = source.content_language

        if source.content_disposition:
            headers["Content-Disposition"] = source.content_disposition

        content = source.get_contents_as_string()
        bucket.put_object(key, content, headers=headers)
        index += 1
        print "[{}/{}] copying {}".format(index, len(keys), key)


# This code lifted straight from /the-machines-static-data/tools/publish.py and path_helper.py
def find_files(root, recursive):
    files = []
    for fname in os.listdir(root):
        full = os.path.join(root, fname)
        if os.path.isfile(full):
            files.append(full)
        elif os.path.isdir(full) and recursive:
            files += find_files(full, recursive)
    return files


def load_types():
    types = {}
    for file_path in find_files("./types", True):
        _, filename = os.path.split(file_path)
        basename, ext = os.path.splitext(filename)
        if ext.lower() == ".json":
            try:
                int(basename)
            except ValueError:
                continue

            with open(file_path, "r") as f:
                info = json.loads(f.read())
                published = info.get("published", True)
                typeID = info["typeID"]
                if not published:
                    print "Type {} is not published".format(typeID)
                    continue
                if typeID in types:
                    raise RuntimeError(
                        "type %s is already visited" % typeID
                    )
                types[typeID] = info
    return types


def load_schemas():
    schemas = {}
    for file_path in find_files("./schemas", False):
        _, filename = os.path.split(file_path)
        basename, ext = os.path.splitext(filename)
        if ext.lower() == ".json":
            with open(file_path, "r") as f:
                info = json.loads(f.read())
                schemas[basename.lower()] = info
    return schemas


if __name__ == '__main__':
    cli()
