import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


def _get_secret(key: str) -> str:
    if key in os.environ:
        return os.environ[key]
    try:
        import streamlit as st

        return st.secrets[key]
    except Exception:
        raise KeyError(key)


SUPABASE_URL = _get_secret("SUPABASE_URL")
SUPABASE_KEY = _get_secret("SUPABASE_KEY")


def get_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def get_youtube_api_key():
    try:
        return _get_secret("YOUTUBE_API_KEY")
    except KeyError:
        return None
