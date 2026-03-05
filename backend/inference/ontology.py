"""
Topic ve aspect ontolojisi: tek kaynak.

Dashboard, prompt ve normalizasyon hep bu listeleri kullanır.
Topic–aspect isim tutarlılığı: channel_quality yerine channel_trust (tek terim).
"""

# İzin verilen sentiment değerleri (general_sentiment ve aspect.sentiment).
# mixed: hem olumlu hem olumsuz (örn. "Kamerası iyi ama fiyatı uçuk" → genel mixed; aspect'ler ayrı ayrı positive/negative)
SENTIMENTS = ["positive", "negative", "neutral", "mixed"]
SENTIMENTS_SET = frozenset(SENTIMENTS)

# Yorumun ana konusu (topic). Sadece bu değerler kullanılır.
TOPICS = [
    "product_review",
    "price_discussion",
    "performance_discussion",
    "camera_discussion",
    "battery_discussion",
    "software_ui",
    "sponsorship_trust",
    "channel_trust",  # kanal güveni / sunum kalitesi (topic ve aspect aynı isim)
    "comparison",
    "offtopic",
]

# Yorumda değerlendirilen boyut (aspect). "other" sadece gerçekten listede yoksa.
# Geniş liste: model "other"a kaçmasın diye sık kullanılan boyutlar eklendi.
ASPECTS = [
    "price",
    "value_for_money",  # fiyat/performans, değer, bütçe
    "performance",
    "camera",
    "battery",
    "display",
    "audio",  # ses, mikrofon, hoparlör
    "design",
    "build_quality",
    "software",
    "thermal",
    "connectivity",  # 5g, wifi, bluetooth, bağlantı
    "durability",  # dayanıklılık, ömür
    "storage",  # hafıza, sd kart, depolama
    "customer_service",  # servis, garanti, müşteri hizmetleri
    "sponsorship",
    "channel_trust",
    "comparison",
    "other",
]

TOPICS_SET = frozenset(TOPICS)
ASPECTS_SET = frozenset(ASPECTS)

# Eski / yanlış isimleri doğruya map et (örn. prompt v1'den gelen channel_quality)
TOPIC_ALIASES = {
    "channel_quality": "channel_trust",
}
ASPECT_ALIASES = {
    "channel_quality": "channel_trust",
    "value": "value_for_money",
    "fiyat_performans": "value_for_money",
    "microphone": "audio",
    "ses": "audio",
    "hoparlör": "audio",
    "bağlantı": "connectivity",
    "wifi": "connectivity",
    "bluetooth": "connectivity",
    "dayanıklılık": "durability",
    "ömür": "durability",
    "sd kart": "storage",
    "sdcard": "storage",
    "hafıza kartı": "storage",
    "hafıza": "storage",
    "depolama": "storage",
    "servis": "customer_service",
    "garanti": "customer_service",
    "garanti süresi": "customer_service",
    "müşteri hizmetleri": "customer_service",
    "müşteri hizmeti": "customer_service",
}


def normalize_topic(value: str) -> str:
    """Geçerli topic döner; bilinmeyen veya alias ise offtopic veya eşlenen değer."""
    if not value or not isinstance(value, str):
        return "offtopic"
    v = value.strip().lower()
    if v in TOPICS_SET:
        return v
    if v in TOPIC_ALIASES:
        return TOPIC_ALIASES[v]
    return "offtopic"


def normalize_aspect(value: str) -> str:
    """Geçerli aspect döner; bilinmeyen veya alias ise other veya eşlenen değer."""
    if not value or not isinstance(value, str):
        return "other"
    v = value.strip().lower()
    if v in ASPECTS_SET:
        return v
    if v in ASPECT_ALIASES:
        return ASPECT_ALIASES[v]
    return "other"


def normalize_sentiment(value: str) -> str:
    """Geçerli sentiment döner; set dışındaysa neutral."""
    if not value or not isinstance(value, str):
        return "neutral"
    v = value.strip().lower()
    if v in SENTIMENTS_SET:
        return v
    return "neutral"
