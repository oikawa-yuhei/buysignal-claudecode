import sys
from pathlib import Path
from urllib.parse import quote_plus

sys.path.append(str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from src.batch import build_regex_pattern, canonicalize_keyword
from src.batch import run as run_batch
from src.config import get_client

st.set_page_config(page_title="BuySignal", page_icon="⚡", layout="centered")

client = get_client()


@st.cache_data(ttl=30)
def load_categories():
    return (
        client.table("categories")
        .select("id, name, icon, seed_keywords")
        .order("id")
        .execute()
        .data
        or []
    )


@st.cache_data(ttl=15)
def load_unregistered_keywords(category_id):
    query = client.table("unregistered_keywords").select("*").order("count", desc=True)
    if category_id is not None:
        query = query.eq("predicted_category_id", category_id)
    return query.execute().data or []


@st.cache_data(ttl=30)
def load_sources(category_id):
    query = client.table("sources").select("*").order("id")
    if category_id is not None:
        query = query.eq("category_id", category_id)
    return query.execute().data or []


@st.cache_data(ttl=15)
def load_products(category_id):
    query = client.table("products").select("*").order("created_at", desc=True)
    if category_id is not None:
        query = query.eq("category_id", category_id)
    return query.execute().data or []


@st.cache_data(ttl=15)
def load_blacklist():
    return client.table("blacklist").select("*").order("created_at", desc=True).execute().data or []


@st.cache_data(ttl=30)
def load_brands(category_id):
    query = client.table("brands").select("*").order("name")
    if category_id is not None:
        query = query.eq("category_id", category_id)
    return query.execute().data or []


@st.cache_data(ttl=30)
def load_aliases(category_id):
    query = client.table("product_aliases").select("*").order("alias")
    if category_id is not None:
        query = query.eq("category_id", category_id)
    return query.execute().data or []


@st.cache_data(ttl=60)
def load_daily_buzz_logs(product_ids):
    if not product_ids:
        return []
    return (
        client.table("daily_buzz_logs")
        .select("product_id, logged_at, count")
        .in_("product_id", list(product_ids))
        .execute()
        .data
        or []
    )


def product_exists(name):
    return bool(client.table("products").select("id").eq("name", name).execute().data)


def approve_keyword(row, category_id, keyword_override=None):
    name = canonicalize_keyword(keyword_override) if keyword_override else row["keyword"]
    client.table("products").insert(
        {
            "name": name,
            "regex_pattern": build_regex_pattern(name),
            "category_id": category_id,
        }
    ).execute()
    client.table("unregistered_keywords").delete().eq("id", row["id"]).execute()


def add_product(name, regex_pattern, category_id):
    client.table("products").insert(
        {"name": name, "regex_pattern": regex_pattern, "category_id": category_id}
    ).execute()


def reject_keyword(row):
    client.table("blacklist").insert({"keyword": row["keyword"]}).execute()
    client.table("unregistered_keywords").delete().eq("id", row["id"]).execute()


def toggle_source(source_id, is_active):
    client.table("sources").update({"is_active": is_active}).eq("id", source_id).execute()


def delete_source(source_id):
    client.table("sources").delete().eq("id", source_id).execute()


def add_source(name, source_type, rss_url, search_query, category_id):
    client.table("sources").insert(
        {
            "name": name,
            "source_type": source_type,
            "rss_url": rss_url,
            "search_query": search_query,
            "category_id": category_id,
            "is_active": True,
        }
    ).execute()


def add_category(name, seed_keywords, icon):
    client.table("categories").insert(
        {"name": name, "seed_keywords": seed_keywords, "icon": icon}
    ).execute()


def delete_category(category_id):
    client.table("categories").delete().eq("id", category_id).execute()


def add_brand(name, category_id):
    client.table("brands").insert({"name": name, "category_id": category_id}).execute()


def delete_brand(brand_id):
    client.table("brands").delete().eq("id", brand_id).execute()


def add_alias(alias, canonical_name, category_id):
    client.table("product_aliases").insert(
        {"alias": alias, "canonical_name": canonical_name, "category_id": category_id}
    ).execute()


def delete_alias(alias_id):
    client.table("product_aliases").delete().eq("id", alias_id).execute()


def update_category_seed_keywords(category_id, seed_keywords):
    client.table("categories").update({"seed_keywords": seed_keywords}).eq(
        "id", category_id
    ).execute()


def delete_product(product_id):
    client.table("products").delete().eq("id", product_id).execute()


def merge_products(duplicate_id, canonical_id):
    duplicate = client.table("products").select("*").eq("id", duplicate_id).execute().data[0]
    canonical = client.table("products").select("*").eq("id", canonical_id).execute().data[0]

    dup_logs = (
        client.table("daily_buzz_logs").select("*").eq("product_id", duplicate_id).execute().data
        or []
    )
    for log in dup_logs:
        existing = (
            client.table("daily_buzz_logs")
            .select("id, count")
            .eq("product_id", canonical_id)
            .eq("logged_at", log["logged_at"])
            .execute()
        )
        if existing.data:
            row = existing.data[0]
            client.table("daily_buzz_logs").update({"count": row["count"] + log["count"]}).eq(
                "id", row["id"]
            ).execute()
        else:
            client.table("daily_buzz_logs").insert(
                {
                    "product_id": canonical_id,
                    "logged_at": log["logged_at"],
                    "count": log["count"],
                }
            ).execute()

    existing_alias = (
        client.table("product_aliases").select("id").eq("alias", duplicate["name"]).execute()
    )
    if not existing_alias.data:
        client.table("product_aliases").insert(
            {
                "alias": duplicate["name"],
                "canonical_name": canonical["name"],
                "category_id": canonical.get("category_id"),
            }
        ).execute()

    client.table("products").delete().eq("id", duplicate_id).execute()


def delete_blacklist_entry(blacklist_id):
    client.table("blacklist").delete().eq("id", blacklist_id).execute()


st.markdown(
    """
    <style>
    header[data-testid="stHeader"] {display: none;}
    .block-container {padding-top: 1.5rem; padding-bottom: 4rem; max-width: 480px;}
    div[data-baseweb="tab-list"] {overflow-x: auto; flex-wrap: nowrap;}
    div[data-testid="stVerticalBlockBorderWrapper"] {margin-bottom: 0.4rem;}
    div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stVerticalBlock"] {gap: 0.25rem;}
    div[data-testid="stVerticalBlockBorderWrapper"] .stMarkdown p {margin-bottom: 0;}
    div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stCaptionContainer"] p {margin-bottom: 0;}
    div[data-testid="column"] .stButton button {padding: 0.15rem 0.4rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div style="text-align:left; margin-bottom: 1.2rem; line-height: 1.1;">
        <span style="font-size: clamp(1.6rem, 8vw, 2.2rem); vertical-align: middle;">⚡</span>
        <span style="
            font-size: clamp(1.6rem, 8vw, 2.2rem);
            font-weight: 800;
            letter-spacing: -0.02em;
            background: linear-gradient(90deg, #6366f1, #ec4899);
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
            vertical-align: middle;
        ">BuySignal</span>
        <span style="font-size: 0.75rem; color: #9ca3af; letter-spacing: 0.2em; margin-left: 0.6em; vertical-align: middle;">
            ポチポチツール
        </span>
    </div>
    """,
    unsafe_allow_html=True,
)

PAGES = ["承認キュー", "推移", "履歴", "巡回先管理", "カテゴリ管理", "ブランド管理", "エイリアス管理"]
page = st.pills(
    "ページ",
    PAGES,
    default=PAGES[0],
    required=True,
    label_visibility="collapsed",
    key="page_nav",
)

categories = load_categories()
category_labels = ["すべて"] + [f'{c.get("icon") or "🏷️"} {c["name"]}' for c in categories]
category_ids = [None] + [c["id"] for c in categories]

if page == "承認キュー":
    if st.button("🔄 今すぐ巡回実行", use_container_width=True):
        with st.spinner("巡回中..."):
            texts = run_batch()
        st.session_state["last_run_texts"] = texts
        st.cache_data.clear()
        st.success(f"巡回が完了しました({len(texts)}件のテキストを取得)")
        st.rerun()

    if st.session_state.get("last_run_texts"):
        with st.expander(f"取得テキストを見る({len(st.session_state['last_run_texts'])}件)"):
            for text in st.session_state["last_run_texts"]:
                st.markdown(f"- {text}")

    with st.expander("➕ 任意のワードを直接追加"):
        with st.form("add_product_form", clear_on_submit=True):
            new_product_name = st.text_input("ワード")
            product_category_options = {c["name"]: c["id"] for c in categories}
            product_category_name = st.selectbox(
                "カテゴリ",
                list(product_category_options.keys()) if product_category_options else ["未分類"],
                key="add_product_category",
            )
            submitted_product = st.form_submit_button("追加", use_container_width=True)
            if submitted_product:
                if not new_product_name:
                    st.warning("ワードを入力してください")
                else:
                    canonical_name = canonicalize_keyword(new_product_name)
                    if product_exists(canonical_name):
                        st.warning(f"「{canonical_name}」はすでに登録されています")
                    else:
                        add_product(
                            canonical_name,
                            build_regex_pattern(canonical_name),
                            product_category_options.get(product_category_name),
                        )
                        st.cache_data.clear()
                        st.success("追加しました")
                        st.rerun()

    category_tabs = st.tabs(category_labels)
    for tab, category_id in zip(category_tabs, category_ids):
        with tab:
            keywords = load_unregistered_keywords(category_id)
            if not keywords:
                st.info("未登録ワードはありません")
            for row in keywords:
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                    with col1:
                        st.markdown(f"**{row['keyword']}** ({row['count']}件)")
                        if row.get("brand_name"):
                            st.caption(f"🏷️ {row['brand_name']}")
                    with col2:
                        search_query = f"{row.get('brand_name') or ''} {row['keyword']}".strip()
                        st.link_button(
                            "🔍",
                            f"https://www.google.com/search?q={quote_plus(search_query)}",
                            use_container_width=True,
                        )
                    with col3:
                        if st.button(
                            "⭕",
                            key=f"approve_{category_id}_{row['id']}",
                            use_container_width=True,
                        ):
                            if product_exists(row["keyword"]):
                                client.table("unregistered_keywords").delete().eq(
                                    "id", row["id"]
                                ).execute()
                                st.cache_data.clear()
                                st.warning(
                                    f"「{row['keyword']}」はすでに承認済みでした。キューから削除しました。"
                                )
                                st.rerun()
                            else:
                                target_category_id = (
                                    row.get("predicted_category_id") or category_id
                                )
                                approve_keyword(row, target_category_id)
                                st.cache_data.clear()
                                st.rerun()
                    with col4:
                        if st.button(
                            "❌",
                            key=f"reject_{category_id}_{row['id']}",
                            use_container_width=True,
                        ):
                            reject_keyword(row)
                            st.cache_data.clear()
                            st.rerun()
                    if row.get("sample_context"):
                        st.caption(row["sample_context"])

                    with st.expander("✏️ 修正して承認"):
                        edited_keyword = st.text_input(
                            "ワード",
                            value=row["keyword"],
                            key=f"edit_keyword_{category_id}_{row['id']}",
                        )
                        if st.button(
                            "この内容で承認",
                            key=f"approve_edited_{category_id}_{row['id']}",
                            use_container_width=True,
                        ):
                            if not edited_keyword.strip():
                                st.warning("ワードを入力してください")
                            elif product_exists(canonicalize_keyword(edited_keyword)):
                                st.warning(
                                    f"「{canonicalize_keyword(edited_keyword)}」はすでに登録されています"
                                )
                            else:
                                target_category_id = (
                                    row.get("predicted_category_id") or category_id
                                )
                                approve_keyword(row, target_category_id, edited_keyword)
                                st.cache_data.clear()
                                st.success("修正して承認しました")
                                st.rerun()

elif page == "推移":
    st.subheader("バズ推移(日別言及数)")
    trend_category_tabs = st.tabs(category_labels)
    for tab, category_id in zip(trend_category_tabs, category_ids):
        with tab:
            products = load_products(category_id)
            if not products:
                st.info("承認済みの商品はありません")
                continue

            product_ids = tuple(sorted(p["id"] for p in products))
            logs = load_daily_buzz_logs(product_ids)
            if not logs:
                st.info("まだバズデータがありません")
                continue

            product_name_by_id = {p["id"]: p["name"] for p in products}
            df = pd.DataFrame(logs)
            df["商品"] = df["product_id"].map(product_name_by_id)
            pivot = (
                df.pivot_table(
                    index="logged_at", columns="商品", values="count", aggfunc="sum"
                )
                .fillna(0)
                .sort_index()
            )

            default_products = list(pivot.sum().sort_values(ascending=False).head(5).index)
            selected = st.multiselect(
                "表示する商品(初期値は上位5件)",
                list(pivot.columns),
                default=default_products,
                key=f"trend_select_{category_id}",
            )
            if selected:
                st.line_chart(pivot[selected])
            else:
                st.info("商品を選んでください")

            with st.expander("表で見る"):
                st.dataframe(pivot, use_container_width=True)

elif page == "履歴":
    approved_tab, rejected_tab = st.tabs(["⭕ 承認済み", "❌ 却下済み"])

    with approved_tab:
        all_products = load_products(None)
        approved_category_tabs = st.tabs(category_labels)
        for tab, category_id in zip(approved_category_tabs, category_ids):
            with tab:
                products = load_products(category_id)
                if not products:
                    st.info("承認済みの商品はありません")
                for product in products:
                    with st.container(border=True):
                        col1, col2, col3 = st.columns([3, 1, 1])
                        with col1:
                            st.markdown(f"**{product['name']}**")
                            st.caption(product["regex_pattern"])
                        with col2:
                            if st.button(
                                "🔀",
                                key=f"merge_product_btn_{category_id}_{product['id']}",
                                use_container_width=True,
                            ):
                                st.session_state[
                                    f"show_merge_product_{category_id}_{product['id']}"
                                ] = True
                        with col3:
                            if st.button(
                                "🗑️",
                                key=f"delete_product_btn_{category_id}_{product['id']}",
                                use_container_width=True,
                            ):
                                st.session_state[
                                    f"confirm_delete_product_{category_id}_{product['id']}"
                                ] = True

                        if st.session_state.get(
                            f"show_merge_product_{category_id}_{product['id']}"
                        ):
                            other_products = {
                                p["name"]: p["id"]
                                for p in all_products
                                if p["id"] != product["id"]
                            }
                            if not other_products:
                                st.info("統合先にできる他の商品がありません")
                            else:
                                merge_target_name = st.selectbox(
                                    "表記ゆれで重複しているこの商品を、どちらに統合しますか?"
                                    "(この商品は削除され、正式表記として登録されます)",
                                    list(other_products.keys()),
                                    key=f"merge_target_{category_id}_{product['id']}",
                                )
                                merge_col1, merge_col2 = st.columns(2)
                                with merge_col1:
                                    if st.button(
                                        "統合する",
                                        key=f"merge_confirm_{category_id}_{product['id']}",
                                        use_container_width=True,
                                    ):
                                        merge_products(
                                            product["id"], other_products[merge_target_name]
                                        )
                                        del st.session_state[
                                            f"show_merge_product_{category_id}_{product['id']}"
                                        ]
                                        st.cache_data.clear()
                                        st.success(
                                            f"「{product['name']}」を「{merge_target_name}」に統合しました"
                                        )
                                        st.rerun()
                                with merge_col2:
                                    if st.button(
                                        "キャンセル",
                                        key=f"merge_cancel_{category_id}_{product['id']}",
                                        use_container_width=True,
                                    ):
                                        del st.session_state[
                                            f"show_merge_product_{category_id}_{product['id']}"
                                        ]
                                        st.rerun()

                        if st.session_state.get(
                            f"confirm_delete_product_{category_id}_{product['id']}"
                        ):
                            st.warning(f"「{product['name']}」の承認を取り消しますか？")
                            confirm_col1, confirm_col2 = st.columns(2)
                            with confirm_col1:
                                if st.button(
                                    "はい、取り消す",
                                    key=f"confirm_delete_product_yes_{category_id}_{product['id']}",
                                    use_container_width=True,
                                ):
                                    delete_product(product["id"])
                                    del st.session_state[
                                        f"confirm_delete_product_{category_id}_{product['id']}"
                                    ]
                                    st.cache_data.clear()
                                    st.rerun()
                            with confirm_col2:
                                if st.button(
                                    "キャンセル",
                                    key=f"confirm_delete_product_no_{category_id}_{product['id']}",
                                    use_container_width=True,
                                ):
                                    del st.session_state[
                                        f"confirm_delete_product_{category_id}_{product['id']}"
                                    ]
                                    st.rerun()

    with rejected_tab:
        blacklist_entries = load_blacklist()
        if not blacklist_entries:
            st.info("却下済みのワードはありません")
        for entry in blacklist_entries:
            with st.container(border=True):
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.markdown(f"**{entry['keyword']}**")
                with col2:
                    if st.button(
                        "🗑️", key=f"delete_blacklist_btn_{entry['id']}", use_container_width=True
                    ):
                        st.session_state[f"confirm_delete_blacklist_{entry['id']}"] = True

                if st.session_state.get(f"confirm_delete_blacklist_{entry['id']}"):
                    st.warning(f"「{entry['keyword']}」の却下を取り消しますか？")
                    confirm_col1, confirm_col2 = st.columns(2)
                    with confirm_col1:
                        if st.button(
                            "はい、取り消す",
                            key=f"confirm_delete_blacklist_yes_{entry['id']}",
                            use_container_width=True,
                        ):
                            delete_blacklist_entry(entry["id"])
                            del st.session_state[f"confirm_delete_blacklist_{entry['id']}"]
                            st.cache_data.clear()
                            st.rerun()
                    with confirm_col2:
                        if st.button(
                            "キャンセル",
                            key=f"confirm_delete_blacklist_no_{entry['id']}",
                            use_container_width=True,
                        ):
                            del st.session_state[f"confirm_delete_blacklist_{entry['id']}"]
                            st.rerun()

elif page == "巡回先管理":
    st.subheader("新規巡回先の追加")
    new_source_type_label = st.radio(
        "種類", ["RSS", "YouTube検索"], horizontal=True, key="new_source_type"
    )
    with st.form("add_source_form", clear_on_submit=True):
        name = st.text_input("サイト名")
        if new_source_type_label == "RSS":
            rss_url = st.text_input("RSS URL")
            search_query = None
        else:
            search_query = st.text_input("検索語")
            rss_url = None
        category_options = {c["name"]: c["id"] for c in categories}
        category_name = st.selectbox(
            "デフォルトカテゴリ", list(category_options.keys()) if category_options else ["未分類"]
        )
        submitted = st.form_submit_button("追加", use_container_width=True)
        if submitted:
            if name and (rss_url or search_query):
                add_source(
                    name,
                    "rss" if new_source_type_label == "RSS" else "youtube_search",
                    rss_url,
                    search_query,
                    category_options.get(category_name),
                )
                st.cache_data.clear()
                st.success("追加しました")
                st.rerun()
            else:
                field_label = "RSS URL" if new_source_type_label == "RSS" else "検索語"
                st.warning(f"サイト名と{field_label}を入力してください")

    st.divider()
    st.subheader("巡回先一覧")
    source_category_tabs = st.tabs(category_labels)
    for tab, category_id in zip(source_category_tabs, category_ids):
        with tab:
            sources = load_sources(category_id)
            if not sources:
                st.info("巡回先はありません")
            for src in sources:
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
                    with col1:
                        st.markdown(f"**{src['name']}**")
                        if src.get("source_type") == "youtube_search":
                            st.caption(f"🔍 YouTube: {src.get('search_query')}")
                        else:
                            st.caption(src.get("rss_url"))
                    with col2:
                        is_active = st.toggle(
                            "ON/OFF",
                            value=src["is_active"],
                            key=f"source_toggle_{category_id}_{src['id']}",
                            label_visibility="collapsed",
                        )
                        if is_active != src["is_active"]:
                            toggle_source(src["id"], is_active)
                            st.cache_data.clear()
                            st.rerun()
                    with col3:
                        if st.button(
                            "▶",
                            key=f"run_source_btn_{category_id}_{src['id']}",
                            use_container_width=True,
                        ):
                            with st.spinner(f"「{src['name']}」を巡回中..."):
                                texts = run_batch(source_id=src["id"])
                            st.session_state[f"last_run_texts_{src['id']}"] = texts
                            st.cache_data.clear()
                            st.success(f"巡回が完了しました({len(texts)}件のテキストを取得)")
                            st.rerun()
                    with col4:
                        if st.button(
                            "🗑️",
                            key=f"delete_btn_{category_id}_{src['id']}",
                            use_container_width=True,
                        ):
                            st.session_state[f"confirm_delete_{src['id']}"] = True

                    if st.session_state.get(f"last_run_texts_{src['id']}"):
                        run_texts = st.session_state[f"last_run_texts_{src['id']}"]
                        with st.expander(f"取得テキストを見る({len(run_texts)}件)"):
                            for text in run_texts:
                                st.markdown(f"- {text}")

                    if st.session_state.get(f"confirm_delete_{src['id']}"):
                        st.warning(f"「{src['name']}」を削除しますか？この操作は取り消せません。")
                        confirm_col1, confirm_col2 = st.columns(2)
                        with confirm_col1:
                            if st.button(
                                "はい、削除する",
                                key=f"confirm_delete_yes_{category_id}_{src['id']}",
                                use_container_width=True,
                            ):
                                delete_source(src["id"])
                                del st.session_state[f"confirm_delete_{src['id']}"]
                                st.cache_data.clear()
                                st.rerun()
                        with confirm_col2:
                            if st.button(
                                "キャンセル",
                                key=f"confirm_delete_no_{category_id}_{src['id']}",
                                use_container_width=True,
                            ):
                                del st.session_state[f"confirm_delete_{src['id']}"]
                                st.rerun()

elif page == "カテゴリ管理":
    st.subheader("新規カテゴリの追加")
    with st.form("add_category_form", clear_on_submit=True):
        new_name = st.text_input("カテゴリ名")
        new_icon = st.text_input("アイコン(絵文字)", value="🏷️")
        new_seed_keywords_raw = st.text_input("シードキーワード(カンマ区切り)")
        submitted_cat = st.form_submit_button("追加", use_container_width=True)
        if submitted_cat:
            if new_name:
                seed_keywords = [k.strip() for k in new_seed_keywords_raw.split(",") if k.strip()]
                add_category(new_name, seed_keywords, new_icon or "🏷️")
                st.cache_data.clear()
                st.success("追加しました")
                st.rerun()
            else:
                st.warning("カテゴリ名を入力してください")

    st.divider()
    st.subheader("カテゴリ一覧")
    for cat in categories:
        with st.container(border=True):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"**{cat.get('icon') or '🏷️'} {cat['name']}**")
                seed_keywords = cat.get("seed_keywords") or []
                if seed_keywords:
                    st.caption(", ".join(seed_keywords))
            with col2:
                if st.button("🗑️", key=f"delete_cat_btn_{cat['id']}", use_container_width=True):
                    st.session_state[f"confirm_delete_cat_{cat['id']}"] = True

            with st.expander("シードキーワードを編集"):
                edited_keywords_raw = st.text_input(
                    "シードキーワード(カンマ区切り)",
                    value=", ".join(seed_keywords),
                    key=f"edit_seed_keywords_{cat['id']}",
                )
                if st.button(
                    "更新", key=f"update_seed_keywords_btn_{cat['id']}", use_container_width=True
                ):
                    new_seed_keywords = [
                        k.strip() for k in edited_keywords_raw.split(",") if k.strip()
                    ]
                    update_category_seed_keywords(cat["id"], new_seed_keywords)
                    st.cache_data.clear()
                    st.success("更新しました")
                    st.rerun()

            if st.session_state.get(f"confirm_delete_cat_{cat['id']}"):
                st.warning(
                    f"「{cat['name']}」を削除しますか？紐づく巡回先/商品/未登録ワードのカテゴリは未分類になります。"
                )
                confirm_col1, confirm_col2 = st.columns(2)
                with confirm_col1:
                    if st.button(
                        "はい、削除する",
                        key=f"confirm_delete_cat_yes_{cat['id']}",
                        use_container_width=True,
                    ):
                        delete_category(cat["id"])
                        del st.session_state[f"confirm_delete_cat_{cat['id']}"]
                        st.cache_data.clear()
                        st.rerun()
                with confirm_col2:
                    if st.button(
                        "キャンセル",
                        key=f"confirm_delete_cat_no_{cat['id']}",
                        use_container_width=True,
                    ):
                        del st.session_state[f"confirm_delete_cat_{cat['id']}"]
                        st.rerun()

elif page == "ブランド管理":
    st.caption("ここに登録したブランド名は、数字を含まない商品名(例: GARMIN Instinct Crossover)の検出と、カテゴリの自動判定に使われます。")
    st.subheader("新規ブランドの追加")
    with st.form("add_brand_form", clear_on_submit=True):
        new_brand_name = st.text_input("ブランド名(英字表記)")
        brand_category_options = {c["name"]: c["id"] for c in categories}
        brand_category_name = st.selectbox(
            "カテゴリ",
            list(brand_category_options.keys()) if brand_category_options else ["未分類"],
            key="add_brand_category",
        )
        submitted_brand = st.form_submit_button("追加", use_container_width=True)
        if submitted_brand:
            if new_brand_name:
                add_brand(new_brand_name.strip(), brand_category_options.get(brand_category_name))
                st.cache_data.clear()
                st.success("追加しました")
                st.rerun()
            else:
                st.warning("ブランド名を入力してください")

    st.divider()
    st.subheader("ブランド一覧")
    brand_category_label_by_id = {
        c["id"]: f'{c.get("icon") or "🏷️"} {c["name"]}' for c in categories
    }
    brand_category_tabs = st.tabs(category_labels)
    for tab, category_id in zip(brand_category_tabs, category_ids):
        with tab:
            brands = load_brands(category_id)
            if not brands:
                st.info("ブランドが登録されていません")
            for brand in brands:
                with st.container(border=True):
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.markdown(f"**{brand['name']}**")
                        category_label = brand_category_label_by_id.get(brand.get("category_id"))
                        st.caption(category_label or "未分類")
                    with col2:
                        if st.button(
                            "🗑️",
                            key=f"delete_brand_btn_{category_id}_{brand['id']}",
                            use_container_width=True,
                        ):
                            st.session_state[f"confirm_delete_brand_{brand['id']}"] = True

                    if st.session_state.get(f"confirm_delete_brand_{brand['id']}"):
                        st.warning(f"「{brand['name']}」を削除しますか?")
                        confirm_col1, confirm_col2 = st.columns(2)
                        with confirm_col1:
                            if st.button(
                                "はい、削除する",
                                key=f"confirm_delete_brand_yes_{category_id}_{brand['id']}",
                                use_container_width=True,
                            ):
                                delete_brand(brand["id"])
                                del st.session_state[f"confirm_delete_brand_{brand['id']}"]
                                st.cache_data.clear()
                                st.rerun()
                        with confirm_col2:
                            if st.button(
                                "キャンセル",
                                key=f"confirm_delete_brand_no_{category_id}_{brand['id']}",
                                use_container_width=True,
                            ):
                                del st.session_state[f"confirm_delete_brand_{brand['id']}"]
                                st.rerun()

elif page == "エイリアス管理":
    st.caption(
        "カタカナ表記と英字表記など、表記ゆれで別候補になってしまう場合にここで対応付けておくと、"
        "抽出時に「正式表記」の方へ自動的にまとめられます。"
    )
    st.subheader("エイリアスの追加")
    with st.form("add_alias_form", clear_on_submit=True):
        new_alias = st.text_input("エイリアス表記(例: ノヴァブラスト6)")
        new_canonical = st.text_input("正式表記(例: NOVABLAST6)")
        alias_category_options = {c["name"]: c["id"] for c in categories}
        alias_category_name = st.selectbox(
            "カテゴリ",
            list(alias_category_options.keys()) if alias_category_options else ["未分類"],
            key="add_alias_category",
        )
        submitted_alias = st.form_submit_button("追加", use_container_width=True)
        if submitted_alias:
            if new_alias and new_canonical:
                add_alias(
                    canonicalize_keyword(new_alias),
                    canonicalize_keyword(new_canonical),
                    alias_category_options.get(alias_category_name),
                )
                st.cache_data.clear()
                st.success("追加しました")
                st.rerun()
            else:
                st.warning("エイリアス表記と正式表記の両方を入力してください")

    st.divider()
    st.subheader("エイリアス一覧")
    alias_category_tabs = st.tabs(category_labels)
    for tab, category_id in zip(alias_category_tabs, category_ids):
        with tab:
            aliases = load_aliases(category_id)
            if not aliases:
                st.info("エイリアスは登録されていません")
            for alias in aliases:
                with st.container(border=True):
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.markdown(f"**{alias['alias']}** → {alias['canonical_name']}")
                    with col2:
                        if st.button(
                            "🗑️",
                            key=f"delete_alias_btn_{category_id}_{alias['id']}",
                            use_container_width=True,
                        ):
                            st.session_state[f"confirm_delete_alias_{alias['id']}"] = True

                    if st.session_state.get(f"confirm_delete_alias_{alias['id']}"):
                        st.warning(f"「{alias['alias']}」のエイリアスを削除しますか?")
                        confirm_col1, confirm_col2 = st.columns(2)
                        with confirm_col1:
                            if st.button(
                                "はい、削除する",
                                key=f"confirm_delete_alias_yes_{category_id}_{alias['id']}",
                                use_container_width=True,
                            ):
                                delete_alias(alias["id"])
                                del st.session_state[f"confirm_delete_alias_{alias['id']}"]
                                st.cache_data.clear()
                                st.rerun()
                        with confirm_col2:
                            if st.button(
                                "キャンセル",
                                key=f"confirm_delete_alias_no_{category_id}_{alias['id']}",
                                use_container_width=True,
                            ):
                                del st.session_state[f"confirm_delete_alias_{alias['id']}"]
                                st.rerun()
