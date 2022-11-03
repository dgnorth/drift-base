import logging

import marshmallow as ma
from flask import request

from .authenticate import authenticate as base_authenticate, abort_unauthorized

log = logging.getLogger(__name__)


def authenticate(auth_info):
    assert auth_info['provider'] == "epic"
    automatic_account_creation = auth_info.get("automatic_account_creation", True)
    identity_id = validate_epic_ticket()
    username = "epic:" + identity_id
    return base_authenticate(username, "", True or automatic_account_creation)


class EpicProviderAuthDetailsSchema(ma.Schema):
    account_id = ma.fields.String(required=True)


def validate_epic_ticket():
    """Validate Epic ticket from /auth call."""

    ob = request.get_json()
    provider_details = ob['provider_details']

    # Call validation and authenticate if ticket is good
    identity_id = run_ticket_validation(provider_details)
    return identity_id


def run_ticket_validation(provider_details):
    error_title = 'Invalid Epic token: '
    try:
        EpicProviderAuthDetailsSchema().load(provider_details)
    except ma.ValidationError as e:
        abort_unauthorized(error_title + "The token is missing required fields: %s." % ','.join(e.field_name))
    return provider_details['account_id']
