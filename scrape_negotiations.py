"""Export negotiation messages to CSV, caching pages for resumable runs.

Run: python scrape_negotiations.py
Reads negotiation_links.txt; writes one CSV per negotiation in negotiation_csvs/
and negotiation_scrape_report.json. Duplicate URLs are fetched only once.
Uses four workers with request starts globally separated by five seconds.
Timestamps are kept as displayed, without assuming a timezone.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from http.client import HTTPException
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlsplit

from bs4 import BeautifulSoup

from scrape_ransomware_live import fetch_html, positive_timeout


FIELDS = [
    "negotiation_url", "group", "negotiation_id", "message_index",
    "party", "message", "timestamp",
]


class RequestLimiter:
    def __init__(self) -> None:
        self.lock = Lock()
        self.next_request = 0.0

    def wait(self) -> None:
        with self.lock:
            time.sleep(max(0.0, self.next_request - time.monotonic()))
            self.next_request = time.monotonic() + 5.0


def worker_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("workers must be an integer from 1 to 16") from exc
    if not 1 <= count <= 16:
        raise argparse.ArgumentTypeError("workers must be an integer from 1 to 16")
    return count


def cache_path(directory: Path, url: str) -> Path:
    return directory / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".html")


def csv_path(directory: Path, url: str) -> Path:
    parts = urlsplit(url).path.strip("/").split("/")
    name = "__".join(
        re.sub(r"[^A-Za-z0-9._-]", "_", unquote(part))[:80]
        for part in parts[1:]
    )
    suffix = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return directory / f"{name}__{suffix}.csv"


def extract_messages(html: bytes, url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    bubbles = soup.select(".chat-window .bubble")
    if not bubbles:
        raise ValueError(f"no message bubbles found: {url}")
    parts = urlsplit(url).path.strip("/").split("/")
    rows = []
    for index, bubble in enumerate(bubbles, 1):
        classes = bubble.get("class", [])
        if "victim" in classes:
            party = "victim"
        elif "gang" in classes:
            party = "gang"
        else:
            raise ValueError(f"unknown party in message {index}: {url}")
        timestamp = ""
        timestamps = bubble.select(".ts")
        if len(timestamps) > 1:
            raise ValueError(f"multiple timestamps in message {index}: {url}")
        if timestamps:
            timestamp = timestamps[0].get_text(" ", strip=True)
            timestamps[0].decompose()
        for br in bubble.find_all("br"):
            br.replace_with("\n")
        message = bubble.get_text().strip()
        rows.append({
            "negotiation_url": url,
            "group": unquote(parts[1]),
            "negotiation_id": unquote(parts[2]),
            "message_index": str(index),
            "party": party,
            "message": message,
            "timestamp": timestamp,
        })
    empty_count = sum(not row["message"] for row in rows)
    if empty_count:
        print(
            f"Warning: {url} contains {empty_count} message bubbles with no text; "
            "preserving those rows with an empty message field.",
            file=sys.stderr, flush=True,
        )
    return rows


def read_urls(path: Path) -> list[str]:
    urls = list(dict.fromkeys(
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ))
    if not urls:
        raise ValueError("the links file is empty")
    for url in urls:
        parsed = urlsplit(url)
        parts = parsed.path.strip("/").split("/")
        if not (
            parsed.scheme == "https"
            and parsed.netloc == "www.ransomware.live"
            and len(parts) == 3 and parts[0] == "nego" and all(parts)
            and not parsed.query and not parsed.fragment
        ):
            raise ValueError(f"invalid negotiation URL: {url}")
    return urls


def export_negotiation(
    url: str, cache: Path, output_dir: Path, timeout: float, limiter: RequestLimiter,
) -> int:
    page = cache_path(cache, url)
    destination = csv_path(output_dir, url)
    if page.exists():
        html = page.read_bytes()
    else:
        for attempt in range(1, 4):
            limiter.wait()
            try:
                html = fetch_html(timeout, quote(url, safe=":/%"))
                break
            except (URLError, OSError, HTTPException) as exc:
                retryable = (
                    not isinstance(exc, HTTPError)
                    or exc.code == 429 or exc.code >= 500
                )
                if attempt == 3 or not retryable:
                    raise
                print(
                    f"Retry {attempt}/3 for {url}: {exc}",
                    file=sys.stderr, flush=True,
                )
                time.sleep(5.0 * attempt)
        page.write_bytes(html)
    rows = extract_messages(html, url)
    temporary = destination.with_suffix(".csv.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(destination)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--links", type=Path, default=Path("negotiation_links.txt"))
    parser.add_argument("--output-dir", type=Path, default=Path("negotiation_csvs"))
    parser.add_argument("--cache", type=Path, default=Path("negotiation_pages"))
    parser.add_argument(
        "--report", type=Path, default=Path("negotiation_scrape_report.json"),
    )
    parser.add_argument("--timeout", type=positive_timeout, default=120.0)
    parser.add_argument(
        "--workers", type=worker_count, default=4,
        help="concurrent workers, 1-16 (default: 4); global five-second request spacing",
    )
    args = parser.parse_args()

    try:
        urls = read_urls(args.links)
        if args.report.resolve() == args.links.resolve():
            raise ValueError("links and report must be different files")
        args.cache.mkdir(parents=True, exist_ok=True)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        results: list[dict[str, str | int]] = []
        total_messages = 0
        limiter = RequestLimiter()
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    export_negotiation, url, args.cache, args.output_dir,
                    args.timeout, limiter,
                ): url
                for url in urls
            }
            for number, future in enumerate(as_completed(futures), 1):
                url = futures[future]
                destination = csv_path(args.output_dir, url)
                try:
                    count = future.result()
                except (URLError, OSError, HTTPException, ValueError) as exc:
                    print(f"[{number}/{len(urls)}] ERROR {url}: {exc}", file=sys.stderr, flush=True)
                    results.append({"url": url, "status": "error", "error": str(exc)})
                else:
                    total_messages += count
                    results.append({
                        "url": url, "status": "ok", "messages": count,
                        "csv": str(destination),
                    })
                    print(
                        f"[{number}/{len(urls)}] {count} messages: {destination}",
                        flush=True,
                    )
                failed = sum(item["status"] == "error" for item in results)
                report = {
                    "total_negotiations": len(urls),
                    "processed": len(results),
                    "successful": len(results) - failed,
                    "failed": failed,
                    "messages": total_messages,
                    "complete": len(results) == len(urls) and failed == 0,
                    "results": results,
                }
                temporary_report = args.report.with_suffix(args.report.suffix + ".tmp")
                temporary_report.write_text(
                    json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                temporary_report.replace(args.report)
        print(
            f"Exported {total_messages} messages from {len(urls) - failed}/{len(urls)} "
            f"negotiations to {args.output_dir}/. Failures: {failed}.",
            flush=True,
        )
        return 1 if failed else 0
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
