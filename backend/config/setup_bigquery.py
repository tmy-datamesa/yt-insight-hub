"""
BigQuery dataset ve tablolarını oluşturan yardımcı script.

Amaç:
  - yt_insight_raw, yt_insight_core, yt_insight_ml dataset'lerini oluşturur
  - sql/*.sql dosyalarındaki DDL'leri çalıştırarak tabloları kurar

Kullanım (repo root'tan):
    python -m backend.config.setup_bigquery
    # veya: make bq-setup

Gereksinimler:
  - GCP_PROJECT_ID ortam değişkeni
  - GOOGLE_APPLICATION_CREDENTIALS (service account JSON) veya gcloud auth
"""

from __future__ import annotations

import pathlib
from typing import Iterable

from google.cloud import bigquery

from .settings import gcp_settings


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SQL_DIR = REPO_ROOT / "sql"


def ensure_datasets(client: bigquery.Client) -> None:
    """
    Raw, core ve ml dataset'lerini oluşturur.

    Dataset zaten varsa atlanır; yoksa belirtilen location ile oluşturulur.
    """
    for dataset_id in {
        gcp_settings.dataset_raw,
        gcp_settings.dataset_core,
        gcp_settings.dataset_ml,
    }:
        full_id = f"{client.project}.{dataset_id}"
        dataset = bigquery.Dataset(full_id)
        dataset.location = gcp_settings.location
        try:
            client.get_dataset(full_id)
        except Exception:
            client.create_dataset(dataset, exists_ok=True)


def iter_sql_files() -> Iterable[pathlib.Path]:
    """sql/ klasöründeki tüm .sql dosyalarını alfabetik sırayla döner."""
    if not SQL_DIR.exists():
        return []
    for path in sorted(SQL_DIR.glob("*.sql")):
        yield path


def apply_sql_files(client: bigquery.Client) -> None:
    """
    Her SQL dosyasındaki DDL'i BigQuery'de çalıştırır.

    CREATE TABLE IF NOT EXISTS kullanıldığı için tekrar çalıştırma güvenlidir.
    """
    for path in iter_sql_files():
        sql = path.read_text(encoding="utf-8")
        if not sql.strip():
            continue
        job = client.query(sql)
        job.result()


def main() -> None:
    """Dataset ve tabloları oluşturmak için ana giriş noktası."""
    if not gcp_settings.project_id:
        raise RuntimeError("GCP_PROJECT_ID must be set in environment.")

    client = bigquery.Client(project=gcp_settings.project_id, location=gcp_settings.location)
    ensure_datasets(client)
    apply_sql_files(client)


if __name__ == "__main__":
    main()

