import datetime
import unittest
from unittest import mock

import driftbase.auth.ethereum as ethereum
from driftbase.auth.authenticate import InvalidRequestException, ServiceUnavailableException, \
    UnauthorizedException
from tests.test_auth import BaseAuthTestCase


class TestEthereumAuthenticate(unittest.TestCase):
    def test_fails_if_missing_or_incorrect_provider_name(self):
        with self.assertRaises(KeyError):
            ethereum.authenticate(dict())
        with self.assertRaises(AssertionError):
            ethereum.authenticate(dict(provider=None))
        with self.assertRaises(AssertionError):
            ethereum.authenticate(dict(provider='myspace'))


class TestEthereumLoadProviderDetails(unittest.TestCase):
    def test_fails_if_provider_details_missing_or_wrong_type(self):
        with self.assertRaises(InvalidRequestException):
            ethereum._load_provider_details(dict(token=None))
        with self.assertRaises(InvalidRequestException):
            ethereum._load_provider_details(dict(token=34))
        with self.assertRaises(InvalidRequestException):
            ethereum._load_provider_details(dict(token=[]))
        with self.assertRaises(InvalidRequestException):
            ethereum._load_provider_details(dict(token='abc', other=3))

    def test_loads_provider_details(self):
        details = ethereum._load_provider_details(dict(message='abc', signer='bob', signature='xyz'))
        self.assertEqual(details['message'], 'abc')
        self.assertEqual(details['signer'], 'bob')
        self.assertEqual(details['signature'], 'xyz')


class TestEthereumValidate(unittest.TestCase):
    def test_fails_without_configuration(self):
        with mock.patch('driftbase.auth.ethereum.get_provider_config') as config:
            config.return_value = None
            with self.assertRaises(ServiceUnavailableException):
                ethereum._validate_ethereum_message('bob', 'abc', 'xyz')

    def test_passes_configuration_to_implementation(self):
        with mock.patch('driftbase.auth.ethereum.get_provider_config') as config:
            config.return_value = dict()
            with mock.patch('driftbase.auth.ethereum._run_ethereum_message_validation') as validation:
                validation.return_value = 0
                ethereum._validate_ethereum_message('bob', 'abc', 'xyz')
                validation.assert_called_once_with('bob', 'abc', 'xyz',
                                                   timestamp_leeway=ethereum.DEFAULT_TIMESTAMP_LEEWAY)
        with mock.patch('driftbase.auth.ethereum.get_provider_config') as config:
            config.return_value = dict(timestamp_leeway=42)
            with mock.patch('driftbase.auth.ethereum._run_ethereum_message_validation') as validation:
                validation.return_value = 0
                ethereum._validate_ethereum_message('bob', 'abc', 'xyz')
                validation.assert_called_once_with('bob', 'abc', 'xyz',
                                                   timestamp_leeway=42)


class TestEthereumRunAuthentication(unittest.TestCase):
    def setUp(self):
        self.address = '0x854Cc1Ce8e826e514f1dD8127f9D0AF689f181A9'
        self.message = '{\r\n\t"message": "Authorize for Drift login",\r\n\t"timestamp": "2022-01-12T08:12:59.787Z"\r\n}'
        self.signature = '0x5b0bf23f6cccf4315f561a04aef11b60dadced91bc17ac168db14b467851d4010349a8d3fbaec28c4671eb27ba7a8160900b51c2ded5137b3a9804881f3ee32c1c'
        self.bad_signature = '0xdeadbeef6cccf4315f561a04aef11b60dadced91bc17ac168db14b467851d4010349a8d3fbaec28c4671eb27ba7a8160900b51c2ded5137b3a9804881f3ee32c1c'
        self.timestamp = datetime.datetime.fromisoformat('2022-01-12T08:12:59.787')

    def test_authenticates_when_signature_matches(self):
        with mock.patch('driftbase.auth.ethereum.utcnow') as now:
            now.return_value = self.timestamp + datetime.timedelta(seconds=5)
            self.assertEqual(self.address.lower(),
                             ethereum._run_ethereum_message_validation(self.address, self.message, self.signature))

    def test_fails_when_account_does_not_match_signature(self):
        with mock.patch('driftbase.auth.ethereum.utcnow') as now:
            now.return_value = self.timestamp + datetime.timedelta(seconds=5)
            with self.assertRaises(UnauthorizedException):
                signature = self.signature.replace('0x5', '0x6')
                ethereum._run_ethereum_message_validation(self.address, self.message, signature)

    def test_fails_when_signature_is_malformed(self):
        with mock.patch('driftbase.auth.ethereum.utcnow') as now:
            now.return_value = self.timestamp + datetime.timedelta(seconds=5)
            # long signature
            with self.assertRaises(InvalidRequestException):
                signature = self.signature + '6'
                ethereum._run_ethereum_message_validation(self.address, self.message, signature)
            # wrong signature
            with self.assertRaises(InvalidRequestException):
                signature = self.bad_signature
                ethereum._run_ethereum_message_validation(self.address, self.message, signature)
            # short signature
            with self.assertRaises(InvalidRequestException):
                signature = self.signature[:-5]
                ethereum._run_ethereum_message_validation(self.address, self.message, signature)
            # non-hex digits appended
            with self.assertRaises(InvalidRequestException):
                signature = self.signature + 'non-hex-digits'
                ethereum._run_ethereum_message_validation(self.address, self.message, signature)

    def test_fails_when_passed_in_address_is_different_from_recovered_signer(self):
        with mock.patch('driftbase.auth.ethereum.utcnow') as now:
            now.return_value = self.timestamp + datetime.timedelta(seconds=5)
            with self.assertRaises(UnauthorizedException):
                address = self.address.replace('0x8', '0x9')
                ethereum._run_ethereum_message_validation(address, self.message, self.signature)

    def test_fails_when_timestamp_is_out_of_bounds(self):
        with mock.patch('driftbase.auth.ethereum.utcnow') as now:
            now.return_value = self.timestamp + datetime.timedelta(seconds=ethereum.DEFAULT_TIMESTAMP_LEEWAY + 50)
            with self.assertRaises(UnauthorizedException):
                ethereum._run_ethereum_message_validation(self.address, self.message, self.signature)

    def test_can_extend_timestamp_leeway_in_config(self):
        leeway = ethereum.DEFAULT_TIMESTAMP_LEEWAY + 500
        with mock.patch('driftbase.auth.ethereum.utcnow') as now:
            now.return_value = self.timestamp + datetime.timedelta(seconds=leeway - 50)
            ethereum._run_ethereum_message_validation(self.address, self.message, self.signature,
                                                      timestamp_leeway=leeway)

    def test_fails_when_timestamp_is_in_the_future(self):
        with mock.patch('driftbase.auth.ethereum.utcnow') as now:
            now.return_value = self.timestamp - datetime.timedelta(seconds=10)
            with self.assertRaises(UnauthorizedException):
                ethereum._run_ethereum_message_validation(self.address, self.message, self.signature)


signature_timestamp = datetime.datetime.fromisoformat('2022-01-12T08:12:59.787')

ethereum_data = {
    'provider': 'ethereum',
    'provider_details': {
        'signer': '0x854Cc1Ce8e826e514f1dD8127f9D0AF689f181A9',
        'message': '{\r\n\t"message": "Authorize for Drift login",\r\n\t"timestamp": "2022-01-12T08:12:59.787Z"\r\n}',
        'signature': '0x5b0bf23f6cccf4315f561a04aef11b60dadced91bc17ac168db14b467851d4010349a8d3fbaec28c4671eb27ba7a8160900b51c2ded5137b3a9804881f3ee32c1c',
    }
}


class ProviderDetailsTests(BaseAuthTestCase):
    def test_auth(self):
        with mock.patch('driftbase.auth.ethereum.utcnow') as now:
            now.return_value = signature_timestamp + datetime.timedelta(seconds=5)
            with mock.patch('driftbase.auth.ethereum.get_provider_config') as config:
                config.return_value = dict()
                user1 = self._auth_and_get_user(ethereum_data)
                user2 = self._auth_and_get_user(ethereum_data)
                assert user1['provider_user_id'] == user2['provider_user_id']
                assert user1['identity_id'] == user2['identity_id']
                assert user1['user_id'] == user2['user_id']

    def test_ethereum_address_in_returned_payload(self):
        with (mock.patch('driftbase.auth.ethereum.utcnow') as now):
            now.return_value = signature_timestamp + datetime.timedelta(seconds=5)
            with mock.patch('driftbase.auth.ethereum.get_provider_config') as config:
                config.return_value = dict()
                user = self._auth_and_get_user(ethereum_data)
                assert "provider_user_id" in user
                assert user['provider_user_id'] == f"{ethereum_data['provider']}:" + \
                       f"{ethereum_data['provider_details']['signer'].lower()}"


class TestEthereumEIP4361RunAuthentication(unittest.TestCase):
    def setUp(self):
        self.address = '0xa0940d9ca3974455c5b6920e49b20eb464fc982e'
        self.message = "localhost wants you to sign in with your Ethereum account:\n0xa0940d9CA3974455C5B6920E49b20EB464Fc982e\n\nI accept the dApp's Terms of Service: https://themachinesarena.com/terms-and-conditions\n\nURI: http://localhost:3000\nVersion: 1\nChain ID: 2020\nNonce: 12345678\nIssued At: 2024-01-27T09:11:40.366Z\nExpiration Time: 2024-01-28T09:11:40.365Z"
        self.signature = '0x03227ee89a406ec44bdfb21cf77550a0e40ec9da69f77d130e6b8b7116cbf21f35b13c9884e62362fb90c6d97e8361f7bafd091d44f7b16079e3476740dee5331c'
        self.timestamp = datetime.datetime.fromisoformat('2024-01-27T09:11:40.366')

    def test_authenticates_when_signature_matches(self):
        with mock.patch('driftbase.auth.ethereum.utcnow') as now:
            now.return_value = self.timestamp + datetime.timedelta(seconds=5)
            self.assertEqual(self.address.lower(),
                             ethereum._run_ethereum_message_validation(self.address, self.message, self.signature))

    def test_fails_when_account_does_not_match_signature(self):
        with mock.patch('driftbase.auth.ethereum.utcnow') as now:
            now.return_value = self.timestamp + datetime.timedelta(seconds=5)
            with self.assertRaises(UnauthorizedException):
                signature = self.signature.replace('0x03', '0x06')
                ethereum._run_ethereum_message_validation(self.address, self.message, signature)

