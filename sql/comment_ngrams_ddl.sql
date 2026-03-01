-- =============================================================================
-- COMMENT N-GRAMS (kelime / kelime öbeği frekansları – word cloud, bigram, trigram)
-- =============================================================================
-- Amaç: comment_insights_report.text_clean üzerinden 1/2/3-gram sayımları.
--       Looker'da kelime bulutu veya "en sık geçen ifadeler" grafikleri için.
-- Doldurma: backend/analytics/build_ngrams.py (make build-ngrams)
-- Dataset: yt_insight_ml
-- Tablo:   comment_ngrams
-- =============================================================================

CREATE TABLE IF NOT EXISTS `yt_insight_ml.comment_ngrams` (
  video_id       STRING,
  channel_id     STRING,
  n              INT64,   -- 1=unigram, 2=bigram, 3=trigram
  phrase         STRING,
  phrase_count   INT64,
  updated_at      TIMESTAMP
);
