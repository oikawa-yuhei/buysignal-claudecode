import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import streamlit as st

from src.batch import run as run_batch
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


@st.cache_data(ttl=15)
def load_products(category_id):
    query = client.table("products").select("*").order("created_at", desc=True)
    if category_id is not None:
        query = query.eq("category_id", category_id)
    return query.execute().data or []


@st.cache_data(ttl=15)
def load_blacklist():
    return client.table("blacklist").select("*").order("created_at", desc=True).execute().data or []


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


def delete_source(source_id):
    client.table("sources").delete().eq("id", source_id).execute()


def add_source(name, rss_url, category_id):
    client.table("sources").insert(
        {"name": name, "rss_url": rss_url, "category_id": category_id, "is_active": True}
    ).execute()


def add_category(name, seed_keywords, icon):
    client.table("categories").insert(
        {"name": name, "seed_keywords": seed_keywords, "icon": icon}
    ).execute()


def delete_category(category_id):
    client.table("categories").delete().eq("id", category_id).execute()


def delete_product(product_id):
    client.table("products").delete().eq("id", product_id).execute()


def delete_blacklist_entry(blacklist_id):
    client.table("blacklist").delete().eq("id", blacklist_id).execute()


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

main_tab, history_tab, settings_tab, category_tab = st.tabs(
    ["承認キュー", "履歴", "巡回先管理", "カテゴリ管理"]
)

categories = load_categories()
category_labels = ["すべて"] + [f'{c.get("icon") or "🏷️"} {c["name"]}' for c in categories]
category_ids = [None] + [c["id"] for c in categories]

with main_tab:
    if st.button("🔄 今すぐ巡回実行", use_container_width=True):
        with st.spinner("巡回中..."):
            run_batch()
        st.cache_data.clear()
        st.success("巡回が完了しました")
        st.rerun()

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

with history_tab:
    approved_tab, rejected_tab = st.tabs(["⭕ 承認済み", "❌ 却下済み"])

    with approved_tab:
        approved_category_tabs = st.tabs(category_labels)
        for tab, category_id in zip(approved_category_tabs, category_ids):
            with tab:
                products = load_products(category_id)
                if not products:
                    st.info("承認済みの商品はありません")
                for product in products:
                    with st.container(border=True):
                        col1, col2 = st.columns([4, 1])
                        with col1:
                            st.markdown(f"**{product['name']}**")
                            st.caption(product["regex_pattern"])
                        with col2:
                            if st.button(
                                "🗑️",
                                key=f"delete_product_btn_{product['id']}",
                                use_container_width=True,
                            ):
                                st.session_state[f"confirm_delete_product_{product['id']}"] = True

                        if st.session_state.get(f"confirm_delete_product_{product['id']}"):
                            st.warning(f"「{product['name']}」の承認を取り消しますか？")
                            confirm_col1, confirm_col2 = st.columns(2)
                            with confirm_col1:
                                if st.button(
                                    "はい、取り消す",
                                    key=f"confirm_delete_product_yes_{product['id']}",
                                    use_container_width=True,
                                ):
                                    delete_product(product["id"])
                                    del st.session_state[f"confirm_delete_product_{product['id']}"]
                                    st.cache_data.clear()
                                    st.rerun()
                            with confirm_col2:
                                if st.button(
                                    "キャンセル",
                                    key=f"confirm_delete_product_no_{product['id']}",
                                    use_container_width=True,
                                ):
                                    del st.session_state[f"confirm_delete_product_{product['id']}"]
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

with settings_tab:
    st.subheader("巡回先一覧")
    sources = load_sources()
    for src in sources:
        with st.container(border=True):
            col1, col2, col3 = st.columns([3, 1, 1])
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
            with col3:
                if st.button("🗑️", key=f"delete_btn_{src['id']}", use_container_width=True):
                    st.session_state[f"confirm_delete_{src['id']}"] = True

            if st.session_state.get(f"confirm_delete_{src['id']}"):
                st.warning(f"「{src['name']}」を削除しますか？この操作は取り消せません。")
                confirm_col1, confirm_col2 = st.columns(2)
                with confirm_col1:
                    if st.button(
                        "はい、削除する",
                        key=f"confirm_delete_yes_{src['id']}",
                        use_container_width=True,
                    ):
                        delete_source(src["id"])
                        del st.session_state[f"confirm_delete_{src['id']}"]
                        st.cache_data.clear()
                        st.rerun()
                with confirm_col2:
                    if st.button(
                        "キャンセル",
                        key=f"confirm_delete_no_{src['id']}",
                        use_container_width=True,
                    ):
                        del st.session_state[f"confirm_delete_{src['id']}"]
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

with category_tab:
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

    st.divider()
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
