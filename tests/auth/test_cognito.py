import json
import unittest
from hashlib import pbkdf2_hmac
from unittest import mock

import jwt

import driftbase.auth.cognito
import driftbase.auth.cognito as cognito
from driftbase.auth.authenticate import InvalidRequestException, ServiceUnavailableException, \
    UnauthorizedException
from tests.test_auth import BaseAuthTestCase

# Examples from https://tools.ietf.org/html/rfc7518, https://tools.ietf.org/html/rfc7519
TEST_JWT = 'eyJ0eXAiOiJKV1QiLA0KICJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJqb2UiLA0KICJleHAiOjEzMDA4MTkzODAsDQogImh0dHA6Ly9leGFtcGxlLmNvbS9pc19yb290Ijp0cnVlfQ.dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'
TEST_JWK = '{"kty":"oct", "k":"AyM1SysPpbyDfgZld3umj1qzKObwVMkoqQ-EstJQLr_T-1qS0gZH75aKtMN3Yj0iPS4hcgUuTwjAzZr1Z9CAow", "kid":"test"}'
TEST_JWK_SET = '''{
    "keys":[
        {"kty":"oct", "k":"AyM1SysPpbyDfgZld3umj1qzKObwVMkoqQ-EstJQLr_T-1qS0gZH75aKtMN3Yj0iPS4hcgUuTwjAzZr1Z9CAow", "kid":"test"}
    ]
}'''
TEST_JWT_ALGORITHM = 'HS256'
TEST_USER_POOL_REGION = 'us-west-2'
TEST_USER_POOL_ID = 'us-west-2_abc123'


class TestEosAuthenticate(unittest.TestCase):
    def test_fails_if_missing_or_incorrect_provider_name(self):
        with self.assertRaises(KeyError):
            cognito.authenticate(dict())
        with self.assertRaises(AssertionError):
            cognito.authenticate(dict(provider=None))
        with self.assertRaises(AssertionError):
            cognito.authenticate(dict(provider='myspace'))


class TestEosLoadProviderDetails(unittest.TestCase):
    def test_fails_if_provider_details_missing_or_wrong_type(self):
        with self.assertRaises(InvalidRequestException):
            cognito._load_provider_details(dict(token=None))
        with self.assertRaises(InvalidRequestException):
            cognito._load_provider_details(dict(token=34))
        with self.assertRaises(InvalidRequestException):
            cognito._load_provider_details(dict(token=[]))
        with self.assertRaises(InvalidRequestException):
            cognito._load_provider_details(dict(token='abc', other=3))

    def test_loads_provider_details(self):
        details = cognito._load_provider_details(dict(token='abc'))
        self.assertEqual(details['token'], 'abc')


class TestEosValidate(unittest.TestCase):
    def test_fails_without_configuration(self):
        with mock.patch('driftbase.auth.cognito.get_provider_config') as config:
            config.return_value = None
            with self.assertRaises(ServiceUnavailableException):
                cognito._validate_cognito_token('abc')

    def test_passes_configuration_to_implementation(self):
        with mock.patch('driftbase.auth.cognito.get_provider_config') as config:
            config.return_value = dict(
                client_ids=['xyz'],
                user_pool_region=TEST_USER_POOL_REGION,
                user_pool_id=TEST_USER_POOL_ID
            )
            with mock.patch('driftbase.auth.cognito._run_cognito_token_validation') as validation:
                validation.return_value = 0
                cognito._validate_cognito_token('abc')
                validation.assert_called_once_with('abc', ['xyz'], TEST_USER_POOL_REGION, TEST_USER_POOL_ID)


class TestEosGetKeys(unittest.TestCase):
    def test_fails_when_failing_to_load_keys(self):
        with self.assertRaises(ServiceUnavailableException) as e:
            cognito._get_key_from_token(TEST_JWT, 'https://invalid.com/region/userpool/index.html')
            self.assertTrue(e.exception.msg.find('Failed to fetch') != -1)

    def test_fails_when_key_set_is_empty(self):
        with mock.patch('driftbase.auth.cognito.jwt.PyJWKClient') as mock_jwk_client:
            instance = mock_jwk_client.return_value
            instance.fetch_data.return_value = json.loads('{}')
            instance.get_signing_key_from_jwt.return_value = None
            with self.assertRaises(UnauthorizedException) as e:
                cognito._get_key_from_token(TEST_JWT, driftbase.auth.cognito.COGNITO_PUBLIC_KEYS_URL_TEMPLATE)
                self.assertTrue(e.exception.msg.find('Failed to find') != -1)

    def test_fails_when_key_set_is_invalid(self):
        with mock.patch.object(cognito.jwt.PyJWKClient, 'fetch_data') as mock_fetch:
            mock_fetch.side_effect = json.decoder.JSONDecodeError('mock', '', 42)
            with self.assertRaises(ServiceUnavailableException) as e:
                cognito._get_key_from_token(TEST_JWT, driftbase.auth.cognito.COGNITO_PUBLIC_KEYS_URL_TEMPLATE)
                self.assertTrue(e.exception.msg.find('Failed to read') != -1)


@mock.patch('driftbase.auth.cognito.JWT_ALGORITHM', TEST_JWT_ALGORITHM)
class TestEosRunAuthentication(unittest.TestCase):
    def setUp(self):
        self.token_audience = 'foo'
        self.valid_client_ids = [self.token_audience]
        self.expected_sub = 'cognito_account_id'

    def test_decodes_and_validates_the_sub(self):
        payload = dict(aud=self.token_audience, iss=cognito.TRUSTED_ISSUER_URL_BASE, sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.cognito._get_key_from_token', return_value=jwk.key):
            self.assertEqual(cognito._run_cognito_token_validation(token, self.valid_client_ids, TEST_USER_POOL_REGION,
                                                                   TEST_USER_POOL_ID), self.expected_sub)

    def test_fails_when_audience_is_missing(self):
        payload = dict(iss=cognito.TRUSTED_ISSUER_URL_BASE, sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.cognito._get_key_from_token', return_value=jwk.key):
            with self.assertRaises(UnauthorizedException):
                cognito._run_cognito_token_validation(token, self.valid_client_ids, TEST_USER_POOL_REGION,
                                                      TEST_USER_POOL_ID), self.expected_sub

    def test_fails_when_audience_is_wrong(self):
        payload = dict(aud='other', iss=cognito.TRUSTED_ISSUER_URL_BASE, sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.cognito._get_key_from_token', return_value=jwk.key):
            with self.assertRaises(UnauthorizedException):
                cognito._run_cognito_token_validation(token, self.valid_client_ids, TEST_USER_POOL_REGION,
                                                      TEST_USER_POOL_ID), self.expected_sub

    def test_fails_when_issuer_is_missing(self):
        payload = dict(aus=self.token_audience, sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.cognito._get_key_from_token', return_value=jwk.key):
            with self.assertRaises(UnauthorizedException):
                cognito._run_cognito_token_validation(token, self.valid_client_ids, TEST_USER_POOL_REGION,
                                                      TEST_USER_POOL_ID), self.expected_sub

    def test_fails_when_issuer_is_wrong(self):
        payload = dict(aus=self.token_audience, iss='Acme Industries', sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.cognito._get_key_from_token', return_value=jwk.key):
            with self.assertRaises(UnauthorizedException):
                cognito._run_cognito_token_validation(token, self.valid_client_ids, TEST_USER_POOL_REGION,
                                                      TEST_USER_POOL_ID), self.expected_sub

    def test_fails_when_keys_cannot_be_accessed(self):
        payload = dict(aus=self.token_audience, iss=cognito.TRUSTED_ISSUER_URL_BASE, sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.cognito._get_key_from_token', side_effect=ServiceUnavailableException("")):
            with self.assertRaises(ServiceUnavailableException):
                cognito._run_cognito_token_validation(token, self.valid_client_ids, TEST_USER_POOL_REGION,
                                                      TEST_USER_POOL_ID), self.expected_sub

    def test_fails_when_key_cannot_be_found(self):
        payload = dict(aus=self.token_audience, iss=cognito.TRUSTED_ISSUER_URL_BASE, sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.cognito._get_key_from_token', side_effect=UnauthorizedException("")):
            with self.assertRaises(UnauthorizedException):
                cognito._run_cognito_token_validation(token, self.valid_client_ids, TEST_USER_POOL_REGION,
                                                      TEST_USER_POOL_ID), self.expected_sub


def _make_test_token_and_key(payload):
    jwk = jwt.PyJWK.from_json(TEST_JWK)
    return jwt.encode(payload=payload, key=jwk.key, algorithm=TEST_JWT_ALGORITHM), jwk


@mock.patch('driftbase.auth.cognito.JWT_ALGORITHM', TEST_JWT_ALGORITHM)
class ProviderDetailsTests(BaseAuthTestCase):
    def setUp(self):
        self.token_audience = 'foo'
        self.valid_client_ids = [self.token_audience]
        self.expected_sub = 'cognito_account_id'

    @staticmethod
    def make_provider_data(token):
        return {
            'provider': 'cognito',
            'provider_details': {
                'token': token,
            }
        }

    def test_auth(self):
        with mock.patch('driftbase.auth.cognito.get_provider_config') as config:
            config.return_value = dict(client_ids=[self.token_audience])
            test_cognito_account_id = pbkdf2_hmac('sha256', self.expected_sub.encode('utf-8'),
                                                  b'static_salt', iterations=1).hex()
            payload = dict(aud=self.token_audience, iss=cognito.TRUSTED_ISSUER_URL_BASE, sub=self.expected_sub)
            token, jwk = _make_test_token_and_key(payload)
            with mock.patch('driftbase.auth.cognito._get_key_from_token', return_value=jwk.key):
                user1 = self._auth_and_get_user(self.make_provider_data(token))
            token, jwk = _make_test_token_and_key(payload)
            with mock.patch('driftbase.auth.cognito._get_key_from_token', return_value=jwk.key):
                user2 = self._auth_and_get_user(self.make_provider_data(token))
            assert user1['identity_id'] == user2['identity_id']
            assert user1['user_id'] == user2['user_id']
            assert user1['provider_user_id'] == user2['provider_user_id']
            assert user1['provider_user_id'] == f"cognito:{test_cognito_account_id}"
