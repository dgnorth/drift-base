from drift.systesthelper import DriftTestCase


class DriftTestCase(DriftTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Override unit test auth provider, as we rely on auth potentially creating actual users
        cls.auth_provider = 'user+pass'
