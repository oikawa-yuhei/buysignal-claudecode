import re
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import feedparser

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import get_client

UNREGISTERED_PATTERN = re.compile(r"[ァ-ヶー]{2,}\d{1,4}|[A-Za-z]{2,}\d{1,4}")


def fetch_active_sources(client):
    res = client.table("sources").select("id, rss_url").eq("is_active", True).execute()
    return res.data or []


def collect_texts(sources):
    texts = []
    for src in sources:
        feed = feedparser.parse(src["rss_url"])
        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            texts.append(f"{title} {summary}")
    return texts


def count_product_mentions(texts, products):
    counts = defaultdict(int)
    for product in products:
        pattern = re.compile(product["regex_pattern"])
        for text in texts:
            counts[product["id"]] += len(pattern.findall(text))
    return counts


def upsert_daily_buzz(client, counts):
    today = date.today().isoformat()
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
            client.table("daily_buzz_logs").update({"count": row["count"] + count}).eq(
                "id", row["id"]
            ).execute()
        else:
            client.table("daily_buzz_logs").insert(
                {"product_id": product_id, "logged_at": today, "count": count}
            ).execute()


def extract_unregistered_keywords(texts, products, blacklist):
    registered_patterns = [re.compile(p["regex_pattern"]) for p in products]
    blacklist_set = set(blacklist)

    found = {}
    for text in texts:
        for match in UNREGISTERED_PATTERN.finditer(text):
            keyword = match.group()
            if keyword in blacklist_set:
                continue
            if any(p.search(keyword) for p in registered_patterns):
                continue
            if keyword not in found:
                start = max(match.start() - 20, 0)
                end = min(match.end() + 20, len(text))
                found[keyword] = text[start:end]
    return found


def predict_category(context, categories):
    for category in categories:
        for seed in category.get("seed_keywords") or []:
            if seed and seed in context:
                return category["id"]
    return None


def upsert_unregistered_keywords(client, keyword_contexts, categories):
    now = datetime.now(timezone.utc).isoformat()
    for keyword, context in keyword_contexts.items():
        predicted_category_id = predict_category(context, categories)
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


def run():
    client = get_client()

    sources = fetch_active_sources(client)
    products = client.table("products").select("id, regex_pattern").execute().data or []
    categories = client.table("categories").select("id, seed_keywords").execute().data or []
    blacklist = [
        row["keyword"] for row in (client.table("blacklist").select("keyword").execute().data or [])
    ]

    texts = collect_texts(sources)

    counts = count_product_mentions(texts, products)
    upsert_daily_buzz(client, counts)

    keyword_contexts = extract_unregistered_keywords(texts, products, blacklist)
    upsert_unregistered_keywords(client, keyword_contexts, categories)


if __name__ == "__main__":
    run()
