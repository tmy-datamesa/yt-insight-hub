"""
LLM ile yorum analizi: genel sentiment, topic ve aspect-based sentiment çıkarımı.

Amaç:
  - Curated tablodan metni dolu olan TÜM yorumları seçer (dil / uzunluk filtresi yoktur)
  - Henüz bu model+prompt ile işlenmemiş olanları alır (idempotent)
  - Prompt chaining ile iki adımda çalışır:
      1) Tagging prompt: general_sentiment, topic, aspect_names[], stratejik sinyaller
      2) Aspect prompt: Her aspect için sentiment + evidence
  - Sonuçları yt_insight_ml.comment_insights tablosuna yazar
  - Tagging adımında iki aşamalı Chain-of-Thought (CoT) kullanılır:
      a) Önce modelden "adım adım düşün" (serbest metin) istenir.
      b) Bu çıktı verilerek sadece JSON üretmesi istenir.

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
    normalize_sentiment,
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


# ---------------------------------------------------------------------------
# Prompt 1: Tagging (topic + aspect_names + stratejik sinyaller)
# ---------------------------------------------------------------------------

def _build_tagging_system_prompt() -> str:
    sentiment_rule = (
        'general_sentiment: Overall sentiment → "positive", "negative", "neutral", or "mixed". '
        'Use "mixed" when the comment clearly has BOTH positive and negative opinions '
        '(e.g. "Kamerası çok iyi ama fiyatı uçuk" = mixed; good on one aspect, bad on another).'
    )
    if openai_settings.force_choice_sentiment:
        sentiment_rule = (
            'general_sentiment: You MUST choose "positive", "negative", or "mixed". '
            'Do NOT use "neutral". Pick the dominant tone; use "mixed" only when positive and negative are clearly balanced.'
        )
    return f"""
You are a classifier for Turkish comments under technology-related YouTube videos.

Your task in this STEP 1 (TAGGING ONLY):
1. {sentiment_rule}
2. topic: MAIN topic of the comment → choose EXACTLY ONE value from the topic list below.
   Allowed topic list: {_TOPICS_STR}
3. aspect_names: Detect ALL aspects that are mentioned in the comment and return ONLY THEIR NAMES
   from the aspect list below. Do NOT output sentiment or evidence in this step.

Aspect list (use ONLY these values): {_ASPECTS_STR}

Mapping hints (Turkish phrase → aspect name):
- Fiyat, pahalı, ucuz, bütçe → price
- Fiyat/performans oranı, değer, "paranın hakkı" → value_for_money
- Performans, hız, donanım, oyun → performance
- Kamera, fotoğraf, çekim → camera
- Batarya, şarj, pil ömrü → battery
- Ekran, görüntü, panel → display
- Ses, mikrofon, hoparlör, kulaklık çıkışı → audio
- Tasarım, görünüm → design
- Dayanıklılık, kalite, ömür → build_quality or durability
- Yazılım, arayüz, güncelleme → software
- Isınma, termal → thermal
- 5G, WiFi, Bluetooth, bağlantı → connectivity
- Sponsorluk, reklam, güven → sponsorship
- Kanal, sunum, anlatım → channel_trust
- Karşılaştırma, X ile Y → comparison
- SD kart, hafıza kartı, depolama, GB → storage
- Servis, garanti, müşteri hizmetleri → customer_service
Use "other" ONLY if none of the above really fits; always try to map to a list value first.

4. Strategic boolean signals (based on the whole comment text):
   - purchase_intent: TRUE if the user is thinking about buying or asks for a recommendation
     (examples in Turkish: "alacağım", "almalı mıyım", "alsam mı", "tavsiye eder misiniz").
   - is_question: TRUE if there is at least one question (question mark or clear question pattern).
   - competitor_mention: TRUE if the comment mentions or compares to another product/brand/channel.

Example (comment in Turkish):
Comment: "Fiyatı yüksek ama bataryası iyi. X markayla kıyaslar mısınız?"

Valid JSON output:
{{"general_sentiment": "neutral",
  "topic": "product_review",
  "aspect_names": ["price", "battery"],
  "purchase_intent": false,
  "is_question": true,
  "competitor_mention": true}}

Output rules:
- ALWAYS return a SINGLE valid JSON object.
- aspect_names MUST be an array (use [] if there is no aspect).
- Do NOT include any explanations or extra text outside the JSON.
""".strip()


def _build_tagging_cot_user_prompt(comment_text: str) -> str:
    """İki aşamalı CoT: ilk aşamada adım adım düşünmesi için kullanıcı mesajı."""
    return (
        "Aşağıdaki yorumu adım adım analiz et. Önce düşün, sonra çıkarımını yaz.\n\n"
        "1) Yorumun ana konusu ne? (ürün incelemesi mi, fiyat mı, sponsorluk/reklam güveni mi, "
        "kanal/sunum mu, karşılaştırma mı, yoksa başka bir şey mi?)\n"
        "2) Hangi aspect’ler geçiyor? (fiyat, batarya, kamera, performans, tasarım vb.)\n"
        "3) Genel duygu tonu nedir? (olumlu / olumsuz / nötr / karışık – hem iyi hem kötü yan varsa karışık)\n"
        "4) Satın alma niyeti, soru veya rakip marka/kanal atıfı var mı?\n\n"
        "Açıklamanı Türkçe veya İngilizce serbest metin olarak yaz; JSON üretme.\n\n"
        f"Yorum:\n{comment_text}"
    )


def build_tagging_messages(comment_text: str) -> List[Dict[str, str]]:
    """Tek yorum için tagging amaçlı OpenAI Chat API mesaj listesini oluşturur (tek aşama, JSON)."""
    return [
        {"role": "system", "content": _build_tagging_system_prompt().strip()},
        {
            "role": "user",
            "content": (
                "Yorum metni aşağıdadır. Sadece geçerli JSON üret; "
                '"general_sentiment", "topic", "aspect_names", "purchase_intent", '
                '"is_question", "competitor_mention" alanlarını doldur.\n\n'
                f"Yorum:\n{comment_text}"
            ),
        },
    ]


def build_tagging_messages_with_cot(
    comment_text: str, reasoning: str
) -> List[Dict[str, str]]:
    """CoT sonrası: yukarıdaki analiz verilerek sadece JSON isteyen mesaj listesi."""
    return [
        {"role": "system", "content": _build_tagging_system_prompt().strip()},
        {
            "role": "user",
            "content": _build_tagging_cot_user_prompt(comment_text),
        },
        {"role": "assistant", "content": reasoning},
        {
            "role": "user",
            "content": (
                "Yukarıdaki analize göre yalnızca şu anahtarlara sahip tek bir geçerli JSON üret: "
                '"general_sentiment", "topic", "aspect_names", "purchase_intent", '
                '"is_question", "competitor_mention". Başka metin yazma.'
            ),
        },
    ]


def _call_text_model(
    client: OpenAI, messages: List[Dict[str, str]]
) -> str:
    """Serbest metin yanıt döner; response_format kullanılmaz (CoT ilk aşama)."""
    resp = client.chat.completions.create(
        model=openai_settings.model_name,
        temperature=openai_settings.temperature,
        messages=messages,
    )
    return (resp.choices[0].message.content or "").strip()


def _call_json_model(
    client: OpenAI, messages: List[Dict[str, str]]
) -> Dict[str, Any]:
    """
    OpenAI API'yi çağırıp JSON response'u parse eder.

    response_format=json_object ile yapılandırılmış çıktı zorunlu.
    JSON parse hatası olursa 1 kez daha dener; ikinci denemede hata fırlatır.
    """
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


def call_tagging_model(client: OpenAI, comment_text: str) -> Dict[str, Any]:
    """
    Tagging adımı: iki aşamalı CoT.
    1) Adım adım düşün (serbest metin).
    2) Bu çıktı verilerek sadece JSON üret (general_sentiment, topic, aspect_names, vb.).
    """
    cot_messages = [
        {"role": "system", "content": _build_tagging_system_prompt().strip()},
        {"role": "user", "content": _build_tagging_cot_user_prompt(comment_text)},
    ]
    reasoning = _call_text_model(client, cot_messages)
    messages_with_cot = build_tagging_messages_with_cot(comment_text, reasoning)
    return _call_json_model(client, messages_with_cot)


# ---------------------------------------------------------------------------
# Prompt 2: Aspect bazlı sentiment + evidence
# ---------------------------------------------------------------------------

def _build_aspect_system_prompt() -> str:
    aspect_sentiment_rule = (
        'If the attitude towards this aspect is unclear, use "neutral"; '
        'if clearly both positive and negative about this aspect, use "mixed".'
    )
    if openai_settings.force_choice_sentiment:
        aspect_sentiment_rule = (
            'Do NOT use "neutral". You MUST choose "positive", "negative", or "mixed". '
            'Prefer the dominant tone for this aspect.'
        )
    return f"""
You are a sentiment and evidence extractor for a SINGLE aspect.

Your task in this STEP 2 (PER-ASPECT ANALYSIS):
1. You will receive:
   - The full comment text (in Turkish),
   - The name of ONE aspect to analyse (e.g. "battery", "storage", "customer_service").
2. Decide the sentiment ONLY with respect to THIS aspect:
   - "positive" / "negative" / "neutral" / "mixed" (use "mixed" only when the comment says both good and bad about this single aspect).
3. Find the best evidence sentence or short span in the comment that supports your decision:
   - Prefer a direct quote from the comment text (or very close paraphrase).
   - Length should be between 3 and 20 words.

Rules:
- Ignore other topics; focus ONLY on the given aspect.
- {aspect_sentiment_rule}
- NEVER leave the evidence field empty:
  - If there is no clear phrase about the aspect, set
    evidence to "(aspect ile ilgili açık ifade yok)" (in Turkish).

Output format (single JSON object):
{{"aspect": "<aspect_name>", "sentiment": "<positive|negative|neutral|mixed>", "evidence": "<quote or explanation>"}}

Output rules:
- ALWAYS return a SINGLE valid JSON object.
- Do NOT include any explanations or extra text outside the JSON.
""".strip()


def build_aspect_messages(comment_text: str, aspect_name: str) -> List[Dict[str, str]]:
    """Tek yorum + tek aspect için sentiment & evidence isteyen mesajları oluşturur."""
    return [
        {"role": "system", "content": _build_aspect_system_prompt()},
        {
            "role": "user",
            "content": (
                f'Aspect adı: "{aspect_name}".\n'
                "Yalnızca bu aspect açısından sentiment ve evidence üret.\n\n"
                f"Yorum metni:\n{comment_text}"
            ),
        },
    ]


def call_aspect_model(
    client: OpenAI, comment_text: str, aspect_name: str
) -> Dict[str, Any]:
    """Tek bir aspect için sentiment+evidence tahmini alır."""
    messages = build_aspect_messages(comment_text, aspect_name)
    return _call_json_model(client, messages)


def fetch_pending_comments(
    client: bigquery.Client,
    model_name: str,
    video_id: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """
    Henüz bu model_name ile işlenmemiş curated yorumları döner.

    LEFT JOIN insights: p.comment_id IS NULL olanlar seçilir -> idempotent.
    Dil veya uzunluk filtresi YOKTUR; metni dolu olan tüm yorumlar alınır.
    """
    core_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_core}.{bq_tables.curated_comments}"
    pred_table = f"{gcp_settings.project_id}.{gcp_settings.dataset_ml}.{bq_tables.comment_insights}"

    conditions = [
        "c.text_clean IS NOT NULL",
        "c.text_clean != ''",
        "p.comment_id IS NULL",
    ]
    if video_id:
        conditions.append("c.video_id = @video_id")
    where_clause = " AND ".join(conditions)
    use_limit = limit > 0
    limit_clause = "LIMIT @limit" if use_limit else ""

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
    {limit_clause}
    """

    job_config_params = [
        bigquery.ScalarQueryParameter("model_name", "STRING", model_name),
    ]
    if use_limit:
        job_config_params.append(bigquery.ScalarQueryParameter("limit", "INT64", limit))
    job_config = bigquery.QueryJobConfig(
        query_parameters=job_config_params
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

    Beklenen prediction formatı:
      - general_sentiment, topic, purchase_intent, is_question, competitor_mention
      - aspects: [{"aspect": ..., "sentiment": ..., "evidence": ...}, ...]

    Topic ve aspect değerleri ontolojiye normalize edilir (channel_quality -> channel_trust).
    Sentiment set dışındaysa normalize_sentiment ile neutral yapılır.
    Evidence boşsa "(alıntı yok)" ile doldurulur.
    """
    raw_sentiment = (prediction.get("general_sentiment") or "neutral").strip().lower()
    general_sentiment = normalize_sentiment(raw_sentiment)
    topic = normalize_topic(prediction.get("topic") or "offtopic")

    aspects_raw = prediction.get("aspects") or []
    aspects: List[Dict[str, Any]] = []
    for a in aspects_raw:
        if not isinstance(a, dict):
            continue
        asp = normalize_aspect(a.get("aspect") or "other")
        raw_sent = (a.get("sentiment") or "neutral").strip().lower()
        sent = normalize_sentiment(raw_sent)
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
        help="Maximum number of comments to process in this run. Use 0 for no limit (process all pending).",
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
        text = row["text_clean"] or ""

        # 1) Tagging adımı: genel sentiment, topic, aspect_names, stratejik sinyaller
        tagging = call_tagging_model(oa_client, comment_text=text)

        # 2) Aspect adımı: her aspect için sentiment + evidence
        aspect_names_raw = tagging.get("aspect_names") or []
        aspect_names: List[str] = []
        for name in aspect_names_raw:
            if isinstance(name, str):
                cleaned = name.strip()
                if cleaned and cleaned not in aspect_names:
                    aspect_names.append(cleaned)

        aspects: List[Dict[str, Any]] = []
        for aspect_name in aspect_names:
            aspect_pred = call_aspect_model(
                oa_client, comment_text=text, aspect_name=aspect_name
            )
            # Model çıktısında aspect alanı yoksa, çağrılan isimle doldur
            aspect_value = aspect_pred.get("aspect") or aspect_name
            aspects.append(
                {
                    "aspect": aspect_value,
                    "sentiment": aspect_pred.get("sentiment"),
                    "evidence": aspect_pred.get("evidence"),
                }
            )

        combined_prediction: Dict[str, Any] = dict(tagging)
        combined_prediction["aspects"] = aspects

        results.append(
            build_bq_row(
                row=row,
                prediction=combined_prediction,
                model_name=openai_settings.model_name,
            )
        )

    load_predictions_to_bq(bq_client, results)


if __name__ == "__main__":
    main()

