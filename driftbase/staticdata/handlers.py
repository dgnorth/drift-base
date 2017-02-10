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
    revs = {}
    try:
        data = g.conf.tenant.get('static_data_refs_legacy')
        if data:
            origin = "Tenant config"
        else:
            data = {
                "repository": "directivegames/the-machines-static-data",
                "revision": "refs/heads/develop",
            }
            origin = "Hardcoded defaults"

            repo = data['repository']
            revs[repo] = data, origin
    except:
        log.error("Error getting static data. data='%s', origin='%s'" % (repr(data), origin))
        log.exception()

    return revs


class StaticDataAPI(Resource):

    no_jwt_check = ['GET']

    get_args = reqparse.RequestParser()
    get_args.add_argument(
        "static_data_ref", type=str,
        help="A GIT reference tag to get a particular version"
    )

    def get(self):
        """
        Returns server side config that the client needs
        """
        args = self.get_args.parse_args()
        data = {}

        def get_from_url(url):
            content = g.redis.get(url)
            if content:
                return json.loads(content)

            with g.redis.lock("lock" + url):
                content = g.redis.get(url)
                if content:
                    return json.loads(content)
                r = requests.get(url)
                r.raise_for_status()
                g.redis.set(url, r.text, expire=50)
                return r.json()

        data["static_data_urls"] = []

        for repository, (ref_entry, origin) in get_static_data_ids().items():

            # Get the index file from S3 and index it by 'ref'
            index_file_url = "{}{}/index.json".format(INDEX_URL, repository)
            err = None
            try:
                index_file = get_from_url(index_file_url)
            except Exception as e:
                err = "Can't fetch %s: %s" % (index_file_url, e)
                log.exception(err)
            if err:
                data["error"] = err
                continue
            print "ref_entry", ref_entry
            index_file = {ref_entry["ref"]: ref_entry for ref_entry in index_file["index"]}

            # Use this ref if it matches
            ref = index_file.get(ref_entry["revision"])

            # Override if client is pinned to a particular version
            if ref_entry.get("allow_client_pin", False) and args.static_data_ref in index_file:
                ref = index_file[args.static_data_ref]
                origin = "Client pin"

            def make_data_url(root_url, repository, ref):
                if not root_url.endswith('/'):
                    root_url += '/'
                return '{}{}/data/{}/'.format(root_url, repository, ref)

            if ref:
                d = {
                    "repository": repository,
                    "revision": ref["ref"],
                    "commit_id": ref["commit_id"],
                    "origin": origin,
                    "data_root_url": make_data_url(DATA_URL, repository, ref["commit_id"]),
                    "cdn_list": [
                        {'cdn': cdn,
                         'data_root_url': make_data_url(root_url, repository, ref["commit_id"]),
                         }
                        for cdn, root_url in CDN_LIST
                    ],
                }
                data["static_data_urls"].append(d)

        return data


api.add_resource(StaticDataAPI, "/static-data", endpoint="staticdata")


@register_endpoints
def endpoint_info(current_users):
    return {
        "static_data": url_for("staticdata.staticdata", _external=True),
    }
