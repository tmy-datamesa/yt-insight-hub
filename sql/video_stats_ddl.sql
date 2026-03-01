-- =============================================================================
-- VIDEO STATS (izlenme, begeni, yorum sayisi - video bazli)
-- =============================================================================
-- Amac: YouTube videos.list API (statistics + snippet) ile alinan video bilgileri.
-- Kaynak: backend/ingestion/fetch_youtube_comments.py (fetch sonrasi cagrilir)
-- Dataset: yt_insight_raw
-- Tablo:   video_stats
-- =============================================================================

CREATE TABLE IF NOT EXISTS `yt_insight_raw.video_stats` (
  video_id          STRING,
  channel_id        STRING,
  video_title       STRING,
  channel_title     STRING,

  view_count        INT64,
  like_count        INT64,
  comment_count     INT64,

  published_at      TIMESTAMP,

  fetched_at        TIMESTAMP
);
