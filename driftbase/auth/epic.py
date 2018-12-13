
import logging
from six.moves import http_client

from flask import request

from drift.core.extensions.schemachecker import check_schema
from .authenticate import authenticate as base_authenticate

log = logging.getLogger(__name__)


def authenticate(auth_info):
    assert auth_info['provider'] == "epic"
    automatic_account_creation = auth_info.get("automatic_account_creation", True)
    identity_id = validate_epic_ticket()
    username = "epic:" + identity_id
    return base_authenticate(username, "", True or automatic_account_creation)


# Epic provider details schema
epic_provider_schema = {
    'type': 'object',
    'properties':
    {
        'provider_details':
        {
            'type': 'object',
            'properties':
            {
                'account_id': {'type': 'string'},
            },
            'required': ['account_id'],
        },
    },
    'required': ['provider_details'],
}


def validate_epic_ticket():
    """Validate Epic ticket from /auth call."""

    ob = request.get_json()
    check_schema(ob, epic_provider_schema, "Error in request body.")
    provider_details = ob['provider_details']

       # Call validation and authenticate if ticket is good
    identity_id = run_ticket_validation(provider_details)
    return identity_id


def run_ticket_validation(provider_details):
    return provider_details['account_id']
