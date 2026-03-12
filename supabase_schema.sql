-- supabase_schema.sql
-- Run this in the Supabase SQL Editor (Dashboard → SQL Editor → New query)
-- before running build_supabase.py.
--
-- Requires: the pgvector extension must be enabled for your Supabase project.
-- Dashboard → Database → Extensions → search "vector" → Enable.

-- ─────────────────────────────────────────────────────────────────────────────
-- Enable the vector extension
-- ─────────────────────────────────────────────────────────────────────────────
create extension if not exists vector;


-- ─────────────────────────────────────────────────────────────────────────────
-- Main table
-- ─────────────────────────────────────────────────────────────────────────────
create table if not exists tv_scenes (

  -- Document identity
  id                  text        primary key,        -- e.g. "big_bang_theory_s03e14sc00002"
  content             text        not null,           -- full scene or exemplar text
  embedding           vector(384) not null,           -- all-MiniLM-L6-v2 (384-dim)

  -- Metadata
  show                text        not null default '', -- "big_bang_theory" | "the_office"
  doc_type            text        not null default '', -- "canon" | "exemplar"
  season              integer     not null default 0,
  episode             integer     not null default 0,
  scene               integer     not null default 0,
  characters_present  text        not null default '[]', -- JSON-encoded list of names
  episode_title       text        not null default '',
  turn_idx            integer,                           -- exemplar only; null for canon

  -- Boolean character-presence flags (supported characters only)
  -- Add a new column here + in build_supabase.py when adding a new character
  has_sheldon         boolean     not null default false,
  has_michael         boolean     not null default false,
  has_dwight          boolean     not null default false
);


-- ─────────────────────────────────────────────────────────────────────────────
-- HNSW vector index — cosine distance, optimised for all-MiniLM-L6-v2
-- (m=16, ef_construction=64 are standard starting values)
-- ─────────────────────────────────────────────────────────────────────────────
create index if not exists tv_scenes_embedding_idx
  on tv_scenes
  using hnsw (embedding vector_cosine_ops)
  with (m = 16, ef_construction = 64);


-- ─────────────────────────────────────────────────────────────────────────────
-- Metadata indexes — speeds up the WHERE clauses in match_tv_scenes
-- ─────────────────────────────────────────────────────────────────────────────
create index if not exists tv_scenes_show_idx
  on tv_scenes (show);

create index if not exists tv_scenes_doc_type_idx
  on tv_scenes (doc_type);

create index if not exists tv_scenes_show_doc_type_idx
  on tv_scenes (show, doc_type);


-- ─────────────────────────────────────────────────────────────────────────────
-- RPC: match_tv_scenes
--
-- Returns the closest rows filtered by show, doc_type, and a character-presence
-- boolean column.  The character column name is dynamic (e.g. "has_sheldon"),
-- so we use plpgsql with format() + %I to quote it safely — no SQL injection.
--
-- Parameters:
--   query_embedding   — 384-dim query vector
--   filter_show       — "big_bang_theory" or "the_office"
--   filter_doc_type   — "canon" or "exemplar"
--   filter_char_col   — column name, e.g. "has_sheldon"
--   match_count       — how many rows to return (default: 20)
--
-- Returns rows ordered by cosine distance (nearest first).
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function match_tv_scenes(
  query_embedding   vector(384),
  filter_show       text,
  filter_doc_type   text,
  filter_char_col   text,
  match_count       int  default 20
)
returns table (
  id                  text,
  content             text,
  show                text,
  doc_type            text,
  season              integer,
  episode             integer,
  scene               integer,
  characters_present  text,
  episode_title       text,
  turn_idx            integer,
  distance            double precision
)
language plpgsql
as $$
begin
  return query execute format(
    $q$
      select
        id,
        content,
        show,
        doc_type,
        season,
        episode,
        scene,
        characters_present,
        episode_title,
        turn_idx,
        (embedding <=> $1)::double precision as distance
      from tv_scenes
      where show     = $2
        and doc_type = $3
        and %I = true
      order by embedding <=> $1
      limit $4
    $q$,
    filter_char_col   -- safely quoted column name via %I
  )
  using query_embedding, filter_show, filter_doc_type, match_count;
end;
$$;


-- ─────────────────────────────────────────────────────────────────────────────
-- Helper: truncate_tv_scenes
-- Called by build_supabase.py --reset to wipe the table before a full reingest.
-- Defined as a function so the service-role client can invoke it via RPC
-- without needing direct DDL permissions.
-- ─────────────────────────────────────────────────────────────────────────────
create or replace function truncate_tv_scenes()
returns void
language plpgsql
as $$
begin
  truncate table tv_scenes;
end;
$$;
