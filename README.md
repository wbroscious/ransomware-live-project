# Ransomware.live negotiation export

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python scrape_ransomware_live.py --timeout 120
python scrape_negotiations.py
```

To reuse the saved index instead of downloading it:

```bash
python scrape_ransomware_live.py --input ransomware_live.html
```

The message scraper reads `negotiation_links.txt`, removes duplicate URLs, and
writes one CSV per unique negotiation in `negotiation_csvs/` (configurable with
`--output-dir`). Filenames include the group, negotiation ID, and a URL hash to
avoid collisions. Each row contains `negotiation_url`, `group`,
`negotiation_id`, `message_index` (one-based page order), `party` (`victim` or
`gang`), `message`, and `timestamp`. Timestamps retain the site's display format;
missing timestamps are empty, and no timezone is inferred. CSV quoting preserves
commas, quotes, and embedded message line breaks. Treat scraped message content
as untrusted text, especially when opening it in spreadsheet applications.
Some source pages contain empty message bubbles. These are retained as rows with
empty `message` fields (and their party/timestamp when present), with a warning
logged rather than dropping the message or the entire negotiation.

Pages are cached in `negotiation_pages/`. Re-running the command rebuilds the CSVs
from cached pages and downloads missing pages, without duplicating messages.
Four worker threads overlap slow downloads and process cached pages concurrently.
Use `--workers 1` for sequential execution or `--workers N` (1-16) to change the
pool size. A shared limiter spaces all request starts, including retries, at
least five seconds apart. This replaces the earlier five-second delay after
each response while retaining the site's crawl-delay spacing; more workers do
not increase the request rate. Temporary network errors get up to three attempts.

`negotiation_scrape_report.json` records per-negotiation message counts and errors
after each page. `complete` is true only when every unique URL succeeded; a run
with any failures exits nonzero. Partial CSV output remains available.
