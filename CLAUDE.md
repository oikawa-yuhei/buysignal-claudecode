# BuySignal Engine & ポチポチツール 開発ガイドライン

## 1. プロジェクト概要
- 目的: DB管理の動的巡回先（`sources`）から毎時テキスト収集し、バズ(z-score)×価格下落(Price Drop)のBuySignalを検出するシステム。
- 特徴: 未知語を共起キーワードで自動カテゴリ推測し、スマホWeb UI（ポチポチツール）で人間がワンタップ承認（Human-in-the-loop）する。
- 汎用性: 
  - `sources` テーブルにURLを追加するだけで、コード変更なしで巡回先メディアを無限追加可能。
  - `categories` テーブルに1行追加するだけで新ジャンルを無限展開可能。

## 2. トークン節約ルール (厳守)
- **応答出力:** 挨拶や長い解説、コードの説明は一切不要。変更理由も1行程度で済ませ、作成/更新したファイルパスとコードのみを出力すること。
- **コード編集:** ファイル全体を再出力せず、変更が必要な差分または最小限のモジュール単位で出力・書き込みを行うこと。
- **検索最小化:** 不要なディレクトリ全体検索（Grep/Find）を避け、指示されたファイルのみをピンポイントで読み込むこと。

## 3. 技術スタック
- DB: Supabase (PostgreSQL)
- Backend: Python 3.11+ (feedparser, pandas, numpy, supabase)
- Frontend: Streamlit (スマホ最適化UI)
- Architecture: 毎時バッチ処理 ($O(1)$ スケーリング)

## 4. ディレクトリ構造
buy-signal/
├── CLAUDE.md
├── docs/             # 仕様書
├── sql/              # Supabase用 DDL
├── src/              # バッチ処理 (collector, parser, evaluator, config)
├── scripts/          # 初期データ投入・動作テスト用スクリプト
└── app/              # ポチポチツール (Streamlit UI)
