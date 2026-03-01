"""
LLM ile yorum analizi: genel sentiment, topic ve aspect-based sentiment çıkarımı.

Amaç:
  - Curated tablodan Türkçe, yeterince uzun yorumları seçer
  - Henüz bu model+prompt ile işlenmemiş olanları alır (idempotent)
  - OpenAI Chat Completions ile structured JSON (general_sentiment, topic, aspects) üretir
  - Sonuçları yt_insight_ml.comment_insights tablosuna yazar

Veri akışı:
  curated (LEFT JOIN insights) -> OpenAI API -> comment_insights

Kullanım (repo root'tan):
    python -m backend.inference.comment_insights --video-id dP9JEXHI0zs
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from google.cloud import bigquery
from openai import OpenAI

from backend.config.settings import gcp_settings, bq_tables, openai_settings
from backend.inference.ontology import (
    ASPECTS,
    TOPICS,
    normalize_aspect,
    normalize_topic,
)

# Prompt'ta kullanılacak liste metinleri (tek kaynak: ontology)
_TOPICS_STR = ", ".join(TOPICS)
_ASPECTS_STR = ", ".join(ASPECTS)


def _bq_client() -> bigquery.Client:
    """BigQuery client döner."""
    if not gcp_settings.project_id:
        raise RuntimeError("GCP_PROJECT_ID must be set in environment or .env file.")
    return bigquery.Client(project=gcp_settings.project_id, location=gcp_settings.location)


def _openai_client() -> OpenAI:
    """OpenAI client instance döner."""
    if not openai_settings.api_key:
        raise RuntimeError("OPENAI_API_KEY must be set in environment or .env file.")
    return OpenAI(api_key=openai_settings.api_key)


# LLM'e verilen sistem prompt'u: görev + sıkı ontoloji + eşleştirme rehberi + evidence
def _build_system_prompt() -> str:
    return f"""
Sen Türkçe teknoloji YouTube videoları altındaki yorumları analiz eden bir modelisin.

Görev:
1. general_sentiment: Yorumun genel duygu yönü → "positive", "negative" veya "neutral".
2. topic: Yorumun ana konusu → AŞAĞIDAKİ LİSTEDEN TAM BİR TANE SEÇ.
   İzin verilen topic listesi: {_TOPICS_STR}
3. aspects: Yorumda geçen her boyut için aspect (aşağıdaki listeden), sentiment ve evidence.

Aspect listesi (SADECE bu değerleri kullan): {_ASPECTS_STR}

Eşleştirme rehberi (yorumdaki ifade → aspect):
- Fiyat, pahalı, ucuz, bütçe → price
- Fiyat/performans oranı, değer, "paranın hakkı" → value_for_money
- Performans, hız, donanım, oyun → performance
- Kamera, fotoğraf, çekim → camera
- Batarya, şarj, pil ömrü → battery
- Ekran, görüntü, panel → display
- Ses, mikrofon, hoparlör, kulaklık çıkışı → audio
- Tasarım, görünüm → design
- Dayanıklılık, kalite, ömür → build_quality veya durability
- Yazılım, arayüz, güncelleme → software
- Isınma, termal → thermal
- 5G, WiFi, Bluetooth, bağlantı → connectivity
- Sponsorluk, reklam, güven → sponsorship
- Kanal, sunum, anlatım → channel_trust
- Karşılaştırma, X ile Y → comparison
"other" SADECE yukarıdaki hiçbiri gerçekten uymuyorsa kullan; önce mutlaka listeden uygun bir karşılık seç.

Evidence: Her aspect için yorumdan 3-15 kelimelik alıntı veya özet zorunlu; boş bırakma.

4. Stratejik sinyaller (boolean; yorum metnine göre true/false):
   - purchase_intent: Satın alma niyeti veya karar aşaması (örn. "alacağım", "düşünüyorum", "önerir misin", "alsam mı").
   - is_question: En az bir soru cümlesi var mı (soru işareti veya soru kalıbı).
   - competitor_mention: Rakip ürün, marka veya kanal ismi / kıyası geçiyor mu.

Örnek çıktı (yorum: "Fiyatı yüksek ama bataryası iyi. X markayla kıyaslar mısınız?"):
{{"general_sentiment": "neutral", "topic": "product_review", "aspects": [{{"aspect": "price", "sentiment": "negative", "evidence": "fiyatı yüksek"}}, {{"aspect": "battery", "sentiment": "positive", "evidence": "bataryası iyi"}}], "purchase_intent": false, "is_question": true, "competitor_mention": true}}

Sadece geçerli JSON döndür, ek açıklama yazma.
"""


def build_messages(comment_text: str) -> List[Dict[str, str]]:
    """Tek yorum için OpenAI Chat API mesaj listesini oluşturur."""
    return [
        {"role": "system", "content": _build_system_prompt().strip()},
        {
            "role": "user",
            "content": f"Yorum metni aşağıdadır. Sadece geçerli JSON üret; her aspect için evidence alanını doldur.\n\nYorum:\n{comment_text}",
        },
    ]


def call_model(client: OpenAI, comment_text: str) -> Dict[str, Any]:
    """
    OpenAI API'yi çağırıp JSON response'u parse eder.

    response_format=json_object ile yapılandırılmış çıktı zorunlu.
    JSON parse hatası olursa 1 kez daha dener; ikinci denemede hata fırlatır.
    """
    messages = build_messages(comment_text)
    for attempt in range(2):
        resp = client.chat.completions.create(
            model=openai_settings.model_name,
            temperature=openai_settings.temperature,
            response_format={"type": "json_object"},
            messages=messages,
        )
        content = resp.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # İlk denemede parse hatası; ikinci denemede aynı mesajlarla tekrar dene
            if attempt == 1:
                raise
    return {}


def fetch_pending_comments(
    client: bigquery.Client,
    model_name: str,
    video_id: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """
    Henüz bu model_name ile işlenmemiş curated yorumları döner.

    LEFT JOIN insights: p.comment_id IS NULL olanlar seçilir -> idempotent.
    Sadece Türkçe ve en az 3 token uzunluğundaki yorumlar alınır.
    """
    core_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_core}.{bq_tables.curated_comments}"
    pred_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_ml}.{bq_tables.comment_insights}"

    conditions = [
        "c.is_turkish = TRUE",
        "c.comment_len_tokens >= 3",
        "p.comment_id IS NULL",
    ]
    if video_id:
        conditions.append("c.video_id = @video_id")
    where_clause = " AND ".join(conditions)

    query = f"""
    SELECT
      c.comment_id,
      c.video_id,
      c.channel_id,
      c.text_clean
    FROM `{core_table}` AS c
    LEFT JOIN `{pred_table}` AS p
      ON c.comment_id = p.comment_id
     AND p.model_name = @model_name
    WHERE {where_clause}
    LIMIT @limit
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("model_name", "STRING", model_name),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]
        + (
            [bigquery.ScalarQueryParameter("video_id", "STRING", video_id)]
            if video_id
            else []
        )
    )

    job = client.query(query, job_config=job_config)
    return [dict(row) for row in job.result()]


def build_bq_row(
    row: Dict[str, Any],
    prediction: Dict[str, Any],
    model_name: str,
) -> Dict[str, Any]:
    """
    LLM prediction'ını BigQuery satır formatına çevirir.

    Topic ve aspect değerleri ontolojiye normalize edilir (channel_quality -> channel_trust).
    Evidence boşsa "(alıntı yok)" ile doldurulur.
    """
    raw_sentiment = (prediction.get("general_sentiment") or "neutral").strip().lower()
    general_sentiment = raw_sentiment if raw_sentiment in ("positive", "negative", "neutral") else "neutral"
    topic = normalize_topic(prediction.get("topic") or "offtopic")

    aspects_raw = prediction.get("aspects") or []
    aspects: List[Dict[str, Any]] = []
    for a in aspects_raw:
        if not isinstance(a, dict):
            continue
        asp = normalize_aspect(a.get("aspect") or "other")
        sent = (a.get("sentiment") or "neutral").strip().lower()
        if sent not in ("positive", "negative", "neutral"):
            sent = "neutral"
        evidence = (a.get("evidence") or "").strip() or "(alıntı yok)"
        aspects.append({"aspect": asp, "sentiment": sent, "evidence": evidence})

    def to_bool(val: Any) -> bool:
        if val is None:
            return False
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.strip().lower() in ("true", "1", "yes", "evet")
        return bool(val)

    return {
        "comment_id": row["comment_id"],
        "video_id": row["video_id"],
        "channel_id": row["channel_id"],
        "model_name": model_name,
        "general_sentiment": general_sentiment,
        "topic": topic,
        "aspects": aspects,
        "purchase_intent": to_bool(prediction.get("purchase_intent")),
        "is_question": to_bool(prediction.get("is_question")),
        "competitor_mention": to_bool(prediction.get("competitor_mention")),
        "inference_ts": datetime.now(timezone.utc).isoformat(),
    }


def load_predictions_to_bq(client: bigquery.Client, rows: List[Dict[str, Any]]) -> None:
    """Tahmin satırlarını comment_insights tablosuna WRITE_APPEND ile yazar."""
    if not rows:
        return
    table_id = f"{gcp_settings.project_id}.{gcp_settings.dataset_ml}.{bq_tables.comment_insights}"
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND
    )
    job = client.load_table_from_json(rows, table_id, job_config=job_config)
    job.result()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run LLM-based aspect & sentiment inference for YouTube comments."
    )
    parser.add_argument(
        "--video-id",
        help="Optional video ID; if omitted, runs on all pending comments.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum number of comments to process in this run.",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    bq_client = _bq_client()
    oa_client = _openai_client()

    pending = fetch_pending_comments(
        client=bq_client,
        model_name=openai_settings.model_name,
        video_id=args.video_id,
        limit=args.limit,
    )

    results: List[Dict[str, Any]] = []
    for row in pending:
        prediction = call_model(oa_client, comment_text=row["text_clean"])
        results.append(
            build_bq_row(
                row=row,
                prediction=prediction,
                model_name=openai_settings.model_name,
            )
        )

    load_predictions_to_bq(bq_client, results)


if __name__ == "__main__":
    main()

