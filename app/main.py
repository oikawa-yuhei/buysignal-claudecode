import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src.config import get_client

st.set_page_config(page_title="ポチポチツール", page_icon="🛒", layout="centered")

client = get_client()


@st.cache_data(ttl=30)
def load_categories():
    return client.table("categories").select("id, name, icon").order("id").execute().data or []


@st.cache_data(ttl=15)
def load_unregistered_keywords(category_id):
    query = client.table("unregistered_keywords").select("*").order("count", desc=True)
    if category_id is not None:
        query = query.eq("predicted_category_id", category_id)
    return query.execute().data or []


@st.cache_data(ttl=30)
def load_sources():
    return client.table("sources").select("*").order("id").execute().data or []


def approve_keyword(row, category_id):
    client.table("products").insert(
        {"name": row["keyword"], "regex_pattern": row["keyword"], "category_id": category_id}
    ).execute()
    client.table("unregistered_keywords").delete().eq("id", row["id"]).execute()


def reject_keyword(row):
    client.table("blacklist").insert({"keyword": row["keyword"]}).execute()
    client.table("unregistered_keywords").delete().eq("id", row["id"]).execute()


def toggle_source(source_id, is_active):
    client.table("sources").update({"is_active": is_active}).eq("id", source_id).execute()


def add_source(name, rss_url, category_id):
    client.table("sources").insert(
        {"name": name, "rss_url": rss_url, "category_id": category_id, "is_active": True}
    ).execute()


st.markdown(
    """
    <style>
    .block-container {padding-top: 1rem; padding-bottom: 4rem; max-width: 480px;}
    div[data-baseweb="tab-list"] {overflow-x: auto; flex-wrap: nowrap;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🛒 ポチポチツール")

main_tab, settings_tab = st.tabs(["承認キュー", "巡回先管理"])

categories = load_categories()
category_labels = ["すべて"] + [f'{c.get("icon") or "🏷️"} {c["name"]}' for c in categories]
category_ids = [None] + [c["id"] for c in categories]

with main_tab:
    category_tabs = st.tabs(category_labels)
    for tab, category_id in zip(category_tabs, category_ids):
        with tab:
            keywords = load_unregistered_keywords(category_id)
            if not keywords:
                st.info("未登録ワードはありません")
            for row in keywords:
                with st.container(border=True):
                    st.markdown(f"**{row['keyword']}**  ({row['count']}件)")
                    if row.get("sample_context"):
                        st.caption(row["sample_context"])
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("⭕ 承認", key=f"approve_{row['id']}", use_container_width=True):
                            target_category_id = row.get("predicted_category_id") or category_id
                            approve_keyword(row, target_category_id)
                            st.cache_data.clear()
                            st.rerun()
                    with col2:
                        if st.button("❌ 却下", key=f"reject_{row['id']}", use_container_width=True):
                            reject_keyword(row)
                            st.cache_data.clear()
                            st.rerun()

with settings_tab:
    st.subheader("巡回先一覧")
    sources = load_sources()
    for src in sources:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.markdown(f"**{src['name']}**")
            st.caption(src["rss_url"])
        with col2:
            is_active = st.toggle(
                "ON/OFF",
                value=src["is_active"],
                key=f"source_toggle_{src['id']}",
                label_visibility="collapsed",
            )
            if is_active != src["is_active"]:
                toggle_source(src["id"], is_active)
                st.cache_data.clear()
                st.rerun()

    st.divider()
    st.subheader("新規巡回先の追加")
    with st.form("add_source_form", clear_on_submit=True):
        name = st.text_input("サイト名")
        rss_url = st.text_input("RSS URL")
        category_options = {c["name"]: c["id"] for c in categories}
        category_name = st.selectbox(
            "デフォルトカテゴリ", list(category_options.keys()) if category_options else ["未分類"]
        )
        submitted = st.form_submit_button("追加", use_container_width=True)
        if submitted:
            if name and rss_url:
                add_source(name, rss_url, category_options.get(category_name))
                st.cache_data.clear()
                st.success("追加しました")
                st.rerun()
            else:
                st.warning("サイト名とURLを入力してください")
