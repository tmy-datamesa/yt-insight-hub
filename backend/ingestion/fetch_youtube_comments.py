"""
YouTube yorumlarını çekip BigQuery raw tablosuna yükleyen ingestion script'i.

Amaç:
  - YouTube Data API v3 ile public yorumları (top-level + reply) çeker
  - Ham veriyi yt_insight_raw.comments tablosuna yazar
  - Video veya kanal bazlı çalışır; sayfalama ile tüm yorumları toplar

Veri akışı:
  YouTube API (commentThreads) -> Python dict listesi -> BigQuery WRITE_APPEND

Kullanım (repo root'tan):
    python -m backend.ingestion.fetch_youtube_comments --video-id dP9JEXHI0zs
    python -m backend.ingestion.fetch_youtube_comments --channel-id UCxxx --max-videos 10
"""

from __future__ import annotations

import argparse
import datetime as dt
from typing import Any, Dict, List, Optional

def _utc_now() -> str:
    """UTC şu an; BigQuery timestamp alanları için ISO string (Z suffix)."""
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

import requests
from dotenv import load_dotenv
from google.cloud import bigquery

from backend.config.settings import gcp_settings, bq_tables, youtube_settings


API_BASE = "https://www.googleapis.com/youtube/v3"


def _require_api_key() -> str:
    """YouTube API anahtarını kontrol eder; yoksa hata fırlatır."""
    if not youtube_settings.api_key:
        raise RuntimeError("YOUTUBE_API_KEY must be set in environment or .env file.")
    return youtube_settings.api_key


def _bq_client() -> bigquery.Client:
    """BigQuery client instance döner; proje ID kontrolü yapar."""
    if not gcp_settings.project_id:
        raise RuntimeError("GCP_PROJECT_ID must be set in environment or .env file.")
    return bigquery.Client(project=gcp_settings.project_id, location=gcp_settings.location)


def _youtube_get(endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """YouTube Data API v3'e GET isteği atar; JSON response döner."""
    api_key = _require_api_key()
    full_params = {"key": api_key, **params}
    resp = requests.get(f"{API_BASE}/{endpoint}", params=full_params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def list_videos_for_channel(channel_id: str, max_videos: int) -> List[Dict[str, Any]]:
    """
    Kanalın en son yüklenen videolarını listeler (search API, order=date).

    Sayfalama ile nextPageToken kullanılır; max_videos sayısına ulaşınca durur.
    """
    videos: List[Dict[str, Any]] = []
    page_token: Optional[str] = None

    while len(videos) < max_videos:
        params: Dict[str, Any] = {
            "part": "id,snippet",
            "channelId": channel_id,
            "order": "date",
            "maxResults": min(50, max_videos - len(videos)),
            "type": "video",
        }
        if page_token:
            params["pageToken"] = page_token

        data = _youtube_get("search", params)
        for item in data.get("items", []):
            video_id = item["id"].get("videoId")
            if not video_id:
                continue
            videos.append(item)
            if len(videos) >= max_videos:
                break

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return videos


def fetch_comments_for_video(video_id: str) -> List[Dict[str, Any]]:
    """
    Tek bir videonun tüm yorumlarını çeker (top-level + reply'lar).

    commentThreads API kullanılır; part=snippet,replies ile cevaplar da gelir.
    Sayfalama nextPageToken ile yapılır; token bitene kadar döngü devam eder.
    """
    records: List[Dict[str, Any]] = []
    page_token: Optional[str] = None

    while True:
        params: Dict[str, Any] = {
            "part": "snippet,replies",
            "videoId": video_id,
            "maxResults": 100,
            "order": "time",
            "textFormat": "plainText",
        }
        if page_token:
            params["pageToken"] = page_token

        data = _youtube_get("commentThreads", params)

        for item in data.get("items", []):
            thread_snippet = item["snippet"]
            top = thread_snippet["topLevelComment"]["snippet"]

            # Tüm yorumlar için ortak video/kanal bilgisi
            base_common = {
                "channel_id": thread_snippet.get("channelId"),
                "channel_title": thread_snippet.get("channelTitle"),
                "video_id": thread_snippet.get("videoId"),
                "video_title": thread_snippet.get("videoTitle"),
                "video_published_at": None,
            }

            ingested_at = _utc_now()

            # Ana yorum (thread'in ilk yorumu)
            records.append(
                {
                    **base_common,
                    "comment_id": thread_snippet.get("topLevelComment", {}).get("id"),
                    "parent_id": None,
                    "is_top_level": True,
                    "author_channel_id": top.get("authorChannelId", {}).get("value"),
                    "author_display_name": top.get("authorDisplayName"),
                    "text_original": top.get("textOriginal"),
                    "text_display": top.get("textDisplay"),
                    "like_count": top.get("likeCount"),
                    "published_at": top.get("publishedAt"),
                    "updated_at": top.get("updatedAt"),
                    "raw_payload": item,
                    "ingested_at": ingested_at,
                }
            )

            # Cevaplar (replies) varsa; her biri ayrı satır olarak eklenir
            for reply in item.get("replies", {}).get("comments", []):
                rs = reply["snippet"]
                records.append(
                    {
                        **base_common,
                        "comment_id": reply.get("id"),
                        "parent_id": thread_snippet.get("topLevelComment", {}).get("id"),
                        "is_top_level": False,
                        "author_channel_id": rs.get("authorChannelId", {}).get("value"),
                        "author_display_name": rs.get("authorDisplayName"),
                        "text_original": rs.get("textOriginal"),
                        "text_display": rs.get("textDisplay"),
                        "like_count": rs.get("likeCount"),
                        "published_at": rs.get("publishedAt"),
                        "updated_at": rs.get("updatedAt"),
                        "raw_payload": reply,
                        "ingested_at": ingested_at,
                    }
                )

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return records


def fetch_video_stats(video_ids: List[str]) -> List[Dict[str, Any]]:
    """
    videos.list API (part=statistics,snippet) ile izlenme, begeni, yorum sayisi alir.

    En fazla 50 video ID tek istekte; daha fazlaysa sayfalama yapilmaz (ilk 50).
    """
    if not video_ids:
        return []
    api_key = _require_api_key()
    # API id parametresi en fazla 50 ID kabul eder
    chunk = video_ids[:50]
    params: Dict[str, Any] = {
        "part": "statistics,snippet",
        "id": ",".join(chunk),
        "key": api_key,
    }
    data = _youtube_get("videos", params)
    result: List[Dict[str, Any]] = []
    fetched_at = _utc_now()
    for item in data.get("items", []):
        vid = item.get("id") or ""
        sn = item.get("snippet") or {}
        stat = item.get("statistics") or {}
        # API bazen sayilari string doner
        def _int(val: Any) -> int:
            if val is None:
                return 0
            if isinstance(val, int):
                return val
            try:
                return int(str(val).replace(",", ""))
            except (ValueError, TypeError):
                return 0

        pub = sn.get("publishedAt")
        result.append({
            "video_id": vid,
            "channel_id": sn.get("channelId") or "",
            "video_title": sn.get("title") or "",
            "channel_title": sn.get("channelTitle") or "",
            "view_count": _int(stat.get("viewCount")),
            "like_count": _int(stat.get("likeCount")),
            "comment_count": _int(stat.get("commentCount")),
            "published_at": pub if pub else None,
            "fetched_at": fetched_at,
        })
    return result


def load_video_stats_to_bq(records: List[Dict[str, Any]]) -> None:
    """Video istatistiklerini yt_insight_raw.video_stats tablosuna yazar (APPEND)."""
    if not records:
        return
    client = _bq_client()
    table_id = f"{gcp_settings.project_id}.{gcp_settings.dataset_raw}.{bq_tables.video_stats}"
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND
    )
    job = client.load_table_from_json(records, table_id, job_config=job_config)
    job.result()


def load_comments_to_bq(records: List[Dict[str, Any]]) -> None:
    """
    Yorum listesini BigQuery raw tablosuna yükler.

    WRITE_APPEND kullanılır; aynı comment_id tekrar yazılırsa duplicate satır oluşur
    (curate aşamasında LEFT JOIN ile zaten işlenmemiş olanları seçeriz).
    """
    if not records:
        return

    client = _bq_client()
    table_id = f"{gcp_settings.project_id}.{gcp_settings.dataset_raw}.{bq_tables.raw_comments}"
    job_config = bigquery.LoadJobConfig(
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND
    )
    job = client.load_table_from_json(records, table_id, job_config=job_config)
    job.result()


def run_for_video_ids(video_ids: List[str]) -> None:
    """Birden fazla video için yorumları çekip BigQuery'e yazar; video istatistiklerini de günceller."""
    all_records: List[Dict[str, Any]] = []
    for vid in video_ids:
        records = fetch_comments_for_video(vid)
        all_records.extend(records)
    load_comments_to_bq(all_records)
    # Video bazlı izlenme/begeni/yorum sayısı (videos.list API)
    stats_records = fetch_video_stats(video_ids)
    load_video_stats_to_bq(stats_records)


def run_for_channel_id(channel_id: str, max_videos: int) -> None:
    """Kanalın son N videosunu çekip her birinin yorumlarını toplar ve BigQuery'e yazar."""
    videos = list_videos_for_channel(channel_id, max_videos=max_videos)
    video_ids = [item["id"]["videoId"] for item in videos]
    run_for_video_ids(video_ids)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch YouTube comments into BigQuery.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--video-id", action="append", help="YouTube video ID (can be used multiple times).")
    group.add_argument("--channel-id", help="YouTube channel ID.")

    parser.add_argument(
        "--max-videos",
        type=int,
        default=10,
        help="Max number of recent videos when using --channel-id.",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    if args.video_id:
        run_for_video_ids(args.video_id)
    else:
        if not args.channel_id:
            raise RuntimeError("Either --video-id or --channel-id must be provided.")
        run_for_channel_id(args.channel_id, max_videos=args.max_videos)


if __name__ == "__main__":
    main()

