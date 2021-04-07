import logging

import marshmallow as ma
import requests
from flask import request
from flask_smorest import abort
from six.moves import http_client
from werkzeug.exceptions import Unauthorized

from driftbase.auth import get_provider_config
from .authenticate import authenticate as base_authenticate

log = logging.getLogger(__name__)


class OculusProviderAuthDetailsSchema(ma.Schema):
    user_id = ma.fields.String(required=True)
    nonce = ma.fields.String(required=True)


class OculusProviderAuthSchema(ma.Schema):
    provider = ma.fields.String(required=True)
    provider_details = ma.fields.Nested(OculusProviderAuthDetailsSchema, required=True)


def authenticate(auth_info):
    assert auth_info['provider'] == 'oculus'
    provider_details = auth_info.get('provider_details')
    automatic_account_creation = auth_info.get("automatic_account_creation", True)

    if provider_details.get('provisional', False):
        if len(provider_details['username']) < 1:
            abort_unauthorized("Bad Request. 'username' cannot be an empty string.")
        username = "oculus:" + provider_details['username']
        password = provider_details['password']
        return base_authenticate(username, password, True or automatic_account_creation)
    identity_id = validate_oculus_ticket()
    username = "oculus:" + identity_id
    return base_authenticate(username, "", True or automatic_account_creation)


def validate_oculus_ticket():
    """Validate Oculus ticket from /auth call."""

    ob = request.get_json()
    try:
        OculusProviderAuthSchema().load(ob)
    except ma.ValidationError as e:
        abort_unauthorized("Oculus token property %s is invalid" % e.field_name)

    provider_details = ob['provider_details']
    # Get Oculus authentication config
    oculus_config = get_provider_config('oculus')

    if not oculus_config:
        abort(http_client.SERVICE_UNAVAILABLE, description="Oculus authentication not configured for current tenant")

    # Call validation and authenticate if ticket is good
    identity_id = run_ticket_validation(
        user_id=provider_details['user_id'],
        access_token=oculus_config['access_token'],
        nonce=provider_details['nonce']
    )

    return identity_id


def run_ticket_validation(user_id, access_token, nonce):
    """
    Validates Oculus session ticket.

    Returns a unique ID for this player.
    """
    token_check_url = 'https://graph.oculus.com/user_nonce_validate?access_token={access_token}&nonce={nonce}&user_id={user_id}'
    url = token_check_url.format(user_id=user_id, access_token=access_token, nonce=nonce)

    try:
        ret = requests.post(url, headers={'Accept': 'application/json'})
    except requests.exceptions.RequestException as e:
        log.warning("Oculus authentication request failed: %s", e)
        abort_unauthorized("Oculus ticket validation failed. Can't reach Oculus platform.")

    if ret.status_code != 200 or not ret.json().get('is_valid', False):
        log.warning("Failed Oculus authentication. Response code %s: %s", ret.status_code, ret.json())
        abort_unauthorized("User {} not authenticated on Oculus platform.".format(user_id))

    return user_id


def abort_unauthorized(description):
    """Raise an Unauthorized exception.
    """
    raise Unauthorized(description=description)
