"""
Merkezi konfigürasyon modülü.

Tüm ortam değişkenleri ve sabitler burada toplanır. .env dosyası import anında
yüklenir; böylece GCP_PROJECT_ID, API anahtarları vb. tüm script'lerde kullanılabilir.

Kullanım:
    from backend.config.settings import gcp_settings, bq_tables, youtube_settings
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# .env dosyasını import anında yükle; böylece os.getenv() çağrıları doğru değer döner
load_dotenv()


@dataclass(frozen=True)
class GCPSettings:
    """GCP / BigQuery proje ve dataset ayarları."""

    project_id: str = os.getenv("GCP_PROJECT_ID", "")
    location: str = os.getenv("GCP_LOCATION", "EU")

    # BigQuery dataset isimleri (raw=ham veri, core=temizlenmiş, ml=tahminler+rapor view'leri)
    dataset_raw: str = "yt_insight_raw"
    dataset_core: str = "yt_insight_core"
    dataset_ml: str = "yt_insight_ml"


@dataclass(frozen=True)
class BigQueryTables:
    """BigQuery tablo isimleri (dataset prefix olmadan)."""

    raw_comments: str = "comments"
    video_stats: str = "video_stats"
    curated_comments: str = "comments_curated"
    comment_insights: str = "comment_insights"


@dataclass(frozen=True)
class YouTubeSettings:
    """YouTube Data API v3 anahtarı."""

    api_key: str = os.getenv("YOUTUBE_API_KEY", "")


@dataclass(frozen=True)
class OpenAISettings:
    """OpenAI API ayarları (LLM inference için)."""

    api_key: str = os.getenv("OPENAI_API_KEY", "")
    model_name: str = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-mini")
    # Sınıflandırma ve yapılandırılmış çıktı için temperature varsayılanı 0.0
    temperature: float = float(os.getenv("OPENAI_TEMPERATURE", "0.0"))
    # Force-choice: 1 ise promptta "Asla nötr kullanma, pozitif veya negatif seç" kuralı kullanılır (test için)
    force_choice_sentiment: bool = os.getenv("OPENAI_FORCE_CHOICE_SENTIMENT", "").strip() in ("1", "true", "yes")


# Singleton instance'lar; tüm modüller bunları import eder
gcp_settings = GCPSettings()
bq_tables = BigQueryTables()
youtube_settings = YouTubeSettings()
openai_settings = OpenAISettings()

