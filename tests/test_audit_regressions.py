"""Regressions reproduced while reviewing mobile release readiness."""

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from browser_agent.agent import RetrievalAgent
from browser_agent.errors import InteractionSafetyError
from browser_agent.interaction import InteractionSafetyValidator
from browser_agent.safety import registrable_domain, validate_public_url
from tests.test_interaction_safety import _store, _observation, _fill


class AuditRegressions(unittest.TestCase):
    def test_other_hosting_tenant_cannot_receive_credentials(self):
        destination = validate_public_url("https://unrelated.github.io/login", resolve_dns=False)
        with patch("browser_agent.interaction.validate_public_url", return_value=destination):
            with self.assertRaises(InteractionSafetyError):
                InteractionSafetyValidator(_store()).validate_fill(
                    _fill(), _observation(form_domain=destination.domain),
                    current_url=destination.url,
                    trusted_domains={registrable_domain("hospital.github.io")},
                )

    def test_unknown_report_date_prevents_automatic_latest_selection(self):
        dated = SimpleNamespace(element_id="dated", report_date=date(2026, 1, 1))
        unknown = SimpleNamespace(element_id="unknown", report_date=None)
        self.assertIsNone(RetrievalAgent._unique_latest([dated, unknown]))
        tied = SimpleNamespace(element_id="tied", report_date=dated.report_date)
        self.assertEqual(RetrievalAgent._tied_latest([dated, tied, unknown]), [])
        self.assertEqual(RetrievalAgent._tied_latest([dated, tied]), [dated, tied])
