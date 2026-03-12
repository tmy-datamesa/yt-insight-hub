## YT Insight Hub

YouTube yorumları için **uçtan uca yorum analitiği** pipeline’ıdır:

- YouTube API’den yorum ve video istatistiklerini çeker.
- Ham veriyi temizleyip BigQuery’de **raw / core / ml** katmanlarında saklar.
- LLM (OpenAI `gpt-4o-mini`) ile her yorum için:
  - genel duygu (`positive/negative/neutral/mixed`),
  - konu (`topic`),
  - aspect bazlı duygu + evidence (örn. `battery`, `storage`, `customer_service`),
  - stratejik sinyaller (satın alma niyeti, soru, rakip kıyası)
  üretir.
- Sonuçları **Streamlit** dashboard ve **Looker Studio** raporlarıyla görselleştirir.

Bu repo, küçük ama gerçekçi bir **conversational/product analytics** ürününün YouTube yorumları için uyarlanmış hali olarak tasarlandı.

<img width="1016" height="1439" alt="image" src="https://github.com/user-attachments/assets/0ca772e6-99ca-4230-817b-6f8842ee7e95" />

---

## Hızlı kurulum

```bash
git clone <repo-url>
cd yt-insight-hub
make venv
source yt/bin/activate          
make install
```

`.env` dosyasına en az şu değişkenleri ekle:

- `GCP_PROJECT_ID` – BigQuery proje ID
- `YOUTUBE_API_KEY` – YouTube Data API v3 anahtarı
- `OPENAI_API_KEY` – OpenAI anahtarı

BigQuery dataset ve tabloları oluştur:

```bash
make bq-setup
```

---

## Pipeline (özet)

Yeni bir video için tipik akış:

```bash
make fetch-comments VIDEO_ID=<video_id>   # YouTube yorumlarını ve video_stats'i çek
make curate-comments                      # Ham → curated (temiz metin, dil, reply bilgisi)
make run-inference VIDEO_ID=<video_id>    # LLM ile sentiment/topic/aspect + sinyaller
make streamlit                            # Dashboard'u aç (http://localhost:8501)
```

Veri katmanları:

- `yt_insight_raw` – ham yorumlar + video istatistikleri
- `yt_insight_core` – temizlenmiş / normalize edilmiş yorumlar
- `yt_insight_ml` – LLM çıktıları + raporlama view’leri (`comment_insights_report`, `aspect_sentiment_report`)

---

## Daha fazla detay

Teknik tasarım ve şema detayları için:

- `docs/PROJECT_GUIDE.md` – Baştan sona proje rehberi
- `docs/ONTOLOGY.md` – Topic / aspect ontolojisi ve alias’lar
- `docs/MODEL_VERSIONS.md` – LLM versiyonları (v1–v4, prompt chaining + CoT + mixed sentiment)
- `docs/DATA_SOURCES.md` – BigQuery tabloları ve Streamlit/Looker alan eşlemeleri

# YT Insight Hub

**Looker Dashboard:** [YouTube Comment Insights](https://lookerstudio.google.com/s/gbf4u5q04WM)

YouTube videolarındaki yorumları toplayan, LLM ile duygu/konu/aspect analizi yapan ve sonuçları **Streamlit** ile görselleştiren bir projedir. Veri **BigQuery**’de saklanır; isteğe bağlı **Looker Studio** ile raporlanabilir.

<img width="1015" height="1439" alt="image" src="https://github.com/user-attachments/assets/3f401369-55f1-41d9-81a9-8ae636823e3f" />

---

## Proje ne yapar? (Özet)

1. **Yorum çekme:** YouTube Data API ile bir videonun yorumları ve video istatistikleri (izlenme, beğeni) alınır → `yt_insight_raw.comments` ve `yt_insight_raw.video_stats`.
2. **Temizleme (curation):** Ham yorumlar temizlenir, dil tespiti yapılır → `yt_insight_core.comments_curated`.
3. **LLM analizi:** Her yorum için genel duygu (positive/negative/neutral), konu (topic), aspect bazlı duygu ve niyet sinyalleri (satın alma niyeti, soru, rakip kıyası) üretilir → `yt_insight_ml.comment_insights`.
4. **Raporlama view’leri:** `comment_insights_report` (yorum başına tek satır, iş dostu kolonlar) ve `aspect_sentiment_report` (aspect satır satır). Looker veya başka BI araçları bu view’lere bağlanabilir.
5. **Dashboard:** Streamlit ile video seçilir; o videoya ait sentiment, topic, intent, aspect ve sık ifadeler (N-gram) gösterilir.

Tüm akış **komut satırı** (Make) ile çalıştırılır; veri tek kaynak (BigQuery) üzerinden tutulur (MLOps: tek kaynak, tek pipeline).

---

## Veri akışı (teknik)

```
YouTube API  →  raw (comments, video_stats)
                     ↓
              curate-comments (temizlik + dil)
                     ↓
              comments_curated
                     ↓
              run-inference (LLM: OpenAI)
                     ↓
              comment_insights
                     ↓
              comment_insights_report (view)
              aspect_sentiment_report (view)
                     ↓
              Streamlit / Looker Studio
```

- **raw:** Ham yorum + video istatistikleri.
- **core:** Temizlenmiş, dil etiketli yorumlar (curation).
- **ml:** LLM çıktıları (comment_insights) ve raporlama view’leri (comment_insights_report, aspect_sentiment_report) ve isteğe bağlı n-gram tablosu (comment_ngrams).

---

## Kurulum (sırasıyla)

### 1. Repo ve sanal ortam

```bash
git clone <repo-url>
cd yt-insight-hub
make venv
source yt/bin/activate   # Windows: yt\Scripts\activate
make install
```

### 2. Ortam değişkenleri

- Proje kökünde `.env` dosyası oluştur (veya `.env.example`’dan kopyala). İçinde en az şunlar olmalı:
  - `GCP_PROJECT_ID` — BigQuery proje ID’si
  - `YOUTUBE_API_KEY` — YouTube Data API v3 anahtarı
  - `OPENAI_API_KEY` — LLM için OpenAI API anahtarı
- BigQuery erişimi için:
  ```bash
  export GOOGLE_APPLICATION_CREDENTIALS="/yol/service-account.json"
  ```

### 3. BigQuery’yi oluştur (bir kez)

```bash
make bq-setup
```

Bu komut `yt_insight_raw`, `yt_insight_core`, `yt_insight_ml` dataset’lerini ve içlerindeki tablo/view’leri oluşturur (comments, video_stats, comments_curated, comment_insights, comment_insights_report, aspect_sentiment_report DDL’leri `sql/` altındaki dosyalardan okunur).

---

## Yeni video ekleme (pipeline)

Her video için sırayla:

```bash
# 1) Yorumları çek (VIDEO_ID = YouTube URL’deki v= veya youtu.be/ sonrası)
make fetch-comments VIDEO_ID=<video_id>

# 2) Ham yorumları temizle
make curate-comments

# 3) LLM ile analiz (sentiment, topic, aspect, intent)
make run-inference VIDEO_ID=<video_id>
```

Bittikten sonra `make streamlit` ile dashboard’da bu videoyu seçebilirsin.

---

## Make komutları

| Komut | Açıklama |
|-------|----------|
| `make venv` | Sanal ortam (yt) oluşturur |
| `make install` | Bağımlılıkları kurar |
| `make bq-setup` | BigQuery dataset ve tablolarını oluşturur |
| `make fetch-comments VIDEO_ID=xxx` | Tek videonun yorumlarını çeker |
| `make fetch-comments-channel CHANNEL_ID=xxx MAX_VIDEOS=N` | Kanalın son N videosunun yorumlarını çeker |
| `make curate-comments` | Raw → curated (temizleme + dil tespiti) |
| `make run-inference VIDEO_ID=xxx` | LLM analizi; sonuçlar `comment_insights` tablosuna yazılır |
| `make streamlit` | Streamlit dashboard’u başlatır |
| `make clear-insights` | `comment_insights` tablosunu sıfırlar (geri alınamaz) |

---

## Streamlit dashboard

```bash
make streamlit
```

Tarayıcıda `http://localhost:8501` açılır.

- **Sol menü:** Video listesi (kanal + video adı + yorum sayısı). Bir video seç.
- **Sayfa:** Seçilen videoya ait özet metrikler (izlenme, beğeni, analiz edilen yorum sayısı), kanal etkileşimi (top-level, kanal cevapları), stratejik sinyaller (satın alma niyeti, soru, rakip), intent/topic/sentiment dağılım grafikleri, aspect bazlı sentiment tablosu, sık geçen ifadeler (bigram/trigram) ve yorum listesi (filtrelenebilir) gösterilir.

Bir video için “Bu video için henüz LLM tahmini yok” görürsen, ekrandaki `make run-inference VIDEO_ID=...` komutunu çalıştır.

---

## Looker Studio

**Dashboard:** [YouTube Comment Insights](https://lookerstudio.google.com/s/gbf4u5q04WM)

BigQuery’ye bağlanıp aynı veriyi raporlamak için:

1. Looker Studio → Create → Data source → BigQuery.
2. Proje → `yt_insight_ml` → `comment_insights_report` (veya `aspect_sentiment_report`) seç.
3. Rapor oluştur; dimension olarak `video_title`, `topic`, `general_sentiment`, `comment_type`, `intent_category` vb., metrik olarak Record count kullan.

---

## Klasör yapısı (özet)

```
yt-insight-hub/
├── backend/
│   ├── config/       # settings, BigQuery kurulumu
│   ├── ingestion/    # YouTube çekme, curation
│   ├── inference/    # LLM analizi, ontoloji (topic/aspect listesi)
│   └── analytics/    # (boş; ileride ek analizler için)
├── frontend/
│   └── app.py        # Streamlit uygulaması
├── sql/              # BigQuery DDL ve view’ler
├── Makefile          # Tüm komutlar
├── requirements.txt
└── README.md
```

- **Ontoloji:** Topic ve aspect listeleri `backend/inference/ontology.py` içindedir; prompt ve normalizasyon buradan beslenir.
- **Raporlama:** Ana view `comment_insights_report`; kolonlar arasında `comment_type` (Top-level / Reply / Creator reply) ve `intent_category` (Pre-Purchase Intent, Information Seeking, Comparison, Complaint, Post-Purchase, Irrelevant, Other) vardır.


---

## not

MVP projesi; eğitim veya iç deneme için uygundur. YouTube API ve OpenAI kullanım politikalarına uygun kullanım kullanıcıya aittir.

**Repo:** [github.com/tmy-datamesa/yt-insight-hub](https://github.com/tmy-datamesa/yt-insight-hub)
