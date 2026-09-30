from datetime import datetime, timezone

import pytest

from scraper.src.main import absolute_url, extract_book_record, extract_catalogue_links, normalize_price


BOOK_HTML = """
<article class="product_page">
  <h1> A Light in the Attic </h1>
  <p class="price_color"> £51.77 </p>
  <p class="availability"> In stock (22 available) </p>
  <p class="star-rating Three"></p>
  <div id="product_description"></div>
  <p> A useful description. </p>
</article>
"""


def test_normalize_price():
    assert normalize_price("£1,251.50") == 1251.50


def test_relative_url_becomes_absolute():
    assert absolute_url("../book/index.html", "https://books.toscrape.com/catalogue/page-1.html") == "https://books.toscrape.com/book/index.html"


def test_extract_record_handles_missing_description():
    record = extract_book_record(BOOK_HTML.replace("<p> A useful description. </p>", ""), "https://books.toscrape.com/book/index.html", "https://books.toscrape.com/catalogue/page-1.html", datetime.now(timezone.utc))
    assert record["description"] is None


def test_duplicate_catalogue_urls_are_removed():
    html = '<article class="product_pod"><h3><a href="../book/index.html">One</a></h3></article><article class="product_pod"><h3><a href="../book/index.html">One again</a></h3></article>'
    assert extract_catalogue_links(html, "https://books.toscrape.com/catalogue/page-1.html") == ["https://books.toscrape.com/book/index.html"]


def test_malformed_fixture_fails_price_normalization():
    with pytest.raises(ValueError):
        normalize_price("price unavailable")
