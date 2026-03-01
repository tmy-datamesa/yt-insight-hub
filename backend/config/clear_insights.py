"""
comment_insights tablosunu DROP + CREATE ile sıfırlar (temiz başlangıç).

DML (DELETE) yerine DDL kullanır; BigQuery free tier'da billing gerekmez.

Kullanım (repo root'tan):
    python -m backend.config.clear_insights
    # veya: make clear-insights

Dikkat: Tablo silinip aynı şema ile yeniden oluşturulur. Tüm inference kayıtları gider; geri alınamaz.
"""

from __future__ import annotations

import pathlib

from dotenv import load_dotenv
from google.cloud import bigquery

from backend.config.settings import gcp_settings, bq_tables


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DDL_PATH = REPO_ROOT / "sql" / "comment_insights_ddl.sql"


def main() -> None:
    load_dotenv()
    if not gcp_settings.project_id:
        raise RuntimeError("GCP_PROJECT_ID must be set in environment or .env file.")

    client = bigquery.Client(project=gcp_settings.project_id, location=gcp_settings.location)
    table_id = f"{gcp_settings.project_id}.{gcp_settings.dataset_ml}.{bq_tables.comment_insights}"

    # 1) Tabloyu sil (DDL; free tier'da çalışır)
    drop_sql = f"DROP TABLE IF EXISTS `{table_id}`"
    job = client.query(drop_sql)
    job.result()
    print(f"Tablo silindi: {table_id}")

    # 2) Aynı şema ile yeniden oluştur (sql/comment_insights_ddl.sql)
    if not DDL_PATH.exists():
        raise FileNotFoundError(f"DDL dosyası bulunamadı: {DDL_PATH}")

    ddl_sql = DDL_PATH.read_text(encoding="utf-8").strip()
    # Proje ID'li tam tablo adı kullan (CREATE TABLE IF NOT EXISTS -> CREATE TABLE)
    ddl_sql = ddl_sql.replace(
        "CREATE TABLE IF NOT EXISTS `yt_insight_ml.comment_insights`",
        f"CREATE TABLE `{table_id}`",
    )
    job = client.query(ddl_sql)
    job.result()
    print(f"Tablo yeniden oluşturuldu: {table_id}")


if __name__ == "__main__":
    main()
