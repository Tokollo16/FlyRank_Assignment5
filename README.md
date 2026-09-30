# The Polite Scraper

A small Python scraping pipeline for the Books to Scrape practice sandbox. It fetches the first three catalogue pages, discovers their 60 book URLs, caches HTML, extracts raw fields, normalizes prices, validates records, and writes an honest run report.

## Run it

Requires Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=. python3 scraper/src/main.py
```

The first run makes the live requests. Later development runs use `scraper/cache/` and do not request cached pages again. Outputs are written to `output/books.json`, `output/errors.json`, and `output/run-report.json`.

To prove the failure path without harming the sandbox:

```bash
PYTHONPATH=. python3 scraper/src/main.py --include-fake
```

## Target classification

- **Target:** `https://books.toscrape.com/`, a public sandbox made for practising scraping.
- **Scope:** only catalogue pages 1 through 3, with the 60 book pages linked from them.
- **Collected data:** title, canonical product URL, price and availability text, rating text, description, source catalogue page, fetch time, and numeric GBP price.
- **Robots check:** I requested `https://books.toscrape.com/robots.txt`; it returned HTTP 404, so no robots file was found. A missing file is not treated as permission for another site.
- **Why appropriate:** this target explicitly exists as a scraping practice sandbox and the collection is limited to the assignment's requested catalogue slice.

I will not reuse this code on another site without checking its rules and terms first.

## Record schema

Each validated record contains:

```json
{
  "title": "A Light in the Attic",
  "product_url": "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
  "price_text": "£51.77",
  "availability_text": "In stock (22 available)",
  "rating_text": "Three",
  "description": "...",
  "source_page": "https://books.toscrape.com/catalogue/page-1.html",
  "fetched_at": "2026-10-01T00:00:00Z",
  "price_gbp": 51.77
}
```

`description` is nullable because some pages omit it. URLs are required to be absolute HTTPS URLs, and `price_gbp` must be a non-negative number. Invalid records go to `output/errors.json`, never `books.json`.

## Politeness and failure handling

- Every real request uses an identifying user-agent.
- A 10-second timeout prevents hanging forever.
- Real requests are separated by at least 500 ms.
- Successful HTML is cached and reused during development.
- Timeout and 5xx responses are retried once; 403 and 404 responses are not retried.
- Each book is handled independently, so one broken page does not stop the run.
- Records are keyed by canonical product URL, making reruns idempotent.

## Checks

```bash
PYTHONPATH=. python3 -m pytest -q
```

The parser tests cover price normalization, relative-to-absolute URLs, missing descriptions, duplicate URLs, and malformed input without calling the network.

## Sample run evidence

A successful run should report `catalogue_pages=3`, `discovered=60`, `unique_urls=60`, and `valid_records=60`. The `--include-fake` checkpoint should preserve 60 valid records and report one failed page. The generated `output/run-report.json` is the authoritative timing and count record for the latest local run.

This assignment needs no browser because the book data is already in the HTML sent by the server; a browser would add cost without adding access to the core fields.

## Ethics note

Use an official API when one exists. Never bypass logins, paywalls, or blocks. Collect only the data needed for the stated purpose, identify the client honestly, and keep request volume low.
# FlyRank_Assignment5
