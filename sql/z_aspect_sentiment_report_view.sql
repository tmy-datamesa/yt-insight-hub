-- =============================================================================
-- ASPECT SENTIMENT RAPORLAMA VIEW (Looker / grafikler için düz tablo)
-- =============================================================================
-- Amaç: comment_insights içindeki aspects dizisini satır satır açar;
--       video/kanal bilgisi ile birlikte aspect bazlı tablo ve grafik yapılır.
-- Dataset: yt_insight_ml
-- View:    aspect_sentiment_report
-- =============================================================================

CREATE OR REPLACE VIEW `yt_insight_ml.aspect_sentiment_report` AS
WITH latest_run AS (
  SELECT
    comment_id,
    video_id,
    channel_id,
    model_name,
    general_sentiment,
    topic,
    aspects,
    ROW_NUMBER() OVER (
      PARTITION BY video_id, comment_id
      ORDER BY inference_ts DESC
    ) AS rn
  FROM `yt_insight_ml.comment_insights`
  WHERE aspects IS NOT NULL AND ARRAY_LENGTH(aspects) > 0
),
video_stats_latest AS (
  SELECT
    video_id,
    channel_id,
    video_title,
    channel_title
  FROM `yt_insight_raw.video_stats`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY fetched_at DESC) = 1
)
SELECT
  l.comment_id,
  l.video_id,
  l.channel_id,
  l.model_name,
  l.general_sentiment AS comment_sentiment,
  l.topic AS comment_topic,
  asp.aspect,
  asp.sentiment AS aspect_sentiment,
  asp.evidence,
  COALESCE(vs.video_title, l.video_id) AS video_title,
  COALESCE(vs.channel_title, l.channel_id) AS channel_title
FROM latest_run l
CROSS JOIN UNNEST(l.aspects) AS asp
LEFT JOIN video_stats_latest vs
  ON l.video_id = vs.video_id AND l.channel_id = vs.channel_id
WHERE l.rn = 1;
