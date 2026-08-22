# noise-fix-verify-2026-08-22
import html
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import feedparser

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import get_client

_WORD = r"(?:[ァ-ヶー]{2,}|[A-Za-z]{2,})"
_AWORD = rf"(?>{_WORD})"
_CONTEXT_WORD = r"[A-Za-z]{2,}"
_ACONTEXT_WORD = rf"(?>{_CONTEXT_WORD})"
_SEP = r"[\s「」『』【】]+"
_CORE_STD = rf"{_AWORD}\s?\d{{1,4}}"
_CORE_SHORT = r"[A-Za-z]\d{1,4}"

UNREGISTERED_PATTERN = re.compile(
    rf"(?:{_ACONTEXT_WORD}{_SEP}){{1,2}}{_CORE_SHORT}(?:{_SEP}{_ACONTEXT_WORD}){{0,2}}"
    rf"|(?:{_ACONTEXT_WORD}{_SEP}){{0,2}}{_CORE_STD}(?:{_SEP}{_ACONTEXT_WORD}){{0,2}}"
)
URL_PATTERN = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
TRADEMARK_PATTERN = re.compile(r"[®™©]")


def build_brand_patterns(brands):
    patterns = []
    for brand in brands:
        pattern = re.compile(
            rf"\b{re.escape(brand['name'])}\b(?:{_SEP}{_ACONTEXT_WORD}){{1,4}}(?!{_SEP}?[A-Za-z]?\d)",
            re.IGNORECASE,
        )
        patterns.append((pattern, brand.get("category_id")))
    return patterns


def strip_noise(text):
    text = URL_PATTERN.sub(" ", text)
    text = HTML_TAG_PATTERN.sub(" ", text)
    text = TRADEMARK_PATTERN.sub("", text)
    return html.unescape(text)


def normalize_text(text):
    return unicodedata.normalize("NFKC", text)


def canonicalize_keyword(raw_keyword):
    text = re.sub(r"[「」『』【】]", " ", raw_keyword)
    text = re.sub(r"\s+", " ", text).strip().upper()
    return re.sub(r"(?<=[A-Zァ-ヶー])\s+(?=\d)", "", text)


def build_regex_pattern(keyword):
    parts = []
    for segment in keyword.split(" "):
        match = re.match(r"^(\D+)(\d+)$", segment)
        if match:
            prefix, digits = match.groups()
            parts.append(re.escape(prefix) + r"\s*" + re.escape(digits))
        else:
            parts.append(re.escape(segment))
    return r"\s+".join(parts)


def fetch_active_sources(client):
    res = client.table("sources").select("id, rss_url").eq("is_active", True).execute()
    return res.data or []


def fetch_source_by_id(client, source_id):
    res = client.table("sources").select("id, rss_url").eq("id", source_id).execute()
    return res.data or []


def get_entry_id(entry):
    return entry.get("id") or entry.get("link") or entry.get("title", "")


def fetch_processed_entry_ids(client, source_id):
    res = (
        client.table("processed_entries")
        .select("entry_id")
        .eq("source_id", source_id)
        .execute()
    )
    return {row["entry_id"] for row in (res.data or [])}


def mark_entries_processed(client, source_id, entry_ids):
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"source_id": source_id, "entry_id": entry_id, "processed_at": now}
        for entry_id in entry_ids
    ]
    if rows:
        client.table("processed_entries").insert(rows).execute()


def collect_texts(client, sources):
    texts = []
    for src in sources:
        feed = feedparser.parse(src["rss_url"])
        processed_ids = fetch_processed_entry_ids(client, src["id"])
        new_ids = []
        for entry in feed.entries:
            entry_id = get_entry_id(entry)
            if entry_id in processed_ids:
                continue
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            texts.append(normalize_text(strip_noise(f"{title} {summary}")))
            new_ids.append(entry_id)
        mark_entries_processed(client, src["id"], new_ids)
    return texts


def count_product_mentions(texts, products):
    counts = defaultdict(int)
    for product in products:
        pattern = re.compile(product["regex_pattern"], re.IGNORECASE)
        for text in texts:
            counts[product["id"]] += len(pattern.findall(text))
    return counts


def upsert_daily_buzz(client, counts):
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat()
    for product_id, count in counts.items():
        if count == 0:
            continue
        existing = (
            client.table("daily_buzz_logs")
            .select("id, count")
            .eq("product_id", product_id)
            .eq("logged_at", today)
            .execute()
        )
        if existing.data:
            row = existing.data[0]
            client.table("daily_buzz_logs").update(
                {"count": row["count"] + count, "updated_at": now}
            ).eq("id", row["id"]).execute()
        else:
            client.table("daily_buzz_logs").insert(
                {"product_id": product_id, "logged_at": today, "count": count, "updated_at": now}
            ).execute()


def split_brand_prefix(keyword, brands):
    """If keyword starts with a known brand followed by a separate model
    name, strip the brand so the same model is recognized as one product
    regardless of whether the brand was mentioned in a given article.
    A brand fused directly with a number (e.g. "SUUNTO9") is left as-is,
    since the number IS the product line there, not a separate model name.
    """
    for brand in brands:
        brand_name = canonicalize_keyword(brand["name"])
        if keyword == brand_name:
            return keyword, brand.get("category_id")
        if keyword.startswith(brand_name + " "):
            remainder = keyword[len(brand_name) :].strip()
            if remainder and not remainder[0].isdigit():
                return remainder, brand.get("category_id")
            return keyword, brand.get("category_id")
        if keyword.startswith(brand_name) and keyword[len(brand_name) : len(brand_name) + 1].isdigit():
            return keyword, brand.get("category_id")
    return keyword, None


def extract_unregistered_keywords(texts, products, blacklist, brands=None):
    brands = brands or []
    registered_patterns = [re.compile(p["regex_pattern"], re.IGNORECASE) for p in products]
    blacklist_set = {canonicalize_keyword(normalize_text(word)) for word in blacklist}
    brand_patterns = [pattern for pattern, _ in build_brand_patterns(brands)]
    patterns = [UNREGISTERED_PATTERN] + brand_patterns

    found = {}
    for text in texts:
        for pattern in patterns:
            for match in pattern.finditer(text):
                raw_keyword = canonicalize_keyword(match.group())
                keyword, brand_category_id = split_brand_prefix(raw_keyword, brands)
                if keyword in blacklist_set:
                    continue
                if any(p.search(keyword) for p in registered_patterns):
                    continue
                if keyword not in found:
                    start = max(match.start() - 20, 0)
                    end = min(match.end() + 20, len(text))
                    found[keyword] = {
                        "context": text[start:end],
                        "brand_category_id": brand_category_id,
                    }
                elif brand_category_id is not None and found[keyword]["brand_category_id"] is None:
                    found[keyword]["brand_category_id"] = brand_category_id
    return found


def predict_category(brand_category_id, context, categories):
    if brand_category_id is not None:
        return brand_category_id
    for category in categories:
        for seed in category.get("seed_keywords") or []:
            if seed and seed in context:
                return category["id"]
    return None


def upsert_unregistered_keywords(client, keyword_contexts, categories):
    now = datetime.now(timezone.utc).isoformat()
    for keyword, info in keyword_contexts.items():
        context = info["context"]
        predicted_category_id = predict_category(info["brand_category_id"], context, categories)
        existing = (
            client.table("unregistered_keywords")
            .select("id, count")
            .eq("keyword", keyword)
            .execute()
        )
        if existing.data:
            row = existing.data[0]
            client.table("unregistered_keywords").update(
                {
                    "count": row["count"] + 1,
                    "sample_context": context,
                    "predicted_category_id": predicted_category_id,
                    "updated_at": now,
                }
            ).eq("id", row["id"]).execute()
        else:
            client.table("unregistered_keywords").insert(
                {
                    "keyword": keyword,
                    "predicted_category_id": predicted_category_id,
                    "count": 1,
                    "sample_context": context,
                    "updated_at": now,
                }
            ).execute()


def run(source_id=None):
    client = get_client()

    sources = fetch_source_by_id(client, source_id) if source_id is not None else fetch_active_sources(client)
    products = client.table("products").select("id, regex_pattern").execute().data or []
    categories = client.table("categories").select("id, seed_keywords").execute().data or []
    blacklist = [
        row["keyword"] for row in (client.table("blacklist").select("keyword").execute().data or [])
    ]
    brands = client.table("brands").select("name, category_id").execute().data or []

    texts = collect_texts(client, sources)

    counts = count_product_mentions(texts, products)
    upsert_daily_buzz(client, counts)

    keyword_contexts = extract_unregistered_keywords(texts, products, blacklist, brands)
    upsert_unregistered_keywords(client, keyword_contexts, categories)

    return texts


if __name__ == "__main__":
    run()
