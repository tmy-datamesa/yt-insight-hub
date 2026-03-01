"""
comment_insights_report.text_clean üzerinden 1/2/3-gram sayımları; comment_ngrams tablosuna yazar.

Amaç: Looker / word cloud için "fiyat performans", "şarj aleti yok" gibi
      en sık geçen kelime ve kelime öbeklerini BigQuery'de tutmak.
Veri: comment_insights_report (video_id, channel_id, text_clean)
Çıktı: yt_insight_ml.comment_ngrams (video_id, channel_id, n, phrase, phrase_count, updated_at)

Kullanım (repo root):
    python -m backend.analytics.build_ngrams
    python -m backend.analytics.build_ngrams --video-id VIDEO_ID   # tek video
    make build-ngrams
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
from google.cloud import bigquery

from backend.config.settings import gcp_settings, bq_tables


def tokenize(text: str) -> list[str]:
    """
    Metni kelimelere böler: boşluk + noktalama ayırıcı.
    Türkçe karakterleri korur; her kelime küçük harfe çevrilir (İ -> i).
    """
    if not text or not isinstance(text, str):
        return []
    # Noktalama ve gereksiz karakterleri boşluğa çevir
    t = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return []
    # Türkçe İ -> i (Python lower() bunu yapmaz)
    words = [w.replace("\u0130", "i").lower() for w in t.split() if w.strip()]
    return words


def ngrams_for_text(words: list[str], n_max: int = 3) -> dict[tuple[int, str], int]:
    """Bir metin için n=1,2,3 gram sayımlarını döner. Key: (n, phrase), Value: count."""
    counts: dict[tuple[int, str], int] = defaultdict(int)
    for n in range(1, min(n_max + 1, len(words) + 1)):
        for i in range(len(words) - n + 1):
            phrase = " ".join(words[i : i + n])
            if phrase.strip():
                counts[(n, phrase)] += 1
    return counts


def build_ngrams(
    client: bigquery.Client,
    video_id: str | None = None,
    min_count: int = 1,
) -> int:
    """
    comment_insights_report'tan text_clean çeker, n-gram sayar, comment_ngrams'a yazar.
    video_id verilirse sadece o video; yoksa tüm videolar.
    Dönen: yazılan satır sayısı.
    """
    report_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_ml}.comment_insights_report"
    ngrams_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_ml}.comment_ngrams"

    query = f"""
    SELECT video_id, channel_id, text_clean
    FROM `{report_table}`
    WHERE text_clean IS NOT NULL AND LENGTH(TRIM(text_clean)) > 0
    """
    if video_id:
        query += f" AND video_id = @video_id"
    job_config = bigquery.QueryJobConfig()
    if video_id:
        job_config.query_parameters = [
            bigquery.ScalarQueryParameter("video_id", "STRING", video_id)
        ]
    df = client.query(query, job_config=job_config).result().to_dataframe()
    if df.empty:
        return 0

    # (video_id, channel_id) -> (n, phrase) -> count
    agg: dict[tuple[str, str], dict[tuple[int, str], int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for _, row in df.iterrows():
        vid, cid, text = row["video_id"], row["channel_id"], row["text_clean"]
        words = tokenize(str(text))
        for (n, phrase), cnt in ngrams_for_text(words).items():
            agg[(vid, cid)][(n, phrase)] += cnt

    # Flatten to rows
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for (vid, cid), phrase_counts in agg.items():
        for (n, phrase), cnt in phrase_counts.items():
            if cnt >= min_count:
                rows.append(
                    {
                        "video_id": vid,
                        "channel_id": cid,
                        "n": n,
                        "phrase": phrase,
                        "phrase_count": cnt,
                        "updated_at": now,
                    }
                )

    if not rows:
        return 0

    # Load job ile tabloyu tamamen yenile (WRITE_TRUNCATE). DELETE kullanmıyoruz;
    # BigQuery ücretsiz katmanda DML (DELETE) izin verilmediği için bu yöntem gerekli.
    df_out = pd.DataFrame(rows)
    df_out["updated_at"] = pd.to_datetime(df_out["updated_at"], utc=True)
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_dataframe(df_out, ngrams_table, job_config=job_config).result()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build n-grams from comment_insights_report into comment_ngrams table.")
    parser.add_argument("--video-id", type=str, default=None, help="Optional: only this video_id")
    parser.add_argument("--min-count", type=int, default=1, help="Minimum phrase count to store (default 1)")
    args = parser.parse_args()

    if not gcp_settings.project_id:
        raise RuntimeError("GCP_PROJECT_ID must be set.")

    client = bigquery.Client(project=gcp_settings.project_id, location=gcp_settings.location)
    n = build_ngrams(client, video_id=args.video_id, min_count=args.min_count)
    print(f"Wrote {n} n-gram rows to comment_ngrams.")


if __name__ == "__main__":
    main()
