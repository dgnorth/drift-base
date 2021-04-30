import unittest

from driftbase.auth.epic import run_ticket_validation
from driftbase.utils.test_utils import BaseCloudkitTest

class EpicCase(BaseCloudkitTest):

    def test_epic(self):
        account_id = 'babababaaba234234234234234234343'
        auth_info = {
            'provider': 'epic',
            'provider_details':
            {
                'account_id': account_id,
            }
        }

        # Straight call
        epic_id = run_ticket_validation(auth_info['provider_details'])
        self.assertEqual(epic_id, account_id)

        # Auth endpoint call
        ret = self.post('/auth', data=auth_info)
        self.assertIn('token', ret.json())


if __name__ == "__main__":
    import logging
    logging.basicConfig(level='INFO')
    unittest.main()
