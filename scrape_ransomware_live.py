"""Download the ransomware.live homepage HTML without rendering JavaScript.

Run: python scrape_ransomware_live.py --output ransomware_live.html
Install dependencies: python -m pip install -r requirements.txt
Fetches one page, not linked pages.
"""

import argparse
import math
import ssl
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import certifi


URL = "https://www.ransomware.live/"


def positive_timeout(value: str) -> float:
    """Parse a finite, positive timeout in seconds."""
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and greater than zero")
    return timeout


def fetch_html(timeout: float) -> bytes:
    """Fetch the original HTML bytes, preserving the server's encoding."""
    request = Request(
        URL,
        headers={
            "User-Agent": "ransomware-live-project/1.0 (single-page HTML downloader)",
            "Accept": "text/html, application/xhtml+xml",
        },
    )
    context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(request, timeout=timeout, context=context) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError(f"expected HTML, received {content_type}")
        html = response.read()
        if not html.strip():
            raise ValueError("the server returned an empty HTML response")
        return html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("ransomware_live.html"),
        help="destination file (default: ransomware_live.html; overwrites if present)",
    )
    parser.add_argument(
        "--timeout", type=positive_timeout, default=30.0,
        help="network timeout in seconds (default: 30)",
    )
    args = parser.parse_args()

    try:
        html = fetch_html(args.timeout)
        args.output.write_bytes(html)
    except (URLError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Saved {len(html):,} bytes from {URL} to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
