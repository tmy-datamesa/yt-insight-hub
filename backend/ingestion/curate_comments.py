"""
Ham yorumları temizleyip analize hazır curated tabloya yazan script.

Amaç:
  - raw.comments'tan henüz işlenmemiş yorumları alır (LEFT JOIN curated)
  - Metin temizliği: HTML unescape, URL kaldırma, whitespace normalize
  - Dil tespiti (langdetect) ile is_turkish flag'i atar
  - yt_insight_core.comments_curated tablosuna yazar

Veri akışı:
  raw.comments (LEFT JOIN curated) -> Python işleme -> curated.comments_curated

Kullanım (repo root'tan):
    python -m backend.ingestion.curate_comments --limit 5000
"""

from __future__ import annotations

import argparse
import html
import re
import unicodedata
from typing import Any, Dict, List

from dotenv import load_dotenv
from google.cloud import bigquery
from langdetect import DetectorFactory, detect

from backend.config.settings import gcp_settings, bq_tables


# langdetect deterministik sonuç için seed (aynı metin -> aynı dil)
DetectorFactory.seed = 0

# Metin temizliği regex'leri: URL ve ardışık boşlukları kaldırmak için
URL_RE = re.compile(r"https?://\S+")
WHITESPACE_RE = re.compile(r"\s+")


def turkish_lower(text: str) -> str:
    """
    Türkçe kurallarına uygun küçük harfe çevirir.

    Python varsayılan .lower() İ -> i ve I -> i yaparken Türkçede
    İ -> i (noktalı i), I -> ı (noktasız ı) olmalı.
    """
    if not text:
        return text
    # Türkçe özel harfler: büyük İ -> küçük i, büyük I (ASCII) -> küçük ı
    text = text.replace("\u0130", "i")  # İ (U+0130)
    text = text.replace("I", "\u0131")  # I -> ı (U+0131)
    return text.lower()


def normalize_text_for_analysis(text: str) -> str:
    """
    Analiz için metni normalize eder: Unicode NFC + Türkçe lowercasing.

    NFC: aynı karakterin farklı kodlamalarını tek forma getirir.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    return turkish_lower(text)


def _bq_client() -> bigquery.Client:
    """BigQuery client döner."""
    if not gcp_settings.project_id:
        raise RuntimeError("GCP_PROJECT_ID must be set in environment or .env file.")
    return bigquery.Client(project=gcp_settings.project_id, location=gcp_settings.location)


def clean_text(text: str) -> str:
    """
    Yorum metnini analize uygun hale getirir.

    - HTML entity'leri decode eder (&amp; -> &)
    - URL'leri boşlukla değiştirir
    - Ardışık boşlukları tek boşluğa indirir
    - Unicode NFC + Türkçe lowercasing (İ->i, I->ı) uygular
    """
    text = html.unescape(text or "")
    text = URL_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text)
    text = text.strip()
    text = normalize_text_for_analysis(text)
    return text


def detect_language(text: str) -> str:
    """
    langdetect ile dil kodu döner (örn. 'tr', 'en').

    Çok kısa metinlerde güvenilmez; 5 karakterden kısa ise 'unknown' döner.
    """
    if not text or len(text) < 5:
        return "unknown"
    try:
        return detect(text)
    except Exception:
        return "unknown"


def fetch_new_raw_comments(limit: int) -> List[Dict[str, Any]]:
    """
    Curated tabloda henüz olmayan raw yorumları seçer.

    LEFT JOIN ile curated'da comment_id yoksa satır döner; böylece idempotent.
    """
    client = _bq_client()
    raw_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_raw}.{bq_tables.raw_comments}"
    curated_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_core}.{bq_tables.curated_comments}"

    query = f"""
    SELECT
      r.comment_id,
      r.video_id,
      r.channel_id,
      r.text_original,
      r.parent_id,
      r.author_channel_id,
      r.like_count
    FROM `{raw_table}` AS r
    LEFT JOIN `{curated_table}` AS c
      ON r.comment_id = c.comment_id
    WHERE c.comment_id IS NULL
    LIMIT {limit}
    """
    job = client.query(query)
    return [dict(row) for row in job.result()]


def curate_batch(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ham yorum satırlarını curated şemaya dönüştürür.

    Her satır için: text_clean, language, is_turkish, comment_len_chars/tokens hesaplanır.
    """
    curated: List[Dict[str, Any]] = []
    for row in rows:
        text_original = row.get("text_original") or ""
        text_clean = clean_text(text_original)
        language = detect_language(text_clean)
        is_turkish = language.startswith("tr")

        comment_len_chars = len(text_clean)
        comment_len_tokens = max(1, len(text_clean.split())) if text_clean else 0

        is_reply = row.get("parent_id") is not None

        curated.append(
            {
                "comment_id": row.get("comment_id"),
                "video_id": row.get("video_id"),
                "channel_id": row.get("channel_id"),
                "text_clean": text_clean,
                "language": language,
                "is_turkish": is_turkish,
                "is_reply": is_reply,
                "parent_id": row.get("parent_id"),
                "author_channel_id": row.get("author_channel_id"),
                "like_count": row.get("like_count"),
                "comment_len_chars": comment_len_chars,
                "comment_len_tokens": comment_len_tokens,
            }
        )
    return curated


def load_curated_to_bq(rows: List[Dict[str, Any]]) -> None:
    """Curated satırları BigQuery comments_curated tablosuna WRITE_APPEND ile yazar."""
    if not rows:
        return

    client = _bq_client()
    table_id = f"{gcp_settings.project_id}.{gcp_settings.dataset_core}.{bq_tables.curated_comments}"
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND
    )
    job = client.load_table_from_json(rows, table_id, job_config=job_config)
    job.result()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Curate raw YouTube comments into analysis-ready table.")
    parser.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Maximum number of new raw comments to curate in one run.",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    raw_rows = fetch_new_raw_comments(limit=args.limit)
    curated_rows = curate_batch(raw_rows)
    load_curated_to_bq(curated_rows)


if __name__ == "__main__":
    main()

