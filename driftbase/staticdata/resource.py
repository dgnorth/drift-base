# -*- coding: utf-8 -*-

import requests
import logging
import json

from flask import Blueprint, g, url_for, current_app
from flask_restful import Api, Resource, reqparse

from drift.urlregistry import register_endpoints

bp = Blueprint("staticdata", __name__)
api = Api(bp)

log = logging.getLogger(__file__)


# Assumption: The static data CDN is here:
INDEX_URL = "https://s3-eu-west-1.amazonaws.com/directive-tiers.dg-api.com/static-data/"
DATA_URL = "https://static-data.dg-api.com/"

CDN_LIST = [
    ['cloudfront', DATA_URL],
    ['alicloud', 'http://directive-tiers.oss-cn-shanghai.aliyuncs.com/static-data/'],
]


def get_static_data_ids():
    """Returns a dict of all static data repos and revision identifiers that apply to the
    current caller. Each entry is tagged with which config it originated from.
    Key is repository name, value is [ref, origin] pair.
    """
    revs = {}  # Key is repo

    def add_ref(config, origin):
        if "static_data_refs" in config:
            for ref in config["static_data_refs"]:
                revs[ref["repository"]] = ref, origin

    # The app config.
    add_ref(current_app.config, "Application config")
    add_ref(g.driftenv_objects, "Config specific to tenant '{}'.".format(g.driftenv["name"]))

    return revs


# defaults when making a new tier
NEW_TIER_DEFAULTS = {
    "s3_bucket": "<PLEASE FILL IN>",  # Example: directive-tiers.dg-api.com
    "s3_path":  "<PLEASE FILL IN>",   # Example: static-data
}


def provision(config, args):

    # Static data repo is per product
    if 'static_data_repo_defaults' not in config.product:
        config.product['static_data_repo_defaults'] = tier['s3_bucket'] + tier['s3_path']

    # Create entry for this tenant
    static_data_refs =
    {
        "static_data_repo": config.product['static_data_repo_defaults'],
        "repo_path": "directivegames/superkaiju-staticdata",
        "revision": "refs/heads/beta",
        "allow_client_pin": true,
    }

    config.tenant['static_data_refs'] = [static_data_refs]


def healthcheck():
    if "postgres" not in g.conf.tenant:
        raise RuntimeError("Tenant config does not have 'postgres'")
    for k in NEW_TIER_DEFAULTS.keys():
        if not g.conf.tenant["postgres"].get(k):
            raise RuntimeError("'postgres' config missing key '%s'" % k)

    rows = g.db.execute("SELECT 1+1")
    result = rows.fetchall()[0]



