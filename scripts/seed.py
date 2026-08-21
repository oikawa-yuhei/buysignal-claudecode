import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import get_client


def seed_categories(client):
    categories = [
        {
            "name": "running_shoes",
            "seed_keywords": ["ランニングシューズ", "厚底", "ソール", "マラソン"],
            "icon": "👟",
        },
        {
            "name": "fitness_gear",
            "seed_keywords": ["筋トレ", "ダンベル", "プロテイン", "トレーニング"],
            "icon": "🏋️",
        },
    ]
    for category in categories:
        existing = client.table("categories").select("id").eq("name", category["name"]).execute()
        if not existing.data:
            client.table("categories").insert(category).execute()


def seed_sources(client):
    categories = client.table("categories").select("id, name").execute().data or []
    category_id_by_name = {c["name"]: c["id"] for c in categories}

    sources = [
        {
            "name": "ケータイ Watch",
            "rss_url": "https://k-tai.watch.impress.co.jp/data/rss/1.0/ktw/feed.rdf",
            "category_id": category_id_by_name.get("fitness_gear"),
        },
        {
            "name": "GIGAZINE",
            "rss_url": "https://gigazine.net/news/rss_2.0/",
            "category_id": category_id_by_name.get("running_shoes"),
        },
    ]
    for source in sources:
        existing = client.table("sources").select("id").eq("rss_url", source["rss_url"]).execute()
        if not existing.data:
            client.table("sources").insert({**source, "is_active": True}).execute()


def run():
    client = get_client()
    seed_categories(client)
    seed_sources(client)


if __name__ == "__main__":
    run()
