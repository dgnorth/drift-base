import logging

import marshmallow as ma
import requests
from flask import request
from drift.blueprint import abort
import http.client as http_client
from werkzeug.exceptions import Unauthorized

from driftbase.auth import get_provider_config
from .authenticate import authenticate as base_authenticate

log = logging.getLogger(__name__)


class GooglePlayProviderAuthDetailsSchema(ma.Schema):
    user_id = ma.fields.String(required=True)
    id_token = ma.fields.String(required=True)


class GooglePlayProviderAuthSchema(ma.Schema):
    provider = ma.fields.String(required=True)
    provider_details = ma.fields.Nested(GooglePlayProviderAuthDetailsSchema, required=True)


def authenticate(auth_info):
    assert auth_info['provider'] == "googleplay"
    provider_details = auth_info.get('provider_details')
    automatic_account_creation = auth_info.get("automatic_account_creation", True)

    if provider_details.get('provisional', False):
        if len(provider_details['username']) < 1:
            abort_unauthorized("Bad Request. 'username' cannot be an empty string.")
        username = "googleplay:" + provider_details['username']
        password = provider_details['password']
        return base_authenticate(username, password, automatic_account_creation)
    identity_id = validate_googleplay_token()
    username = "googleplay:" + identity_id
    return authenticate(username, "", automatic_account_creation)


def validate_googleplay_token():
    """Validate Google Play token from /auth call."""

    ob = request.get_json()
    try:
        GooglePlayProviderAuthSchema().load(ob)
    except ma.ValidationError as e:
        abort_unauthorized("Google Play token property %s is invalid" % e.field_name)
    provider_details = ob['provider_details']
    # Get Google Play authentication config
    gp_config = get_provider_config('googleplay')

    if not gp_config:
        abort(http_client.SERVICE_UNAVAILABLE,
              description="Google Play authentication not configured for current tenant")

    app_client_ids = gp_config.get("client_ids", None)

    # Call validation and authenticate if token is good
    identity_id = run_token_validation(
        user_id=provider_details['user_id'],
        id_token=provider_details['id_token'],
        app_client_ids=app_client_ids
    )

    return identity_id


def run_token_validation(user_id, id_token, app_client_ids):
    """
    Validates Google Play ID token.

    Returns a unique ID for this player.
    """
    token_check_url = 'https://www.googleapis.com/oauth2/v3/tokeninfo?id_token={id_token}'
    url = token_check_url.format(id_token=id_token)

    try:
        ret = requests.post(url, headers={'Accept': 'application/json'})
    except requests.exceptions.RequestException as e:
        log.warning("Google Play authentication request failed: %s", e)
        abort_unauthorized("Google Play token validation failed. Can't reach Google Play platform.")

    if ret.status_code != 200:
        log.warning("Failed Google Play authentication. Token: '%s'... Response code %s: %s",
                    id_token[:10], ret.status_code, ret.json())
        abort_unauthorized("User {} not authenticated on Google Play platform.".format(user_id))

    claims = ret.json()
    if app_client_ids and claims.get("aud", None) not in app_client_ids:
        abort_unauthorized("Client ID {} not one of {}.".format(user_id, app_client_ids))

    claim_user_id = claims.get("sub", None)
    if claim_user_id != user_id:
        abort_unauthorized("User ID {} doesn't match claim {}.".format(user_id, claim_user_id))

    claim_issuer = claims.get("iss", "")
    trusted_issuer = "https://accounts.google.com"
    if claim_issuer != trusted_issuer:
        abort_unauthorized("Claim issuer {} doesn't match {}.".format(claim_issuer, trusted_issuer))

    return user_id


def abort_unauthorized(description):
    """Raise an Unauthorized exception.
    """
    raise Unauthorized(description=description)
