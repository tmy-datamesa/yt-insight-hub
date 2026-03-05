## Ontoloji (Topic & Aspect Rehberi)

Bu dosya, projede kullanılan **topic** ve **aspect** ontolojisini özetler.  
Amaç, LLM’in ve raporların **tek bir ortak sözlükten** beslenmesini sağlamak ve
“other” oranını düşük tutmaktır.

- **Topic**: Yorumun **ana konusu** (tek etiket).
- **Aspect**: Yorumda değerlendirilen **özellik/boyut** (bir yorumda birden fazla aspect olabilir).

Tüm liste ve normalizasyon mantığı `backend/inference/ontology.py` içinde tanımlıdır.

---

## Topic Listesi

Yorumun ana konusu sadece aşağıdaki değerlerden biri olabilir:

- **product_review**: Genel ürün yorumu; belirli bir parça yerine ürünün tamamı hakkında konuşur.
- **price_discussion**: Fiyat, indirim, pahalı/ucuz, bütçe ile ilgili yorumlar.
- **performance_discussion**: Hız, akıcılık, işlemci, oyun performansı vb.
- **camera_discussion**: Kamera kalitesi, fotoğraf/video performansı.
- **battery_discussion**: Pil süresi, şarj hızı, batarya ömrü.
- **software_ui**: Arayüz, işletim sistemi, güncellemeler, yazılım deneyimi.
- **sponsorship_trust**: Sponsorlu içerik, reklam güvenilirliği hakkında yorumlar.
- **channel_trust**: Kanal sahibine duyulan güven, anlatım kalitesi, tarafsızlık algısı.
- **comparison**: Ürünün başka model/markalarla kıyaslanması.
- **offtopic**: Ürünle doğrudan ilgisi olmayan veya tanınmayan konu.

LLM’den gelen topic değeri, `normalize_topic()` fonksiyonu ile bu listeye
map edilir; tanınmayan veya boş değerler **offtopic** olarak kabul edilir.

---

## Aspect Listesi

Aspect, yorumun hangi boyutu değerlendirdiğini gösterir. Model, mümkün olduğunca
aşağıdaki isimleri kullanmalıdır:

- **price**: Ham fiyat seviyesi (pahalı/ucuz).
- **value_for_money**: Fiyat/performans, “paraya değer mi?” tartışmaları.
- **performance**: Genel hız, akıcılık, işlemci gücü, oyun performansı.
- **camera**: Kamera modülleri, fotoğraf/video sonuçları.
- **battery**: Pil süresi, şarj hızı, batarya ömrü.
- **display**: Ekran kalitesi, parlaklık, renkler, yenileme hızı.
- **audio**: Ses kalitesi, mikrofon, hoparlör.
- **design**: Tasarım, görünüş, ergonomi.
- **build_quality**: Malzeme kalitesi, işçilik, sağlamlık hissi.
- **software**: Arayüz, işletim sistemi, güncellemeler, yazılım hataları.
- **thermal**: Isınma, sıcaklık, fan davranışı.
- **connectivity**: 5G, Wi‑Fi, Bluetooth ve genel bağlantı sorunları.
- **durability**: Dayanıklılık, uzun ömür, zamanla bozulma.
- **storage**: Depolama kapasitesi, hafıza kartı (SD kart), toplam GB.
- **customer_service**: Servis, garanti süreci, müşteri hizmetleri kalitesi.
- **sponsorship**: Sponsorlu içerik, reklam/işbirliği ile ilgili yorumlar.
- **channel_trust**: Kanal sahibine güven, anlatımın tarafsızlığı (channel_trust hem topic hem aspect olarak kullanılabilir).
- **comparison**: Diğer ürünlerle kıyaslama, “X yerine Y mi?” tartışmaları.
- **other**: Gerçekten yukarıdakilere girmeyen nadir durumlar için ayrılmıştır.

LLM’den gelen her aspect değeri, `normalize_aspect()` ile bu listeye
normalize edilir. Tanınmayan veya boş değerler **other** olur; bu nedenle
prompt’ta mümkün olduğunca yukarıdaki isimlerden birinin seçilmesi istenir.

---

## Sentiment skalası (genel ve aspect)

Ontolojinin bir parçası olarak sentiment etiketi de **kapalı bir skala** ile tanımlanır:

- **positive**: Net biçimde olumlu duygu (övgü, memnuniyet, tavsiye).
- **negative**: Net biçimde olumsuz duygu (şikâyet, hayal kırıklığı, memnuniyetsizlik).
- **neutral**:
  - Net pozitif/negatif sinyal yoksa veya yorum bilgilendirici/nesnel ise (ör. “Kutudan şarj kablosu çıkıyor.”),
  - Veya duygu karışık ama zayıf/kararsızsa.
- **mixed**:
  - Aynı yorum içinde **hem güçlü pozitif hem güçlü negatif** sinyaller varsa,
  - Örn. “Kamerası çok iyi ama fiyatı uçuk” → ürün genelinde mixed;
  - Veya tek bir aspect için “performansı çok iyi ama çok çabuk ısınıyor” gibi hem iyi hem kötü ifadeler.

Bu skala:

- Hem **genel sentiment** (`general_sentiment`) hem de **aspect seviyesindeki sentiment** için kullanılır.
- `backend/inference/ontology.py` içindeki `SENTIMENTS` / `normalize_sentiment()` fonksiyonu, LLM’den gelen değerleri bu sete çeker; set dışındaki değerler (örn. `"olumlu"`, `"mixed feelings"`) **neutral**’a normalize edilir.

Amaç, iş tarafına yorumlanabilir ve tutarlı bir sentiment uzayı vermektir; dashboard ve raporlarda her zaman bu dört değerden biri görülür.

---

## Alias ve Normalizasyon

Ontoloji, eski/yanlış yazılmış etiketleri doğru isimlere çevirmek için
**alias** sözlükleri kullanır:

- Topic alias örneği:
  - **channel_quality → channel_trust**
- Aspect alias örnekleri:
  - **channel_quality → channel_trust**
  - **value → value_for_money**
  - **fiyat_performans → value_for_money**
  - **microphone / ses / hoparlör → audio**
  - **bağlantı / wifi / bluetooth → connectivity**
  - **dayanıklılık / ömür → durability**
  - **sd kart / hafıza kartı / hafıza / depolama → storage**
  - **servis / garanti / müşteri hizmetleri → customer_service**

Böylece:

- Prompt versiyonları veya dil karışıklıkları olsa bile,
- Dashboard ve raporlar her zaman **tutarlı topic/aspect isimleri** görür.

---

## Tasarım İlkeleri

Ontoloji aşağıdaki ilkelerle tasarlanmıştır:

- **Tek kaynak**: Topic ve aspect listeleri sadece `ontology.py` içinde tanımlanır.
- **Sınırlı ama kapsayıcı**: Liste, gerçek kullanımda sık görülen boyutları kapsar
  ama sınırsız büyümez; “other”a kaçış en aza iner.
- **İsim tutarlılığı**: `channel_quality` gibi varyantlar **alias** ile
  `channel_trust`’a normalize edilir; raporlarda karışıklık olmaz.

Yeni topic/aspect eklemek gerektiğinde:

1. `backend/inference/ontology.py` içindeki `TOPICS` / `ASPECTS` listesine ekle.
2. Gerekirse `TOPIC_ALIASES` / `ASPECT_ALIASES` içine eski isimleri map et.
3. Prompt ve dashboard metinlerini bu yeni isimle uyumlu olacak şekilde güncelle.

