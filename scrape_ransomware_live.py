"""Download the ransomware.live /nego HTML and extract negotiation links.

Run: python scrape_ransomware_live.py --output ransomware_live.html
Use saved HTML: python scrape_ransomware_live.py --input ransomware_live.html
Install dependencies: python -m pip install -r requirements.txt
Fetches one page, not linked pages. Writes one absolute negotiation URL per line
to negotiation_links.txt, preserving page order and repeated links.
"""

import argparse
import math
import ssl
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

import certifi


URL = "https://www.ransomware.live/nego"


class NegotiationLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        link = urljoin(URL, href)
        parsed = urlsplit(link)
        segments = parsed.path.strip("/").split("/")
        if (
            parsed.scheme == "https"
            and parsed.netloc == urlsplit(URL).netloc
            and len(segments) == 3
            and segments[0] == "nego"
            and all(segments)
        ):
            self.links.append(link)


def extract_negotiation_links(html: bytes) -> list[str]:
    parser = NegotiationLinkParser()
    parser.feed(html.decode("utf-8"))
    parser.close()
    if not parser.links:
        raise ValueError("no negotiation links found in the HTML")
    return parser.links


def positive_timeout(value: str) -> float:
    """Parse a finite, positive timeout in seconds."""
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise argparse.ArgumentTypeError("timeout must be finite and greater than zero")
    return timeout


def fetch_html(timeout: float, url: str = URL) -> bytes:
    """Fetch the original HTML bytes, preserving the server's encoding."""
    request = Request(
        url,
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
        "--input", type=Path,
        help="extract links from saved UTF-8 HTML instead of downloading",
    )
    parser.add_argument(
        "--links-output", type=Path, default=Path("negotiation_links.txt"),
        help="links destination (default: negotiation_links.txt; overwrites if present)",
    )
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
        html = args.input.read_bytes() if args.input else fetch_html(args.timeout)
        links = extract_negotiation_links(html)
        if not args.input:
            args.output.write_bytes(html)
        args.links_output.write_text("\n".join(links) + "\n", encoding="utf-8")
    except (URLError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not args.input:
        print(f"Saved {len(html):,} bytes from {URL} to {args.output.resolve()}")
    print(
        f"Saved {len(links)} negotiation links ({len(set(links))} unique) "
        f"to {args.links_output.resolve()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
