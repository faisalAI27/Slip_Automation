"""Create and describe report artifacts independently of the UI."""

from pathlib import Path
import uuid


MOCK_REPORT_CONTENT = """DEMO REPORT — INTERFACE TEST ONLY

No hospital or laboratory service was contacted.
No medical document was interpreted.
No real report was retrieved.

This file only confirms that the Step 1 upload, workflow, and download interface is working.
"""


def create_mock_report(temp_dir: Path) -> Path:
    temp_dir.mkdir(parents=True, exist_ok=True)
    result_path = temp_dir / f"demo-report-{uuid.uuid4().hex}.txt"
    result_path.write_text(MOCK_REPORT_CONTENT, encoding="utf-8")
    return result_path
