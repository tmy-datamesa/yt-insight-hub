-- =============================================================================
-- RAW COMMENTS TABLE
-- =============================================================================
-- Amaç: YouTube Data API commentThreads response'larının kayıpsız saklanması.
-- Kaynak: backend/ingestion/fetch_youtube_comments.py
-- Dataset: yt_insight_raw
-- Tablo:   comments
-- =============================================================================

CREATE TABLE IF NOT EXISTS `yt_insight_raw.comments` (
  channel_id           STRING,
  channel_title        STRING,
  video_id             STRING,
  video_title          STRING,
  video_published_at   TIMESTAMP,

  comment_id           STRING,
  parent_id            STRING,
  is_top_level         BOOL,

  author_channel_id    STRING,
  author_display_name  STRING,

  text_original        STRING,
  text_display         STRING,

  like_count           INT64,
  published_at         TIMESTAMP,
  updated_at           TIMESTAMP,

  raw_payload          JSON,

  ingested_at          TIMESTAMP
);

