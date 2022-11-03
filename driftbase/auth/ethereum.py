import datetime
import eth_keys.exceptions
import eth_utils.exceptions
import http.client as http_client
import json
import logging
import marshmallow as ma
from eth_account import Account
from eth_account.messages import encode_defunct
from flask_smorest import abort
from werkzeug.security import pbkdf2_hex

from driftbase.auth import get_provider_config
from .authenticate import authenticate as base_authenticate, AuthenticationException, ServiceUnavailableException, \
    abort_unauthorized, InvalidRequestException, UnauthorizedException

log = logging.getLogger(__name__)

DEFAULT_TIMESTAMP_LEEWAY = 60


def utcnow():
    return datetime.datetime.utcnow()


class EthereumProviderAuthDetailsSchema(ma.Schema):
    signer = ma.fields.String(required=True, allow_none=False)
    message = ma.fields.String(required=True, allow_none=False)
    signature = ma.fields.String(required=True, allow_none=False)


def authenticate(auth_info):
    assert auth_info['provider'] == 'ethereum'

    try:
        parameters = _load_provider_details(auth_info['provider_details'])
    except InvalidRequestException as e:
        abort(http_client.BAD_REQUEST, message=e.msg)
    except KeyError as e:
        abort(http_client.BAD_REQUEST, message="Missing provider_details")

    try:
        identity_id = _validate_ethereum_message(**parameters)
    except ServiceUnavailableException as e:
        abort(http_client.SERVICE_UNAVAILABLE, message=e.msg)
    except InvalidRequestException as e:
        abort(http_client.BAD_REQUEST, message=e.msg)
    except AuthenticationException as e:
        abort_unauthorized(e.msg)

    automatic_account_creation = auth_info.get('automatic_account_creation', True)
    # FIXME: The static salt should perhaps be configured per tenant
    username = "ethereum:" + pbkdf2_hex(identity_id, 'static_salt', iterations=1)
    return base_authenticate(username, "", automatic_account_creation)


def _load_provider_details(provider_details):
    try:
        return EthereumProviderAuthDetailsSchema().load(provider_details)
    except ma.exceptions.ValidationError as e:
        raise InvalidRequestException(f"{e}") from None


def _validate_ethereum_message(signer, message, signature):
    ethereum_config = get_provider_config('ethereum')
    if ethereum_config is None:
        raise ServiceUnavailableException("Ethereum authentication not configured for current tenant")

    timestamp_leeway = ethereum_config.get('timestamp_leeway', DEFAULT_TIMESTAMP_LEEWAY)

    return _run_ethereum_message_validation(signer, message, signature, timestamp_leeway=timestamp_leeway)


def _run_ethereum_message_validation(signer, message, signature, timestamp_leeway=DEFAULT_TIMESTAMP_LEEWAY):
    try:
        recovered = Account.recover_message(encode_defunct(text=message), signature=signature).lower()
    except eth_utils.exceptions.ValidationError:
        raise InvalidRequestException("Signature validation failed") from None
    except ValueError:
        raise InvalidRequestException("Signature contains invalid characters") from None
    except eth_keys.exceptions.BadSignature:
        raise InvalidRequestException("Bad signature") from None

    message = json.loads(message)
    timestamp = datetime.datetime.fromisoformat(message['timestamp'][:-1])
    if utcnow() - timestamp > datetime.timedelta(seconds=timestamp_leeway):
        raise UnauthorizedException("Timestamp out of bounds")
    if utcnow() + datetime.timedelta(seconds=5) < timestamp:
        raise UnauthorizedException("Timestamp is in the future")

    if recovered != signer.lower():
        raise UnauthorizedException("Signer does not match passed in address")

    return recovered
