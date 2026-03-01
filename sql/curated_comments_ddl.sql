-- =============================================================================
-- CURATED COMMENTS TABLE
-- =============================================================================
-- Amaç: Analize hazır yorumlar (temiz metin, dil tespiti, token sayısı).
-- Kaynak: backend/ingestion/curate_comments.py (raw -> curated dönüşümü)
-- Dataset: yt_insight_core
-- Tablo:   comments_curated
-- =============================================================================

CREATE TABLE IF NOT EXISTS `yt_insight_core.comments_curated` (
  comment_id         STRING,
  video_id           STRING,
  channel_id         STRING,

  text_clean         STRING,
  language           STRING,
  is_turkish         BOOL,

  is_reply           BOOL,
  parent_id          STRING,
  author_channel_id  STRING,   -- kanal sahibi cevabı: author_channel_id = channel_id

  like_count         INT64,

  comment_len_chars  INT64,
  comment_len_tokens INT64,

  curated_at         TIMESTAMP
);

