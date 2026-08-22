-- BuySignal DB Schema (Supabase / PostgreSQL)

create table if not exists categories (
  id bigint generated always as identity primary key,
  name text not null unique,
  seed_keywords text[] not null default '{}',
  icon text,
  created_at timestamptz not null default now()
);

create table if not exists sources (
  id bigint generated always as identity primary key,
  name text not null,
  rss_url text not null unique,
  is_active boolean not null default true,
  category_id bigint references categories(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists idx_sources_category_id on sources(category_id);
create index if not exists idx_sources_is_active on sources(is_active);

create table if not exists products (
  id bigint generated always as identity primary key,
  name text not null unique,
  regex_pattern text not null,
  category_id bigint references categories(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists idx_products_category_id on products(category_id);

create table if not exists unregistered_keywords (
  id bigint generated always as identity primary key,
  keyword text not null,
  predicted_category_id bigint references categories(id) on delete set null,
  brand_name text,
  count integer not null default 1,
  sample_context text,
  updated_at timestamptz not null default now()
);

create unique index if not exists idx_unregistered_keywords_keyword on unregistered_keywords(keyword);
create index if not exists idx_unregistered_keywords_predicted_category_id on unregistered_keywords(predicted_category_id);

create table if not exists brands (
  id bigint generated always as identity primary key,
  name text not null unique,
  category_id bigint references categories(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists idx_brands_category_id on brands(category_id);

create table if not exists product_aliases (
  id bigint generated always as identity primary key,
  alias text not null unique,
  canonical_name text not null,
  category_id bigint references categories(id) on delete set null,
  created_at timestamptz not null default now()
);

create index if not exists idx_product_aliases_category_id on product_aliases(category_id);

create table if not exists processed_entries (
  id bigint generated always as identity primary key,
  source_id bigint not null references sources(id) on delete cascade,
  entry_id text not null,
  processed_at timestamptz not null default now()
);

create unique index if not exists idx_processed_entries_source_entry on processed_entries(source_id, entry_id);

create table if not exists blacklist (
  id bigint generated always as identity primary key,
  keyword text not null unique,
  created_at timestamptz not null default now()
);

create table if not exists daily_buzz_logs (
  id bigint generated always as identity primary key,
  product_id bigint not null references products(id) on delete cascade,
  logged_at date not null,
  count integer not null default 0,
  updated_at timestamptz not null default now()
);

create unique index if not exists idx_daily_buzz_logs_product_date on daily_buzz_logs(product_id, logged_at);

create table if not exists buy_signals (
  id bigint generated always as identity primary key,
  product_id bigint not null references products(id) on delete cascade,
  score numeric not null,
  buzz_zscore numeric,
  price_drop_rate numeric,
  created_at timestamptz not null default now()
);

create index if not exists idx_buy_signals_product_id on buy_signals(product_id);
create index if not exists idx_buy_signals_created_at on buy_signals(created_at);
