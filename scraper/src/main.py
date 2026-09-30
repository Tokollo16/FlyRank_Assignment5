from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, field_validator

BASE_URL = "https://books.toscrape.com/"
CATALOGUE_URL = urljoin(BASE_URL, "catalogue/page-1.html")
USER_AGENT = "FlyRankInternship-A9/1.0 (+https://github.com/example/assignment5)"
REQUEST_TIMEOUT_SECONDS = 10
REQUEST_DELAY_SECONDS = 0.5


class BookRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    product_url: HttpUrl
    price_text: str = Field(min_length=1)
    availability_text: str = Field(min_length=1)
    rating_text: str = Field(min_length=1)
    description: str | None
    source_page: HttpUrl
    fetched_at: datetime
    price_gbp: float = Field(ge=0)

    @field_validator("product_url", "source_page")
    @classmethod
    def require_https(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme != "https":
            raise ValueError("URL must use https")
        return value


@dataclass
class RunStats:
    started_at: datetime
    pages_fetched: int = 0
    cache_hits: int = 0
    valid_records: int = 0
    invalid_records: int = 0
    failed_pages: list[dict[str, str]] = field(default_factory=list)
    _last_request_at: float | None = None


class FetchError(RuntimeError):
    def __init__(self, url: str, message: str, status_code: int | None = None):
        super().__init__(message)
        self.url = url
        self.status_code = status_code


def clean_text(value: str | None) -> str:
    return " ".join((value or "").split())


def normalize_price(price_text: str) -> float:
    match = re.search(r"\d+(?:\.\d{1,2})?", price_text.replace(",", ""))
    if not match:
        raise ValueError(f"Could not find a price in {price_text!r}")
    return float(match.group())


def absolute_url(href: str, page_url: str) -> str:
    return urljoin(page_url, href)


def extract_catalogue_links(html: str, page_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for anchor in soup.select("article.product_pod h3 a[href]"):
        links.append(absolute_url(anchor["href"], page_url))
    return list(dict.fromkeys(links))


def next_catalogue_url(html: str, page_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one("li.next a[href]")
    return absolute_url(link["href"], page_url) if link else None


def extract_book_record(html: str, product_url: str, source_page: str, fetched_at: datetime) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    product = soup.select_one("article.product_page")
    if product is None:
        raise ValueError("product area not found")

    title = clean_text(product.select_one("h1").get_text(" ") if product.select_one("h1") else None)
    price_text = clean_text(product.select_one(".price_color").get_text(" ") if product.select_one(".price_color") else None)
    availability_text = clean_text(product.select_one(".availability").get_text(" ") if product.select_one(".availability") else None)
    rating = product.select_one(".star-rating")
    rating_text = " ".join(rating.get("class", [])[1:]) if rating else ""
    description_node = product.select_one("#product_description + p")
    description = clean_text(description_node.get_text(" ")) if description_node else None

    return {
        "title": title,
        "product_url": product_url,
        "price_text": price_text,
        "availability_text": availability_text,
        "rating_text": rating_text,
        "description": description,
        "source_page": source_page,
        "fetched_at": fetched_at,
        "price_gbp": normalize_price(price_text),
    }


class PoliteFetcher:
    def __init__(self, cache_dir: Path, stats: RunStats):
        self.cache_dir = cache_dir
        self.stats = stats
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def _cache_path(self, url: str, name: str | None) -> Path:
        if name:
            return self.cache_dir / name
        digest = hashlib.sha256(url.encode()).hexdigest()[:16]
        return self.cache_dir / f"detail-{digest}.html"

    def get(self, url: str, name: str | None = None) -> tuple[str, bool]:
        path = self._cache_path(url, name)
        if path.exists():
            self.stats.cache_hits += 1
            return path.read_text(encoding="utf-8"), True

        last_error: Exception | None = None
        for attempt in range(2):
            if self.stats._last_request_at is not None:
                elapsed = time.monotonic() - self.stats._last_request_at
                if elapsed < REQUEST_DELAY_SECONDS:
                    time.sleep(REQUEST_DELAY_SECONDS - elapsed)
            self.stats._last_request_at = time.monotonic()
            try:
                response = self.session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
                self.stats.pages_fetched += 1
                if response.status_code == 200:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(response.text, encoding="utf-8")
                    return response.text, False
                error = FetchError(url, f"HTTP {response.status_code}", response.status_code)
                if response.status_code < 500 or attempt == 1:
                    raise error
                last_error = error
            except (requests.RequestException, FetchError) as error:
                last_error = error
                status_code = getattr(error, "status_code", None)
                retryable = isinstance(error, requests.RequestException) or (status_code is not None and status_code >= 500)
                if not retryable or attempt == 1:
                    raise FetchError(url, str(error), status_code) from error
                time.sleep(1)
        raise FetchError(url, str(last_error or "request failed"))


def discover_books(fetcher: PoliteFetcher) -> tuple[list[tuple[str, str]], int]:
    page_url = CATALOGUE_URL
    discovered: list[tuple[str, str]] = []
    catalogue_pages = 0
    while page_url and catalogue_pages < 3:
        cache_name = f"catalogue-page-{catalogue_pages + 1}.html"
        html, _ = fetcher.get(page_url, cache_name)
        discovered.extend((url, page_url) for url in extract_catalogue_links(html, page_url))
        page_url = next_catalogue_url(html, page_url)
        catalogue_pages += 1
    unique: dict[str, str] = {}
    for product_url, source_page in discovered:
        unique.setdefault(product_url, source_page)
    return list(unique.items()), catalogue_pages


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def run(include_fake: bool = False) -> dict[str, Any]:
    started = datetime.now(timezone.utc)
    stats = RunStats(started_at=started)
    root = Path(__file__).resolve().parents[2]
    cache_dir = root / "scraper" / "cache"
    output_dir = root / "output"
    fetcher = PoliteFetcher(cache_dir, stats)
    books: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []

    try:
        targets, catalogue_pages = discover_books(fetcher)
    except FetchError as error:
        targets, catalogue_pages = [], 0
        stats.failed_pages.append({"url": error.url, "reason": str(error)})

    if include_fake:
        targets.append(("https://books.toscrape.com/catalogue/does-not-exist/index.html", CATALOGUE_URL))

    for index, (product_url, source_page) in enumerate(targets, start=1):
        try:
            html, _ = fetcher.get(product_url)
            raw = extract_book_record(html, product_url, source_page, datetime.now(timezone.utc))
            record = BookRecord.model_validate(raw)
            books[str(record.product_url)] = record.model_dump(mode="json")
            stats.valid_records += 1
        except (FetchError, ValidationError, ValueError) as error:
            stats.invalid_records += 1
            reason = str(error)
            errors.append({"url": product_url, "reason": reason})
            if isinstance(error, FetchError):
                stats.failed_pages.append({"url": product_url, "reason": reason})
        if index % 10 == 0 or index == len(targets):
            print(f"processed={index}/{len(targets)}")

    finished = datetime.now(timezone.utc)
    report = {
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
        "catalogue_pages": catalogue_pages,
        "discovered": len(targets) - (1 if include_fake else 0),
        "unique_urls": len({url for url, _ in targets}),
        "pages_fetched": stats.pages_fetched,
        "cache_hits": stats.cache_hits,
        "valid_records": stats.valid_records,
        "invalid_records": stats.invalid_records,
        "failed_pages": len(stats.failed_pages),
        "failures": stats.failed_pages,
    }
    write_json(output_dir / "books.json", list(books.values()))
    write_json(output_dir / "errors.json", errors)
    write_json(output_dir / "run-report.json", report)
    print(json.dumps({key: report[key] for key in ("catalogue_pages", "discovered", "unique_urls", "valid_records", "failed_pages")}, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Polite Books to Scrape pipeline")
    parser.add_argument("--include-fake", action="store_true", help="add one local failure case for the Stage 5 checkpoint")
    args = parser.parse_args()
    run(include_fake=args.include_fake)


if __name__ == "__main__":
    main()
