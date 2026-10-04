"""Opt-in real Chromium test, with an entirely intercepted synthetic lab portal.

Run: python -m tests.synthetic_browser_e2e [--gemini]
The Gemini variant sends only generated test data to the configured provider.
No real lab website is visited and no patient record is accessed.
"""

import argparse
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

from PIL import Image, ImageDraw, ImageFont

from browser_agent.agent import RetrievalAgent
from browser_agent.download_manager import ReportDownloadManager
from browser_agent.interaction import ControlledBrowserTools
from browser_agent.session import BrowserSession, BrowserSessionConfig
from config.settings import get_settings
from document_understanding.models import DocumentUnderstandingResult
from document_understanding.provider import create_document_provider
from document_understanding.service import DocumentUnderstandingService
from services.models import RetrievalOutcomeStatus
from services.report_retrieval import ReportRetrievalService

PORTAL = "https://example.com/lab-test"
PDF = b"%PDF-1.4\n%LATEST SYNTHETIC REPORT\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"


class SyntheticProvider:
    def analyze_document(self, _path):
        return DocumentUnderstandingResult.model_validate({
            "analysis_status": "usable", "document_type": "laboratory slip",
            "document_type_confidence": "high", "organization": {
                "name": "Example Diagnostic Lab", "type": "laboratory", "confidence": "high",
            },
            "purpose": "Report retrieval", "likely_action": "Retrieve lab report",
            "urls": [{"url": PORTAL, "normalized_url": PORTAL, "context": "Report portal",
                      "likely_purpose": "report_portal", "confidence": "high"}],
            "qr_codes": [], "dates": [], "instructions": [], "warnings": [],
            "raw_summary": "Synthetic laboratory registration slip", "overall_confidence": "high",
            "fields": [
                {"label": "Patient ID", "value": "TEST-48291", "semantic_type": "patient_identifier", "confidence": "high"},
                {"label": "Access Code", "value": "736204", "semantic_type": "access_credential", "confidence": "high"},
            ],
        })


class SyntheticPortal(BrowserSession):
    def __init__(self):
        super().__init__(BrowserSessionConfig(timeout_seconds=8, navigation_timeout_seconds=8))
        self.auth_count = 0
        self.downloads = []

    def start(self):
        super().start()
        # This fixture route never reaches the network, including unexpected URLs.
        self.page.route("**/*", self._fixture)

    def _fixture(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method == "POST" and path == "/lab-test/login":
            self.auth_count += 1
            fields = parse_qs(request.post_data or "")
            if fields != {"patient": ["TEST-48291"], "accesscode": ["736204"]}:
                route.fulfill(status=403, content_type="text/html", body="Invalid credentials")
                return
            route.fulfill(content_type="text/html", body='''<!doctype html><title>Lab Reports</title>
                <h1>Laboratory reports</h1><table><thead><tr><th>Test</th><th>Report date</th><th>Report</th></tr></thead><tbody>
                <tr><td>Older blood test</td><td>2026-01-01</td><td><button onclick="location.href='/lab-test/older-file'">Download report</button></td></tr>
                <tr><td>Latest blood test</td><td>2026-10-04</td><td><button onclick="location.href='/lab-test/latest-file'">Download report</button></td></tr>
                </tbody></table>''')
        elif path.endswith("-file"):
            self.downloads.append(path)
            route.fulfill(content_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="report.pdf"'}, body=PDF)
        elif request.method == "GET" and path == "/lab-test":
            route.fulfill(content_type="text/html", body='''<!doctype html><title>Online Lab Reports</title>
                <h1>Online Lab Reports</h1><form method="post" action="/lab-test/login">
                <label for="patient">Patient ID</label><input id="patient" name="patient" required>
                <label for="accesscode">Access Code</label><input id="accesscode" name="accesscode" type="password" required>
                <button type="submit">View Reports</button></form>''')
        else:
            route.abort()


def run(use_gemini: bool):
    with TemporaryDirectory(prefix="slip-e2e-") as folder:
        settings = replace(get_settings(), temp_dir=Path(folder))
        image = Image.new("RGB", (1500, 900), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default(size=40)
        draw.multiline_text((60, 60),
            "EXAMPLE DIAGNOSTIC LAB\nLABORATORY REGISTRATION SLIP\nPatient ID: TEST-48291\n"
            f"Access Code: 736204\nReport portal: {PORTAL}\nCollection date: 04 October 2026\n"
            "Use patient ID and access code to view your report.", font=font, fill="black", spacing=25)
        path = Path(folder) / "synthetic.png"
        image.save(path)
        session = SyntheticPortal()
        agent = RetrievalAgent(lambda store: ControlledBrowserTools(session, store, ReportDownloadManager(Path(folder))))
        provider = create_document_provider(settings) if use_gemini else SyntheticProvider()
        service = ReportRetrievalService(settings, document_service=DocumentUnderstandingService(provider), retrieval_agent=agent)
        outcome = service.retrieve(path)
        assert outcome.status == RetrievalOutcomeStatus.COMPLETED, f"Retrieval status: {outcome.status.value}"
        assert session.auth_count == 1, "Authentication was not submitted exactly once"
        assert session.downloads == ["/lab-test/latest-file"], "Latest dated report was not selected"
        assert len(outcome.reports) == 1 and outcome.reports[0].path.read_bytes() == PDF
        print(f"Synthetic E2E passed: {'live Gemini' if use_gemini else 'fixture OCR'}, real Chromium, one login, latest PDF validated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gemini", action="store_true")
    run(parser.parse_args().gemini)
