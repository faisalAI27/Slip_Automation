#!/usr/bin/env python3
"""Convert a Firebase Android app config into ignored Flutter build defines."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit


def build_defines(config: dict, api_url: str) -> dict[str, str]:
    url = urlsplit(api_url)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError(
            "Use the absolute HTTPS Cloud Run URL without query or credentials."
        )
    client = next(
        (
            item
            for item in config.get("client", [])
            if item.get("client_info", {})
            .get("android_client_info", {})
            .get("package_name")
            == "com.slipautomation.reportapp"
        ),
        None,
    )
    if client is None:
        raise ValueError(
            "Firebase must contain the Android app com.slipautomation.reportapp."
        )
    project = config["project_info"]
    result = {
        "API_BASE_URL": api_url.rstrip("/"),
        "API_EXECUTION_MODE": "synchronous",
        "API_AUTH_MODE": "firebase",
        "FIREBASE_PROJECT_ID": project["project_id"],
        "FIREBASE_MESSAGING_SENDER_ID": str(project["project_number"]),
        "FIREBASE_APP_ID": client["client_info"]["mobilesdk_app_id"],
        "FIREBASE_API_KEY": client["api_key"][0]["current_key"],
    }
    if not all(isinstance(value, str) and value for value in result.values()):
        raise ValueError("Firebase Android configuration is incomplete.")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Downloaded google-services.json (not a service-account key)",
    )
    parser.add_argument("--api-url", required=True)
    parser.add_argument(
        "--output", type=Path, default=Path(".env.firebase-defines.json")
    )
    args = parser.parse_args()
    try:
        result = build_defines(json.loads(args.config.read_text()), args.api_url)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        args.output.chmod(0o600)
    except (ValueError, KeyError, IndexError, OSError) as exc:
        parser.exit(
            1,
            f"Configuration could not be generated: {type(exc).__name__}. Check the Android app config and HTTPS URL.\n",
        )
    print(
        f"Wrote Flutter pilot defines to {args.output}. Keep this generated file out of Git."
    )
