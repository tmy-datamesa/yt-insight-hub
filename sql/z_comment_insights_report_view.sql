-- =============================================================================
-- LOOKER STUDIO / RAPORLAMA VIEW
-- =============================================================================
-- Amac: comment_insights + curated + raw birlestirimi; video/channel basliklari
--       ve "en son run" ile tek satir per yorum. Looker Studio bu view'e baglanir.
-- Dataset: yt_insight_ml
-- View:    comment_insights_report
-- =============================================================================

CREATE OR REPLACE VIEW `yt_insight_ml.comment_insights_report` AS
WITH latest_run AS (
  SELECT
    comment_id,
    video_id,
    channel_id,
    model_name,
    general_sentiment,
    topic,
    aspects,
    purchase_intent,
    is_question,
    competitor_mention,
    inference_ts,
    ROW_NUMBER() OVER (
      PARTITION BY video_id, comment_id
      ORDER BY inference_ts DESC
    ) AS rn
  FROM `yt_insight_ml.comment_insights`
),
raw_titles AS (
  SELECT
    video_id,
    channel_id,
    video_title,
    channel_title
  FROM `yt_insight_raw.comments`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY video_id, channel_id ORDER BY ingested_at DESC) = 1
),
video_stats_latest AS (
  SELECT
    video_id,
    channel_id,
    video_title,
    channel_title,
    view_count,
    like_count,
    comment_count,
    published_at AS video_published_at
  FROM `yt_insight_raw.video_stats`
  QUALIFY ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY fetched_at DESC) = 1
)
SELECT
  l.comment_id,
  l.video_id,
  l.channel_id,
  l.model_name,
  l.general_sentiment,
  l.topic,
  l.purchase_intent,
  l.is_question,
  l.competitor_mention,
  l.inference_ts,
  c.text_clean,
  c.is_reply,
  c.author_channel_id,
  c.like_count AS comment_like_count,
  (c.author_channel_id IS NOT NULL AND c.author_channel_id = c.channel_id) AS is_creator_reply,
  -- comment_type: business-friendly label for Looker/BI
  CASE
    WHEN (c.author_channel_id IS NOT NULL AND c.author_channel_id = c.channel_id) THEN 'Creator reply'
    WHEN c.is_reply THEN 'Reply'
    ELSE 'Top-level'
  END AS comment_type,
  -- intent_category: business intent (first match wins)
  CASE
    WHEN l.purchase_intent = TRUE THEN 'Pre-Purchase Intent'
    WHEN l.competitor_mention = TRUE THEN 'Comparison'
    WHEN l.is_question = TRUE THEN 'Information Seeking'
    WHEN l.general_sentiment = 'negative' AND l.topic IN ('product_review', 'performance_discussion', 'price_discussion', 'battery_discussion', 'camera_discussion', 'software_ui', 'sponsorship_trust', 'channel_trust') THEN 'Complaint'
    WHEN l.topic IN ('product_review', 'performance_discussion', 'battery_discussion', 'camera_discussion', 'software_ui') AND l.general_sentiment IN ('positive', 'negative') THEN 'Post-Purchase'
    WHEN l.topic = 'offtopic' OR l.topic IS NULL THEN 'Irrelevant'
    ELSE 'Other'
  END AS intent_category,
  COALESCE(vs.video_title, r.video_title, l.video_id) AS video_title,
  COALESCE(vs.channel_title, r.channel_title, l.channel_id) AS channel_title,
  vs.view_count,
  vs.like_count AS video_like_count,
  vs.comment_count AS video_comment_count,
  vs.video_published_at
FROM latest_run l
JOIN `yt_insight_core.comments_curated` c
  ON l.comment_id = c.comment_id
  AND l.video_id = c.video_id
  AND l.channel_id = c.channel_id
LEFT JOIN raw_titles r
  ON l.video_id = r.video_id
  AND l.channel_id = r.channel_id
LEFT JOIN video_stats_latest vs
  ON l.video_id = vs.video_id
  AND l.channel_id = vs.channel_id
WHERE l.rn = 1;
