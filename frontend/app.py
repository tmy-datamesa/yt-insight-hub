"""
Streamlit dashboard: video seç → özet metrikler, sentiment/topic grafikleri, yorum tablosu.
Veri: BigQuery (load_videos, load_insights). Çalıştırma: make streamlit
"""

import os
import pandas as pd
import streamlit as st
from google.cloud import bigquery

from backend.config.settings import gcp_settings, bq_tables


@st.cache_resource
def get_bq_client():
    if not gcp_settings.project_id:
        raise RuntimeError("GCP_PROJECT_ID must be set.")
    return bigquery.Client(project=gcp_settings.project_id, location=gcp_settings.location)


def load_videos():
    """Video listesi: video_id, n_comments, video_title, channel_title, view_count, like_count, published_at."""
    client = get_bq_client()
    core = f"{gcp_settings.project_id}.{gcp_settings.dataset_core}.{bq_tables.curated_comments}"
    raw = f"{gcp_settings.project_id}.{gcp_settings.dataset_raw}.{bq_tables.raw_comments}"
    stats = f"{gcp_settings.project_id}.{gcp_settings.dataset_raw}.{bq_tables.video_stats}"
    q = f"""
    WITH agg AS (
      SELECT c.video_id, c.channel_id, COUNT(DISTINCT c.comment_id) AS n_comments,
             COALESCE(ANY_VALUE(r.video_title), c.video_id) AS video_title,
             COALESCE(ANY_VALUE(r.channel_title), c.channel_id) AS channel_title
      FROM `{core}` c
      LEFT JOIN `{raw}` r ON c.video_id = r.video_id AND c.channel_id = r.channel_id
      GROUP BY c.video_id, c.channel_id
    ),
    s AS (
      SELECT video_id, channel_id, view_count, like_count, published_at
      FROM `{stats}` QUALIFY ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY fetched_at DESC) = 1
    )
    SELECT a.*, s.view_count, s.like_count, s.published_at
    FROM agg a LEFT JOIN s ON a.video_id = s.video_id AND a.channel_id = s.channel_id
    ORDER BY a.n_comments DESC
    """
    return client.query(q).result().to_dataframe()


def load_insights(video_id: str):
    """Seçilen videonun LLM sonuçları + yorum metni (en son run)."""
    client = get_bq_client()
    pred = f"{gcp_settings.project_id}.{gcp_settings.dataset_ml}.{bq_tables.comment_insights}"
    cur = f"{gcp_settings.project_id}.{gcp_settings.dataset_core}.{bq_tables.curated_comments}"
    q = f"""
    WITH latest AS (
      SELECT model_name FROM (
        SELECT model_name, MAX(inference_ts) AS mt FROM `{pred}` WHERE video_id = @vid GROUP BY model_name
      ) ORDER BY mt DESC LIMIT 1
    )
    SELECT p.comment_id, p.general_sentiment, p.topic, p.aspects, p.purchase_intent,
           p.is_question, p.competitor_mention, c.text_clean, c.is_reply, c.author_channel_id, c.channel_id
    FROM `{pred}` p
    INNER JOIN latest l ON p.model_name = l.model_name
    JOIN `{cur}` c ON p.comment_id = c.comment_id
    WHERE p.video_id = @vid
    """
    job = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("vid", "STRING", video_id)])
    return client.query(q, job_config=job).result().to_dataframe()


def main():
    st.set_page_config(page_title="YT Comment Insights", layout="wide")
    st.sidebar.header("Video seç")
    videos = load_videos()
    if videos.empty:
        st.info("Henüz veri yok. Pipeline çalıştır: fetch-comments → curate-comments → run-inference.")
        return

    opts = [f"{r.channel_title} — {r.video_title} ({r.n_comments})" for _, r in videos.iterrows()]
    idx = videos.index[0] if len(videos) > 0 else 0
    sel = st.sidebar.selectbox("Video", opts, label_visibility="collapsed")
    video_id = videos.iloc[opts.index(sel) if sel in opts else 0]["video_id"]

    df = load_insights(video_id)
    if df.empty:
        st.warning("Bu video için analiz yok.")
        st.code(f"make run-inference VIDEO_ID={video_id}", language="bash")
        return

    row = videos[videos["video_id"] == video_id].iloc[0]
    st.title("YouTube Comment Insights")
    st.caption(f"{row['channel_title']} — {row['video_title']}")

    # Özet: 5 metrik
    r = row
    n_pos = (df["general_sentiment"] == "positive").sum()
    pct = round(100 * n_pos / len(df)) if len(df) else 0
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Views", f"{int(r.get('view_count') or 0):,}" if pd.notna(r.get("view_count")) else "—")
    c2.metric("Likes", f"{int(r.get('like_count') or 0):,}" if pd.notna(r.get("like_count")) else "—")
    c3.metric("Yorum (analiz)", len(df))
    c4.metric("Positive %", f"%{pct}")
    c5.metric("Published", str(r.get("published_at"))[:10] if pd.notna(r.get("published_at")) else "—")

    # Sentiment & topic: Streamlit bar_chart (basit)
    st.subheader("Sentiment")
    sent = df["general_sentiment"].value_counts().reset_index()
    sent.columns = ["sentiment", "count"]
    st.bar_chart(sent.set_index("sentiment"))

    st.subheader("Topic (ilk 10)")
    top = df["topic"].value_counts().head(10).reset_index()
    top.columns = ["topic", "count"]
    st.bar_chart(top.set_index("topic"))

    # Aspect tablosu (varsa)
    rows = []
    for _, r in df.iterrows():
        val = r.get("aspects")
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        lst = val if isinstance(val, list) else (val.tolist() if hasattr(val, "tolist") else [])
        for a in lst:
            if isinstance(a, dict):
                rows.append({"aspect": a.get("aspect"), "sentiment": a.get("sentiment")})
    if rows:
        asp = pd.DataFrame(rows)
        pivot = asp.pivot_table(index="aspect", columns="sentiment", aggfunc="size", fill_value=0)
        if "negative" in pivot.columns:
            pivot = pivot.sort_values("negative", ascending=False)
        st.subheader("Aspect × Sentiment")
        st.dataframe(pivot, use_container_width=True)

    # Yorum listesi (basit filtre)
    st.subheader("Yorumlar")
    filt_sent = st.selectbox("Sentiment filtre", ["Tümü"] + sorted(df["general_sentiment"].dropna().unique().tolist()))
    show = df if filt_sent == "Tümü" else df[df["general_sentiment"] == filt_sent]
    cols = ["general_sentiment", "topic", "text_clean"]
    if "purchase_intent" in show.columns:
        cols.append("purchase_intent")
    out = show[cols].rename(columns={"general_sentiment": "Sentiment", "topic": "Topic", "text_clean": "Yorum", "purchase_intent": "Satın alma niyeti"})
    st.dataframe(out, use_container_width=True, height=400)


if __name__ == "__main__":
    main()
