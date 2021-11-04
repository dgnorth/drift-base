from unittest import mock

import json
import jwt
import unittest

import driftbase.auth.eos as eos
from driftbase.auth.authenticate import InvalidRequestException, ServiceUnavailableException, \
    UnauthorizedException

# Examples from https://tools.ietf.org/html/rfc7518, https://tools.ietf.org/html/rfc7519
TEST_JWT = 'eyJ0eXAiOiJKV1QiLA0KICJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJqb2UiLA0KICJleHAiOjEzMDA4MTkzODAsDQogImh0dHA6Ly9leGFtcGxlLmNvbS9pc19yb290Ijp0cnVlfQ.dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'
TEST_JWK = '{"kty":"oct", "k":"AyM1SysPpbyDfgZld3umj1qzKObwVMkoqQ-EstJQLr_T-1qS0gZH75aKtMN3Yj0iPS4hcgUuTwjAzZr1Z9CAow", "kid":"test"}'
TEST_JWK_SET = '''{
    "keys":[
        {"kty":"oct", "k":"AyM1SysPpbyDfgZld3umj1qzKObwVMkoqQ-EstJQLr_T-1qS0gZH75aKtMN3Yj0iPS4hcgUuTwjAzZr1Z9CAow", "kid":"test"}
    ]
}'''
TEST_JWT_ALGORITHM = 'HS256'


class TestEosAuthenticate(unittest.TestCase):
    def test_fails_if_missing_or_incorrect_provider_name(self):
        with self.assertRaises(KeyError):
            eos.authenticate(dict())
        with self.assertRaises(AssertionError):
            eos.authenticate(dict(provider=None))
        with self.assertRaises(AssertionError):
            eos.authenticate(dict(provider='myspace'))


class TestEosLoadProviderDetails(unittest.TestCase):
    def test_fails_if_provider_details_missing_or_wrong_type(self):
        with self.assertRaises(InvalidRequestException):
            eos._load_provider_details(dict(token=None))
        with self.assertRaises(InvalidRequestException):
            eos._load_provider_details(dict(token=34))
        with self.assertRaises(InvalidRequestException):
            eos._load_provider_details(dict(token=[]))
        with self.assertRaises(InvalidRequestException):
            eos._load_provider_details(dict(token='abc', other=3))

    def test_loads_provider_details(self):
        details = eos._load_provider_details(dict(token='abc'))
        self.assertEqual(details['token'], 'abc')


class TestEosValidate(unittest.TestCase):
    def test_fails_without_configuration(self):
        with mock.patch('driftbase.auth.eos.get_provider_config') as config:
            config.return_value = None
            with self.assertRaises(ServiceUnavailableException):
                eos._validate_eos_token('abc')

    def test_passes_configuration_to_implementation(self):
        with mock.patch('driftbase.auth.eos.get_provider_config') as config:
            config.return_value = dict(client_ids=['xyz'])
            with mock.patch('driftbase.auth.eos._run_eos_token_validation') as validation:
                validation.return_value = 0
                eos._validate_eos_token('abc')
                validation.assert_called_once_with('abc', ['xyz'])


class TestEosGetKeys(unittest.TestCase):
    @mock.patch('driftbase.auth.eos.EPIC_PUBLIC_KEYS_URL', 'https://invalid.com/index.html')
    def test_fails_when_failing_to_load_keys(self):
        with self.assertRaises(ServiceUnavailableException) as e:
            eos._get_key_from_token(TEST_JWT)
        self.assertTrue(e.exception.msg.find('Failed to fetch') != -1)

    def test_fails_when_key_set_is_empty(self):
        with mock.patch('driftbase.auth.eos.jwt.PyJWKClient') as mock_jwk_client:
            instance = mock_jwk_client.return_value
            instance.fetch_data.return_value = json.loads('{}')
            instance.get_signing_key_from_jwt.return_value = None
            with self.assertRaises(UnauthorizedException) as e:
                eos._get_key_from_token(TEST_JWT)
            self.assertTrue(e.exception.msg.find('Failed to find') != -1)

    def test_fails_when_key_set_is_invalid(self):
        with mock.patch.object(eos.jwt.PyJWKClient, 'fetch_data') as mock_fetch:
            mock_fetch.side_effect = json.decoder.JSONDecodeError('mock', '', 42)
            with self.assertRaises(ServiceUnavailableException) as e:
                eos._get_key_from_token(TEST_JWT)
            self.assertTrue(e.exception.msg.find('Failed to read') != -1)


@mock.patch('driftbase.auth.eos.JWT_ALGORITHM', TEST_JWT_ALGORITHM)
class TestEosRunAuthentication(unittest.TestCase):
    def setUp(self):
        self.token_audience = 'foo'
        self.valid_client_ids = [self.token_audience]
        self.expected_sub = 'eos_account_id'

    def test_decodes_and_validates_the_sub(self):
        payload = dict(aud=self.token_audience, iss=eos.TRUSTED_ISSUER_URL_BASE, sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.eos._get_key_from_token', return_value=jwk.key):
            self.assertEqual(eos._run_eos_token_validation(token, self.valid_client_ids), self.expected_sub)

    def test_fails_when_audience_is_missing(self):
        payload = dict(iss=eos.TRUSTED_ISSUER_URL_BASE, sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.eos._get_key_from_token', return_value=jwk.key):
            with self.assertRaises(UnauthorizedException):
                eos._run_eos_token_validation(token, self.valid_client_ids), self.expected_sub

    def test_fails_when_audience_is_wrong(self):
        payload = dict(aud='other', iss=eos.TRUSTED_ISSUER_URL_BASE, sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.eos._get_key_from_token', return_value=jwk.key):
            with self.assertRaises(UnauthorizedException):
                eos._run_eos_token_validation(token, self.valid_client_ids), self.expected_sub

    def test_fails_when_issuer_is_missing(self):
        payload = dict(aus=self.token_audience, sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.eos._get_key_from_token', return_value=jwk.key):
            with self.assertRaises(UnauthorizedException):
                eos._run_eos_token_validation(token, self.valid_client_ids), self.expected_sub

    def test_fails_when_issuer_is_wrong(self):
        payload = dict(aus=self.token_audience, iss='Acme Industries', sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.eos._get_key_from_token', return_value=jwk.key):
            with self.assertRaises(UnauthorizedException):
                eos._run_eos_token_validation(token, self.valid_client_ids), self.expected_sub

    def test_fails_when_keys_cannot_be_accessed(self):
        payload = dict(aus=self.token_audience, iss=eos.TRUSTED_ISSUER_URL_BASE, sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.eos._get_key_from_token', side_effect=ServiceUnavailableException("")):
            with self.assertRaises(ServiceUnavailableException):
                eos._run_eos_token_validation(token, self.valid_client_ids), self.expected_sub

    def test_fails_when_key_cannot_be_found(self):
        payload = dict(aus=self.token_audience, iss=eos.TRUSTED_ISSUER_URL_BASE, sub=self.expected_sub)
        token, jwk = _make_test_token_and_key(payload)
        with mock.patch('driftbase.auth.eos._get_key_from_token', side_effect=UnauthorizedException("")):
            with self.assertRaises(UnauthorizedException):
                eos._run_eos_token_validation(token, self.valid_client_ids), self.expected_sub


def _make_test_token_and_key(payload):
    jwk = jwt.PyJWK.from_json(TEST_JWK)
    return jwt.encode(payload=payload, key=jwk.key, algorithm=TEST_JWT_ALGORITHM), jwk
