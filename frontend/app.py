"""
Streamlit dashboard: video bazında yorum insight'ları.

Veri: BigQuery (load_videos = video listesi + stats; load_insights = seçilen videonun
      comment_insights + curated birleşimi). En son inference run kullanılır.
Akış: Sidebar'dan video seç → özet metrikler, intent/comment_type grafikleri,
      aspect tablosu, sık ifadeler (N-gram), yorum listesi (filtrelenebilir).
Çalıştırma: make streamlit  veya  streamlit run frontend/app.py
"""

import os
import re
from collections import Counter

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.cloud import bigquery

from backend.config.settings import gcp_settings, bq_tables


def _aspects_list(value) -> list:
    """
    BigQuery'den gelen aspects alanını (list / np.ndarray / None) her zaman
    Python list of dict'e çevirir. Grafik ve filtrelerde tekrar kullanılır.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, np.ndarray):
        return value.tolist()
    return []


# Koyu mor gradyan tema renkleri
THEME = {
    "bg_dark": "#0f0618",
    "bg_card": "rgba(45, 20, 70, 0.6)",
    "gradient_start": "#1a0a2e",
    "gradient_end": "#2d1444",
    "accent": "#9d4edd",
    "accent_light": "#c77dff",
    "text": "#e8ddf5",
    "text_muted": "#b8a0c9",
    "bar_colors": ["#7b2cbf", "#9d4edd", "#c77dff", "#e0aaff", "#f3d9ff"],
}

def apply_dark_theme():
    """Sayfa ve sidebar için koyu mor gradyan CSS uygular."""
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&display=swap');
        .stApp {{
            background: linear-gradient(165deg, {THEME["gradient_start"]} 0%, {THEME["bg_dark"]} 40%, {THEME["gradient_end"]} 100%);
            font-family: 'DM Sans', sans-serif;
        }}
        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, {THEME["gradient_end"]} 0%, {THEME["bg_dark"]} 100%);
        }}
        [data-testid="stSidebar"] .stSelectbox label {{
            color: {THEME["text"]} !important;
        }}
        h1, h2, h3 {{
            color: {THEME["text"]} !important;
        }}
        .stMetric label {{
            color: {THEME["text_muted"]} !important;
        }}
        .stMetric [data-testid="stMetricValue"] {{
            color: {THEME["accent_light"]} !important;
        }}
        [data-testid="stDataFrame"] {{
            border-radius: 10px;
            overflow: hidden;
            border: 1px solid rgba(157, 78, 221, 0.3);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def plotly_bar_layout(title: str):
    """Koyu mor temalı Plotly layout."""
    return go.Layout(
        title=dict(text=title, font=dict(color=THEME["text"], size=16)),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(30, 15, 50, 0.5)",
        font=dict(color=THEME["text_muted"], size=12),
        xaxis=dict(showgrid=True, gridcolor="rgba(157, 78, 221, 0.2)", zeroline=False),
        yaxis=dict(showgrid=True, gridcolor="rgba(157, 78, 221, 0.2)", zeroline=False),
        margin=dict(t=40, b=40, l=50, r=20),
        showlegend=False,
    )


def bar_chart_sentiment(sentiment_counts: pd.DataFrame):
    """Sentiment distribution bar chart."""
    color_map = {"positive": "#5c9e5c", "negative": "#c77dff", "neutral": "#9d4edd"}
    colors = [color_map.get(s, THEME["accent"]) for s in sentiment_counts["sentiment"]]
    fig = go.Figure(
        data=[
            go.Bar(
                x=sentiment_counts["sentiment"],
                y=sentiment_counts["count"],
                marker_color=colors,
                text=sentiment_counts["count"],
                textposition="outside",
                textfont=dict(color=THEME["text"]),
            )
        ],
        layout=plotly_bar_layout("Sentiment distribution"),
    )
    fig.update_xaxes(tickfont=dict(color=THEME["text"]))
    fig.update_yaxes(tickfont=dict(color=THEME["text_muted"]))
    return fig


def bar_chart_topic(topic_counts: pd.DataFrame):
    """Topic distribution bar chart."""
    n = len(topic_counts)
    bar_colors = THEME["bar_colors"]
    colors = [bar_colors[i % len(bar_colors)] for i in range(n)]
    fig = go.Figure(
        data=[
            go.Bar(
                x=topic_counts["topic"],
                y=topic_counts["count"],
                marker_color=colors,
                text=topic_counts["count"],
                textposition="outside",
                textfont=dict(color=THEME["text"]),
            )
        ],
        layout=plotly_bar_layout("Topic distribution"),
    )
    fig.update_xaxes(tickfont=dict(color=THEME["text"]), tickangle=-35)
    fig.update_yaxes(tickfont=dict(color=THEME["text_muted"]))
    return fig


def bar_chart_intent(intent_counts: pd.DataFrame):
    """Intent category distribution bar chart."""
    n = len(intent_counts)
    bar_colors = THEME["bar_colors"]
    colors = [bar_colors[i % len(bar_colors)] for i in range(n)]
    fig = go.Figure(
        data=[
            go.Bar(
                x=intent_counts["intent_category"],
                y=intent_counts["count"],
                marker_color=colors,
                text=intent_counts["count"],
                textposition="outside",
                textfont=dict(color=THEME["text"]),
            )
        ],
        layout=plotly_bar_layout("Intent distribution"),
    )
    fig.update_xaxes(tickfont=dict(color=THEME["text"]), tickangle=-25)
    fig.update_yaxes(tickfont=dict(color=THEME["text_muted"]))
    return fig


def bar_chart_comment_type(type_counts: pd.DataFrame):
    """Comment type (Top-level / Reply / Creator reply) bar chart."""
    color_map = {"Top-level": "#9d4edd", "Reply": "#c77dff", "Creator reply": "#5c9e5c"}
    colors = [color_map.get(t, THEME["accent"]) for t in type_counts["comment_type"]]
    fig = go.Figure(
        data=[
            go.Bar(
                x=type_counts["comment_type"],
                y=type_counts["count"],
                marker_color=colors,
                text=type_counts["count"],
                textposition="outside",
                textfont=dict(color=THEME["text"]),
            )
        ],
        layout=plotly_bar_layout("Comment type"),
    )
    fig.update_xaxes(tickfont=dict(color=THEME["text"]))
    fig.update_yaxes(tickfont=dict(color=THEME["text_muted"]))
    return fig


def compute_intent_category(row: pd.Series) -> str:
    """Report view ile aynı mantık: öncelik sırasına göre intent atar."""
    if row.get("purchase_intent") is True:
        return "Pre-Purchase Intent"
    if row.get("competitor_mention") is True:
        return "Comparison"
    if row.get("is_question") is True:
        return "Information Seeking"
    sent, topic = row.get("general_sentiment"), row.get("topic")
    if sent == "negative" and topic in (
        "product_review", "performance_discussion", "price_discussion",
        "battery_discussion", "camera_discussion", "software_ui",
        "sponsorship_trust", "channel_trust",
    ):
        return "Complaint"
    if topic in ("product_review", "performance_discussion", "battery_discussion", "camera_discussion", "software_ui") and sent in ("positive", "negative"):
        return "Post-Purchase"
    if topic == "offtopic" or pd.isna(topic):
        return "Irrelevant"
    return "Other"


def compute_comment_type(row: pd.Series) -> str:
    """Top-level / Reply / Creator reply (report view ile aynı)."""
    if row.get("is_creator_reply"):
        return "Creator reply"
    if row.get("is_reply"):
        return "Reply"
    return "Top-level"


def compute_ngrams_from_texts(texts: pd.Series, n: int, min_count: int = 2) -> pd.DataFrame:
    """Metin serisinden n-gram sayımları (1=unigram, 2=bigram, 3=trigram)."""
    counts: Counter = Counter()
    for t in texts.dropna().astype(str):
        if not t or len(t.strip()) == 0:
            continue
        t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
        words = [w.replace("\u0130", "i").lower() for w in t.split() if w.strip()]
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i : i + n])
            if phrase.strip():
                counts[phrase] += 1
    rows = [{"phrase": p, "count": c} for p, c in counts.most_common(50) if c >= min_count]
    return pd.DataFrame(rows)


@st.cache_resource
def get_bq_client() -> bigquery.Client:
    """BigQuery client; cache_resource ile oturum boyunca tek instance."""
    if not gcp_settings.project_id:
        raise RuntimeError("GCP_PROJECT_ID must be set in environment.")
    return bigquery.Client(project=gcp_settings.project_id, location=gcp_settings.location)


def load_videos() -> pd.DataFrame:
    """
    Video listesi: video_id, channel_id, yorum sayısı, video başlığı, kanal adı,
    izlenme/begeni sayısı (video_stats varsa).
    """
    client = get_bq_client()
    core_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_core}.{bq_tables.curated_comments}"
    raw_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_raw}.{bq_tables.raw_comments}"
    stats_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_raw}.{bq_tables.video_stats}"
    query = f"""
    WITH agg AS (
      SELECT
        c.video_id,
        c.channel_id,
        COUNT(DISTINCT c.comment_id) AS n_comments,
        COALESCE(ANY_VALUE(r.video_title), c.video_id) AS video_title,
        COALESCE(ANY_VALUE(r.channel_title), c.channel_id) AS channel_title
      FROM `{core_table}` AS c
      LEFT JOIN `{raw_table}` AS r
        ON c.video_id = r.video_id AND c.channel_id = r.channel_id
      GROUP BY c.video_id, c.channel_id
    ),
    stats_latest AS (
      SELECT video_id, channel_id, view_count, like_count, comment_count, published_at
      FROM `{stats_table}`
      QUALIFY ROW_NUMBER() OVER (PARTITION BY video_id ORDER BY fetched_at DESC) = 1
    )
    SELECT
      a.video_id,
      a.channel_id,
      a.n_comments,
      a.video_title,
      a.channel_title,
      s.view_count,
      s.like_count,
      s.comment_count,
      s.published_at
    FROM agg a
    LEFT JOIN stats_latest s ON a.video_id = s.video_id AND a.channel_id = s.channel_id
    ORDER BY a.n_comments DESC
    """
    return client.query(query).result().to_dataframe()


def load_insights(video_id: str) -> pd.DataFrame:
    """
    Seçilen videonun LLM tahminlerini + yorum metnini döner.

    Sadece en son çalıştırılan run kullanılır (inference_ts en büyük model_name).
    """
    client = get_bq_client()
    pred_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_ml}.{bq_tables.comment_insights}"
    curated_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_core}.{bq_tables.curated_comments}"
    query = f"""
    WITH latest_run AS (
      SELECT model_name
      FROM (
        SELECT model_name, MAX(inference_ts) AS max_ts
        FROM `{pred_table}`
        WHERE video_id = @video_id
        GROUP BY model_name
      )
      ORDER BY max_ts DESC NULLS LAST
      LIMIT 1
    )
    SELECT
      p.comment_id,
      p.general_sentiment,
      p.topic,
      p.aspects,
      p.purchase_intent,
      p.is_question,
      p.competitor_mention,
      c.text_clean,
      c.parent_id,
      c.is_reply,
      c.author_channel_id,
      c.channel_id
    FROM `{pred_table}` AS p
    INNER JOIN latest_run AS l
      ON p.model_name = l.model_name
    JOIN `{curated_table}` AS c
      ON p.comment_id = c.comment_id
    WHERE p.video_id = @video_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("video_id", "STRING", video_id)]
    )
    return client.query(query, job_config=job_config).result().to_dataframe()


def main() -> None:
    """Dashboard – iş ekibi sunumuna uygun düzen."""
    st.set_page_config(
        page_title="YouTube Comment Insights",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_dark_theme()

    st.sidebar.header("Select video")
    videos_df = load_videos()
    if videos_df.empty:
        st.info("No curated comments yet. Run the data pipeline to list videos here.")
        return

    video_options = [
        f"{row.channel_title} — {row.video_title} ({row.n_comments} comments)"
        for _, row in videos_df.iterrows()
    ]
    video_options_to_id = {opt: videos_df.iloc[i].video_id for i, opt in enumerate(video_options)}
    selected = st.sidebar.selectbox("Choose a video", video_options, label_visibility="collapsed")
    selected_video_id = video_options_to_id.get(selected, videos_df.iloc[0].video_id)

    with st.sidebar.expander("Technical"):
        if not os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
            st.caption("GOOGLE_APPLICATION_CREDENTIALS required for BigQuery.")
        st.caption("Data: BigQuery · Analysis: LLM-based sentiment & topic")

    insights_df = load_insights(selected_video_id)
    if insights_df.empty:
        st.info("No analysis for this video yet. Run inference to see insights.")
        with st.expander("How to run analysis"):
            st.code(f"make run-inference VIDEO_ID={selected_video_id}", language="bash")
        return

    sel_row = videos_df[videos_df["video_id"] == selected_video_id].iloc[0]
    st.title("YouTube Comment Insights")
    st.caption(f"**{sel_row.channel_title}** — {sel_row.video_title}")

    # Kanal cevabı: yorumu kanal sahibi mi yazdı (author_channel_id == channel_id)
    if "author_channel_id" in insights_df.columns and "channel_id" in insights_df.columns:
        insights_df = insights_df.copy()
        insights_df["is_creator_reply"] = (
            insights_df["author_channel_id"].notna()
            & (insights_df["author_channel_id"] == insights_df["channel_id"])
        )
    else:
        insights_df["is_creator_reply"] = False

    # 1) Video key info (top of page)
    video_row = videos_df[videos_df["video_id"] == selected_video_id]
    r = video_row.iloc[0] if not video_row.empty else {}
    n_positive = (insights_df["general_sentiment"] == "positive").sum()
    pct_positive = round(100 * n_positive / len(insights_df)) if len(insights_df) else 0

    st.subheader("Video summary")
    v1, v2, v3, v4, v5 = st.columns(5)
    with v1:
        st.metric("Views", f"{int(r.get('view_count') or 0):,}" if pd.notna(r.get("view_count")) else "—")
    with v2:
        st.metric("Likes", f"{int(r.get('like_count') or 0):,}" if pd.notna(r.get("like_count")) else "—")
    with v3:
        st.metric("Comments analysed", len(insights_df))
    with v4:
        st.metric("Positive %", f"%{pct_positive}")
    with v5:
        pub = r.get("published_at")
        st.metric("Published", str(pub)[:10] if pub and pd.notna(pub) else "—")

    # 2) Channel engagement
    st.subheader("Channel engagement")
    n_total = len(insights_df)
    n_top_level = (insights_df["is_reply"] == False).sum()
    n_creator_replies = insights_df["is_creator_reply"].sum()
    parent_ids_with_creator_reply = insights_df.loc[
        insights_df["is_creator_reply"], "parent_id"
    ].dropna().unique()
    n_top_level_answered = len(parent_ids_with_creator_reply)
    reply_ratio = (n_top_level_answered / n_top_level * 100) if n_top_level else 0

    e1, e2, e3, e4 = st.columns(4)
    with e1:
        st.metric("Total comments", n_total)
    with e2:
        st.metric("Top-level", n_top_level)
    with e3:
        st.metric("Creator replies", n_creator_replies)
    with e4:
        st.metric("Top-level answered", f"{n_top_level_answered} ({reply_ratio:.0f}%)")

    # 3) Strategic signals
    st.subheader("Strategic signals")
    n_purchase = insights_df["purchase_intent"].fillna(False).sum() if "purchase_intent" in insights_df.columns else 0
    n_question = insights_df["is_question"].fillna(False).sum() if "is_question" in insights_df.columns else 0
    n_competitor = insights_df["competitor_mention"].fillna(False).sum() if "competitor_mention" in insights_df.columns else 0
    s1, s2, s3 = st.columns(3)
    with s1:
        st.metric("Purchase intent", n_purchase)
    with s2:
        st.metric("Contains question", n_question)
    with s3:
        st.metric("Competitor mention", n_competitor)

    # intent_category & comment_type (report view ile aynı mantık)
    insights_df["intent_category"] = insights_df.apply(compute_intent_category, axis=1)
    insights_df["comment_type"] = insights_df.apply(compute_comment_type, axis=1)

    # 4) Insights at a glance
    st.subheader("Insights at a glance")
    intent_counts = insights_df["intent_category"].value_counts().rename_axis("intent_category").reset_index(name="count")
    dominant_intent = intent_counts.iloc[0]["intent_category"] if not intent_counts.empty else "—"
    pct_pre = round(100 * (insights_df["intent_category"] == "Pre-Purchase Intent").sum() / len(insights_df)) if len(insights_df) else 0
    aspect_rows_insight = []
    for _, row in insights_df.iterrows():
        for a in _aspects_list(row.get("aspects")):
            if isinstance(a, dict) and a.get("aspect"):
                aspect_rows_insight.append({"aspect": a.get("aspect"), "sentiment": a.get("sentiment")})
    top_negative_aspect = "—"
    if aspect_rows_insight:
        asp_df = pd.DataFrame(aspect_rows_insight)
        neg = asp_df[asp_df["sentiment"] == "negative"].groupby("aspect").size().sort_values(ascending=False)
        top_negative_aspect = neg.index[0] if len(neg) else "—"
    i1, i2, i3 = st.columns(3)
    with i1:
        st.info(f"**Dominant intent:** {dominant_intent}")
    with i2:
        st.info(f"**Pre-Purchase Intent:** {pct_pre}% of comments")
    with i3:
        st.info(f"**Top negative aspect:** {top_negative_aspect}")

    # 5) Charts: Sentiment, Topic, Intent, Comment type
    if "chart_filter_topic" not in st.session_state:
        st.session_state["chart_filter_topic"] = "All"
    if "chart_filter_sentiment" not in st.session_state:
        st.session_state["chart_filter_sentiment"] = "All"

    sentiment_counts = (
        insights_df["general_sentiment"]
        .value_counts()
        .rename_axis("sentiment")
        .reset_index(name="count")
    )
    topic_counts = (
        insights_df["topic"]
        .value_counts()
        .rename_axis("topic")
        .reset_index(name="count")
        .head(10)
    )

    st.subheader("Sentiment, topic, intent & comment type")
    col1, col2 = st.columns(2)

    with col1:
        st.plotly_chart(
            bar_chart_sentiment(sentiment_counts),
            use_container_width=True,
            key="sentiment_chart",
        )
        st.caption("Select a sentiment to filter the table below.")
        chart_sent = st.selectbox(
            "Sentiment",
            options=["All"] + sorted(sentiment_counts["sentiment"].tolist()),
            key="chart_sentiment_select",
            label_visibility="collapsed",
        )
        st.session_state["chart_filter_sentiment"] = chart_sent if chart_sent != "All" else "All"

        st.plotly_chart(
            bar_chart_topic(topic_counts),
            use_container_width=True,
            key="topic_chart",
        )
        st.caption("Select a topic to filter the table below.")
        chart_topic = st.selectbox(
            "Topic",
            options=["All"] + topic_counts["topic"].tolist(),
            key="chart_topic_select",
            label_visibility="collapsed",
        )
        st.session_state["chart_filter_topic"] = chart_topic if chart_topic != "All" else "All"

        intent_counts_chart = insights_df["intent_category"].value_counts().rename_axis("intent_category").reset_index(name="count")
        if not intent_counts_chart.empty:
            st.plotly_chart(
                bar_chart_intent(intent_counts_chart),
                use_container_width=True,
                key="intent_chart",
            )
        type_counts = insights_df["comment_type"].value_counts().rename_axis("comment_type").reset_index(name="count")
        if not type_counts.empty:
            st.plotly_chart(
                bar_chart_comment_type(type_counts),
                use_container_width=True,
                key="comment_type_chart",
            )

    with col2:
        st.subheader("Aspect-based sentiment")
        aspect_rows = []
        for _, row in insights_df.iterrows():
            for a in _aspects_list(row.get("aspects")):
                if isinstance(a, dict):
                    aspect_rows.append({"aspect": a.get("aspect"), "sentiment": a.get("sentiment")})

        if aspect_rows:
            aspects_df = pd.DataFrame(aspect_rows)
            pivot = aspects_df.pivot_table(
                index="aspect",
                columns="sentiment",
                values="aspect",
                aggfunc="count",
                fill_value=0,
            )

            # Sıralama: negative kolonu varsa ona göre; yoksa toplam sayıya göre
            if "negative" in pivot.columns:
                pivot = pivot.sort_values(by="negative", ascending=False)
            else:
                pivot = pivot.assign(total=pivot.sum(axis=1)).sort_values(
                    by="total", ascending=False
                ).drop(columns=["total"])

            pivot = pivot.reset_index()
            st.dataframe(pivot)

            other_count = aspects_df[aspects_df["aspect"] == "other"].shape[0]
            total_aspects = len(aspects_df)
            if total_aspects > 0 and (other_count / total_aspects) > 0.2:
                st.caption("High 'other' aspect ratio; consider adding categories.")
        else:
            st.info("No aspect data for this video.")

    # 6) N-gram / frequent phrases (on-the-fly from text_clean)
    st.subheader("Frequent phrases (N-gram)")
    texts = insights_df["text_clean"].dropna()
    if len(texts) > 0:
        n_gram_type = st.radio("Phrase length", options=["Bigram (2 words)", "Trigram (3 words)"], horizontal=True, key="ngram_radio")
        n_val = 2 if "Bigram" in n_gram_type else 3
        ngram_df = compute_ngrams_from_texts(texts, n=n_val, min_count=2)
        if not ngram_df.empty:
            ngram_df = ngram_df.head(15)
            fig_ng = go.Figure(
                data=[
                    go.Bar(
                        y=ngram_df["phrase"],
                        x=ngram_df["count"],
                        orientation="h",
                        marker_color=THEME["accent"],
                        text=ngram_df["count"],
                        textposition="outside",
                        textfont=dict(color=THEME["text"]),
                    )
                ],
                layout=plotly_bar_layout(f"Top {n_val}-word phrases"),
            )
            fig_ng.update_yaxes(autorange="reversed", tickfont=dict(color=THEME["text"]))
            st.plotly_chart(fig_ng, use_container_width=True, key="ngram_chart")
            st.dataframe(ngram_df.rename(columns={"phrase": "Phrase", "count": "Count"}), use_container_width=True, height=min(300, 80 + len(ngram_df) * 28))
        else:
            st.caption("No repeated phrases with count ≥ 2.")
    else:
        st.caption("No text to compute phrases.")

    st.subheader("Comment list")

    with st.expander("Filters"):
        sentiments = sorted(insights_df["general_sentiment"].dropna().unique().tolist())
        topics = sorted(insights_df["topic"].dropna().unique().tolist())
        intents = sorted(insights_df["intent_category"].dropna().unique().tolist())
        sel_sentiments = st.multiselect("Sentiment", options=sentiments, default=sentiments)
        sel_topics = st.multiselect("Topic", options=topics, default=topics)
        sel_intents = st.multiselect("Intent", options=intents, default=intents)
        all_aspects_set = set()
        for val in insights_df["aspects"]:
            for a in _aspects_list(val):
                if isinstance(a, dict) and a.get("aspect"):
                    all_aspects_set.add(a.get("aspect"))
        all_aspects = sorted(all_aspects_set)
        aspect_filter = st.selectbox("Aspect", options=["(all)"] + all_aspects, index=0)

    def row_has_aspect(aspects_value, aspect_name: str) -> bool:
        """Satırdaki aspects listesinde belirtilen aspect adı var mı."""
        if not aspect_name:
            return True
        for a in _aspects_list(aspects_value):
            if isinstance(a, dict) and a.get("aspect") == aspect_name:
                return True
        return False

    filtered = insights_df.copy()
    if st.session_state.get("chart_filter_sentiment") and st.session_state["chart_filter_sentiment"] != "All":
        filtered = filtered[filtered["general_sentiment"] == st.session_state["chart_filter_sentiment"]]
    if st.session_state.get("chart_filter_topic") and st.session_state["chart_filter_topic"] != "All":
        filtered = filtered[filtered["topic"] == st.session_state["chart_filter_topic"]]
    if sel_sentiments:
        filtered = filtered[filtered["general_sentiment"].isin(sel_sentiments)]
    if sel_topics:
        filtered = filtered[filtered["topic"].isin(sel_topics)]
    if sel_intents:
        filtered = filtered[filtered["intent_category"].isin(sel_intents)]
    if aspect_filter != "(all)":
        filtered = filtered[
            filtered["aspects"].apply(lambda v: row_has_aspect(v, aspect_filter))
        ]

    filtered = filtered.copy()

    def aspects_evidence_str(aspects_value):
        """Her yorum için aspect: evidence metnini birleştirir (tabloda gösterim)."""
        parts = []
        for a in _aspects_list(aspects_value):
            if not isinstance(a, dict):
                continue
            asp = a.get("aspect") or ""
            ev = (a.get("evidence") or "").strip()
            if ev and ev not in ("(alıntı yok)", "(no evidence)"):
                parts.append(f"{asp}: {ev[:50]}{'…' if len(ev) > 50 else ''}")
            else:
                parts.append(f"{asp}: (no evidence)")
        return " | ".join(parts) if parts else "—"

    filtered["aspects_evidence"] = filtered["aspects"].apply(aspects_evidence_str)

    display_cols = ["comment_type", "intent_category", "general_sentiment", "topic", "text_clean"]
    for col in ["purchase_intent", "is_question", "competitor_mention"]:
        if col in filtered.columns:
            display_cols.append(col)
    if "aspects_evidence" in filtered.columns:
        display_cols = display_cols + ["aspects_evidence"]

    if st.session_state.get("chart_filter_topic") != "All" or st.session_state.get("chart_filter_sentiment") != "All":
        parts = []
        if st.session_state.get("chart_filter_sentiment") != "All":
            parts.append(st.session_state["chart_filter_sentiment"])
        if st.session_state.get("chart_filter_topic") != "All":
            parts.append(st.session_state["chart_filter_topic"])
        st.caption(f"Filter: {', '.join(parts)} — {len(filtered)} comments.")

    display_df = filtered[display_cols].copy()
    display_df = display_df.rename(columns={
        "comment_type": "Comment type",
        "intent_category": "Intent",
        "general_sentiment": "Sentiment",
        "topic": "Topic",
        "text_clean": "Comment",
        "aspects_evidence": "Aspects + evidence",
        "purchase_intent": "Purchase intent",
        "is_question": "Question",
        "competitor_mention": "Competitor mention",
    })

    st.dataframe(
        display_df,
        use_container_width=True,
        height=min(400, 200 + len(filtered) * 35),
    )


if __name__ == "__main__":
    main()

