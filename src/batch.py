# noise-fix-verify-2026-08-22
import html
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.config import get_client, get_youtube_api_key

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

_STOPWORDS = (
    r"(?:VS|AND|OR|THE|FOR|ARE|HAS|HAVE|HAD|ON|TOO|IN|AT|IS|OF|TO|BY|AN|A|GOES|WITH"
    r"|THIS|THAT|THESE|THOSE|WAS|WERE|NOW|UP|ALL|NEW|OUR|YOUR|FROM|OVER|INTO|OUT"
    r"|CAN|WILL|WHAT|WHY|HOW|WHO|BUT|NOT|YOU|WE|IT|AS|BE|DO|IF|ITS|THEIR|WHICH"
    r"|WHEN|WHERE|MORE|MOST|SOME|ANY|EACH|EVERY|BEST|TOP|LONG|NEARLY|RARELY"
    r"|REVIEW|BLOG|BUILT|FEATURES|MARKET|DESIGN|MODEL|YEARS|BIG)\b"
)
_WORD = rf"(?:[ァ-ヶー]{{2,}}|(?!{_STOPWORDS})[A-Za-z]{{2,}})"
_AWORD = rf"\b(?>{_WORD})"
_CONTEXT_WORD = rf"(?!{_STOPWORDS})[A-Za-z]{{2,}}"
_ACONTEXT_WORD = rf"\b(?>{_CONTEXT_WORD})"
# A single trailing capital letter (e.g. "Street X") isn't caught by the
# 2+-char word classes above; only allow it as a suffix, and keep it
# genuinely uppercase regardless of the pattern's IGNORECASE flag so it
# doesn't degrade into matching any stray single letter.
_SINGLE_LETTER_SUFFIX = r"(?-i:[A-Z])\b"
_SUFFIX_WORD = rf"(?:{_ACONTEXT_WORD}|{_SINGLE_LETTER_SUFFIX})"
# Bridges an opening bracket (e.g. "GARMIN「Forerunner") when entering a
# match, but only ever whitespace once inside/after it - a closing
# bracket must not let the match bleed into unrelated text that follows
# (e.g. a publisher name after "「Forerunner 70」Impress Watch").
_SEP_ENTER = r"[\s「『【]+"
_SEP_CONTINUE = r"\s+"
# A digit run directly fused with a trailing capital letter, e.g. the
# "X" in "Instinct 2X" - no separator, so it's part of the core itself.
# The word and digits may also be joined by a hyphen (e.g. "GT-2000"),
# which is just as much a formatting/spacing choice as a bare space.
_CORE_STD = rf"{_AWORD}[\s-]?\d{{1,4}}(?-i:[A-Z])?"
_CORE_SHORT = r"[A-Za-z]\d{1,4}"

UNREGISTERED_PATTERN = re.compile(
    rf"(?:{_ACONTEXT_WORD}{_SEP_ENTER}){{1,2}}{_CORE_SHORT}(?:{_SEP_CONTINUE}{_SUFFIX_WORD}){{0,3}}"
    rf"|(?:{_ACONTEXT_WORD}{_SEP_ENTER}){{0,1}}{_CORE_STD}(?:{_SEP_CONTINUE}{_SUFFIX_WORD}){{0,3}}",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
TRADEMARK_PATTERN = re.compile(r"[®™©]")

# When text is quoted - Japanese brackets or quotation marks - the whole
# quoted span is almost always exactly the product name, a much more
# reliable signal than guessing how many context words to allow on each
# side (e.g. "クラウドランナー 3 マックス" keeps its internal space).
BRACKET_PATTERN = re.compile(
    r"「([^「」]{1,60})」"
    r"|『([^『』]{1,60})』"
    r"|“([^“”]{1,60})”"
    r"|\"([^\"]{1,60})\""
)
_BRACKET_CORE_CHECK = re.compile(rf"{_CORE_STD}|{_CORE_SHORT}", re.IGNORECASE)


def extract_bracketed_candidates(text):
    candidates = []
    for match in BRACKET_PATTERN.finditer(text):
        for i, group in enumerate(match.groups(), start=1):
            if group is None:
                continue
            inner = group.strip()
            if inner and _BRACKET_CORE_CHECK.search(inner):
                candidates.append((inner, match.start(i), match.end(i)))
            break
    return candidates


def build_brand_patterns(brands):
    brand_names = [b["name"] for b in brands]
    excluded = "|".join(sorted((re.escape(n) for n in brand_names), key=len, reverse=True))
    if excluded:
        continuation_word = rf"\b(?>(?!(?:{excluded})\b){_CONTEXT_WORD})"
    else:
        continuation_word = _ACONTEXT_WORD
    continuation_suffix = rf"(?:{continuation_word}|{_SINGLE_LETTER_SUFFIX})"

    patterns = []
    for brand in brands:
        pattern = re.compile(
            rf"\b{re.escape(brand['name'])}\b{_SEP_ENTER}{continuation_word}"
            rf"(?:{_SEP_CONTINUE}{continuation_suffix}){{0,3}}(?!(?:{_SEP_CONTINUE}|-)?[A-Za-z]?\d)",
            re.IGNORECASE,
        )
        patterns.append((pattern, brand.get("category_id")))
    return patterns


def build_brand_core_patterns(brands):
    """Brand directly followed by a digit-anchored model core, e.g.
    "アシックス GT-2000". Separate from build_brand_patterns because that
    one deliberately stops before a digit (it's for the no-digit case);
    _CORE_STD/_CORE_SHORT already handle katakana, hyphens, etc, so this
    just bridges the brand name (in any script) straight into them.
    """
    patterns = []
    for brand in brands:
        pattern = re.compile(
            rf"\b{re.escape(brand['name'])}\b{_SEP_ENTER}(?:{_CORE_SHORT}|{_CORE_STD})"
            rf"(?:{_SEP_CONTINUE}{_SUFFIX_WORD}){{0,3}}",
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
    return re.sub(r"(?<=[A-Zァ-ヶー])[\s-]+(?=\d)", "", text)


def build_regex_pattern(keyword):
    parts = []
    for segment in keyword.split(" "):
        match = re.match(r"^(\D+)(\d+)$", segment)
        if match:
            prefix, digits = match.groups()
            parts.append(re.escape(prefix) + r"[\s-]*" + re.escape(digits))
        else:
            parts.append(re.escape(segment))
    return r"\s+".join(parts)


_SOURCE_COLUMNS = "id, source_type, rss_url, search_query"


def fetch_active_sources(client, source_types=None):
    query = client.table("sources").select(_SOURCE_COLUMNS).eq("is_active", True)
    if source_types:
        query = query.in_("source_type", source_types)
    return query.execute().data or []


def fetch_source_by_id(client, source_id):
    res = client.table("sources").select(_SOURCE_COLUMNS).eq("id", source_id).execute()
    return res.data or []


def get_entry_id(entry):
    return entry.get("id") or entry.get("link") or entry.get("title", "")


def fetch_processed_entry_ids(client, entry_ids):
    """Which of these entry_ids have already been processed, under ANY
    source - the same article/video can surface under multiple sources
    (e.g. two Google News searches, or two YouTube search queries) and
    should only ever be counted once.
    """
    if not entry_ids:
        return set()
    res = client.table("processed_entries").select("entry_id").in_("entry_id", entry_ids).execute()
    return {row["entry_id"] for row in (res.data or [])}


def mark_entries_processed(client, source_id, entry_ids):
    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"source_id": source_id, "entry_id": entry_id, "processed_at": now}
        for entry_id in entry_ids
    ]
    if rows:
        client.table("processed_entries").insert(rows).execute()


def collect_rss_texts(client, src):
    feed = feedparser.parse(src["rss_url"])
    entries = [(get_entry_id(entry), entry) for entry in feed.entries]
    already_ids = fetch_processed_entry_ids(client, [eid for eid, _ in entries])

    texts = []
    new_ids = []
    for entry_id, entry in entries:
        if entry_id in already_ids:
            continue
        title = entry.get("title", "")
        summary = entry.get("summary", "")
        texts.append(normalize_text(strip_noise(f"{title} {summary}")))
        new_ids.append(entry_id)
    mark_entries_processed(client, src["id"], new_ids)
    return texts


def fetch_youtube_videos(query, api_key, published_after=None):
    params = {
        "part": "snippet",
        "type": "video",
        "order": "date",
        "relevanceLanguage": "ja",
        "regionCode": "JP",
        "maxResults": 50,
        "q": query,
        "key": api_key,
    }
    if published_after:
        params["publishedAfter"] = published_after
    response = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=15)
    response.raise_for_status()
    return response.json().get("items", [])


def collect_youtube_texts(client, src):
    api_key = get_youtube_api_key()
    if not api_key or not src.get("search_query"):
        return []

    last_run = (
        client.table("processed_entries")
        .select("processed_at")
        .eq("source_id", src["id"])
        .order("processed_at", desc=True)
        .limit(1)
        .execute()
        .data
    )
    published_after = None
    if last_run:
        last_time = datetime.fromisoformat(last_run[0]["processed_at"].replace("Z", "+00:00"))
        published_after = (last_time - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    items = fetch_youtube_videos(src["search_query"], api_key, published_after)
    video_ids = [item["id"]["videoId"] for item in items if item.get("id", {}).get("videoId")]
    if not video_ids:
        return []

    already_ids = fetch_processed_entry_ids(client, video_ids)

    texts = []
    new_ids = []
    for item in items:
        video_id = item.get("id", {}).get("videoId")
        if not video_id or video_id in already_ids:
            continue
        snippet = item.get("snippet", {})
        title = snippet.get("title", "")
        description = snippet.get("description", "")
        texts.append(normalize_text(strip_noise(f"{title} {description}")))
        new_ids.append(video_id)

    mark_entries_processed(client, src["id"], new_ids)
    return texts


def collect_texts(client, sources):
    texts = []
    for src in sources:
        try:
            if src.get("source_type") == "youtube_search":
                texts.extend(collect_youtube_texts(client, src))
            else:
                texts.extend(collect_rss_texts(client, src))
        except Exception as e:
            print(f"[collect_texts] source {src.get('id')} failed: {e}")
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
    A resulting overly-generic remainder (e.g. a plain dictionary word) is
    a tradeoff left to human review/blacklist rather than guessed here.
    """
    for brand in brands:
        brand_name = canonicalize_keyword(brand["name"])
        if keyword == brand_name:
            return keyword, brand.get("category_id"), brand["name"]
        if keyword.startswith(brand_name + " "):
            remainder = keyword[len(brand_name) :].strip()
            if remainder and not remainder[0].isdigit():
                return remainder, brand.get("category_id"), brand["name"]
            return keyword, brand.get("category_id"), brand["name"]
        if keyword.startswith(brand_name) and keyword[len(brand_name) : len(brand_name) + 1].isdigit():
            return keyword, brand.get("category_id"), brand["name"]
    return keyword, None, None


def extract_unregistered_keywords(texts, products, blacklist, brands=None, aliases=None):
    brands = brands or []
    alias_map = {
        canonicalize_keyword(a["alias"]): canonicalize_keyword(a["canonical_name"])
        for a in (aliases or [])
    }
    registered_patterns = [re.compile(p["regex_pattern"], re.IGNORECASE) for p in products]
    blacklist_set = {canonicalize_keyword(normalize_text(word)) for word in blacklist}
    brand_patterns = [pattern for pattern, _ in build_brand_patterns(brands)]
    brand_core_patterns = [pattern for pattern, _ in build_brand_core_patterns(brands)]
    patterns = [UNREGISTERED_PATTERN] + brand_patterns + brand_core_patterns

    found = {}

    def consider(raw_text, text, start, end):
        raw_keyword = canonicalize_keyword(raw_text)
        keyword, brand_category_id, brand_name = split_brand_prefix(raw_keyword, brands)
        keyword = alias_map.get(keyword, keyword)
        if brand_name is None:
            return
        if keyword in blacklist_set:
            return
        if any(p.search(keyword) for p in registered_patterns):
            return
        if keyword not in found:
            ctx_start = max(start - 20, 0)
            ctx_end = min(end + 20, len(text))
            found[keyword] = {
                "context": text[ctx_start:ctx_end],
                "brand_category_id": brand_category_id,
                "brand_name": brand_name,
            }

    for text in texts:
        for pattern in patterns:
            for match in pattern.finditer(text):
                consider(match.group(), text, match.start(), match.end())
        for inner, start, end in extract_bracketed_candidates(text):
            consider(inner, text, start, end)
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
        brand_name = info["brand_name"]
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
                    "brand_name": brand_name,
                    "updated_at": now,
                }
            ).eq("id", row["id"]).execute()
        else:
            client.table("unregistered_keywords").insert(
                {
                    "keyword": keyword,
                    "predicted_category_id": predicted_category_id,
                    "brand_name": brand_name,
                    "count": 1,
                    "sample_context": context,
                    "updated_at": now,
                }
            ).execute()


def run(source_id=None, source_types=None):
    client = get_client()

    if source_id is not None:
        sources = fetch_source_by_id(client, source_id)
    else:
        sources = fetch_active_sources(client, source_types)
    products = client.table("products").select("id, regex_pattern").execute().data or []
    categories = client.table("categories").select("id, seed_keywords").execute().data or []
    blacklist = [
        row["keyword"] for row in (client.table("blacklist").select("keyword").execute().data or [])
    ]
    brands = client.table("brands").select("name, category_id").execute().data or []
    aliases = client.table("product_aliases").select("alias, canonical_name").execute().data or []

    texts = collect_texts(client, sources)

    counts = count_product_mentions(texts, products)
    upsert_daily_buzz(client, counts)

    keyword_contexts = extract_unregistered_keywords(texts, products, blacklist, brands, aliases)
    upsert_unregistered_keywords(client, keyword_contexts, categories)

    return texts


if __name__ == "__main__":
    # Default to RSS-only so a plain `python src/batch.py` (and the existing
    # hourly workflow) never burns YouTube quota unless explicitly asked.
    cli_types = sys.argv[1].split(",") if len(sys.argv) > 1 else ["rss"]
    run(source_types=cli_types)
