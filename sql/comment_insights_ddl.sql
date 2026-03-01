-- =============================================================================
-- COMMENT INSIGHTS (LLM PREDICTIONS)
-- =============================================================================
-- Amaç: LLM'in ürettiği general_sentiment, topic, aspect-based sentiment.
-- Kaynak: backend/inference/comment_insights.py
-- Idempotent: (comment_id, model_name, prompt_version) kombinasyonu unique
-- Dataset: yt_insight_ml
-- Tablo:   comment_insights
-- =============================================================================

CREATE TABLE IF NOT EXISTS `yt_insight_ml.comment_insights` (
  -- Identity
  comment_id        STRING,
  video_id          STRING,
  channel_id        STRING,

  model_name        STRING,

  -- General sentiment
  general_sentiment STRING,  -- positive | negative | neutral

  -- Topic (main subject of the comment)
  topic             STRING,

  -- Aspect-based sentiment
  aspects ARRAY<STRUCT<
    aspect   STRING,
    sentiment STRING,
    evidence STRING
  >>,

  -- Strategic signals (sektör içgörüsü: satın alma niyeti, soru, rakip kıyası)
  purchase_intent     BOOL,
  is_question         BOOL,
  competitor_mention  BOOL,

  -- Meta
  inference_ts      TIMESTAMP,
  inference_run_id  STRING,

  temperature       FLOAT64,
  max_tokens        INT64,

  raw_response      JSON
);

