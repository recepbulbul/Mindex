# Mindex Belgeleri — Başlangıç Noktası

Bu klasör, Mindex projesinin analiz ve tasarım belgelerini içerir. Projeyi hiç bilmiyorsanız buradan başlayın: önce aşağıdaki kısa girişi, sonra okuma sırasını izleyin. Anlamadığınız bir terim olursa sayfanın sonundaki [terimler sözlüğüne](#terimler-sözlüğü) bakın.

## Mindex nedir?

Mindex, kripto paralar üzerinde **gerçek para kullanmadan** (paper-trading) işlem yapan yazılım ajanlarının aynı piyasada yarıştığı bir simülasyon arenasıdır. Arenada kural tabanlı ajanlar, pekiştirmeli öğrenme (PPO) ajanı ve büyük dil modeli (LLM) ile karar veren ajanlar bulunur. LLM ajanları geçmiş işlemlerinden ders çıkarıp kalıcı bir **hafızaya** yazabilir ve bu dersleri diğer ajanlarla bir **forumda** paylaşabilir; forumda kime ne kadar güvenileceği, tavsiyelerin geçmişte tutup tutmadığına göre hesaplanır. Projenin araştırma sorusu şudur: *Hafıza ve paylaşım, LLM ajanlarının riske göre düzeltilmiş getirisini artırır mı, yoksa hepsinin aynı anda aynı şeyi yaptığı bir sürü davranışına mı yol açar?* Bu soru, hafıza ve forumun açılıp kapatıldığı dört deney koşuluyla (C0–C3) ölçülür.

Proje, "Yapay Zeka ve Veri Mühendisliği Tasarımı" dersi için yapılmıştır. Plan ve isterler kökteki öneri formundan (`Mindex_Oneri_Formu_230291001_230291012.pdf`) gelir.

## Okuma sırası

Belgeler birbirinin üzerine kurulur. İlk okumada şu sırayı öneririz:

1. **[Use case modeli](01-use-cases.md)** — Sistemi kim, ne için kullanır?
2. **[Sistem mimarisi](02-architecture.md)** — Sistem hangi parçalardan oluşur, parçalar nasıl konuşur?
3. **[Akış diyagramları](03-flows.md)** — Üç kritik işlem adım adım nasıl yürür, hata olunca ne olur?
4. **[AI pipeline](04-ai-pipeline.md)** — Veriden karara, karardan öğrenmeye yapay zekâ hattı ve deney koşulları.
5. **[ER diyagramı](05-er-diagram.md)** ve **[veri sözlüğü](06-data-dictionary.md)** — Veritabanında neler saklanır? (SQL karşılığı: [`db/schema.sql`](db/schema.sql))
6. **[Teknoloji yığını](07-tech-stack.md)** — Hangi araçlar neden seçildi?
7. **[Veri hattı, simülatör ve baseline](08-data-pipeline-baseline.md)** — İlk çalışan kod ve ilk ölçüm sonuçları (hedeflerin hangisi tuttu, hangisi tutmadı).
8. **[Arayüz tasarım sistemi](09-design-system.md)** — Arayüzün görsel kuralları.

Yalnızca sonuçları merak ediyorsanız doğrudan 8. belgenin [sonuçlar bölümüne](08-data-pipeline-baseline.md#sonuclar) gidebilirsiniz.

## Belge haritası

| # | Belge | Ne anlatır? | Kim için öncelikli? | İş paketi |
|---|---|---|---|---|
| 1 | [Use case modeli](01-use-cases.md) | Kullanıcılar (aktörler) ve sistemle yapabildikleri; her kullanım senaryosunun hata durumları | Ders hocası, ürün bakışı isteyen herkes | İP1 |
| 2 | [Sistem mimarisi](02-architecture.md) | Sistemin bileşenleri, nerede çalıştıkları ve temel tasarım kararlarının gerekçeleri | Yeni geliştirici, hoca | İP1 |
| 3 | [Akış diyagramları](03-flows.md) | Deney yürütme, LLM karar döngüsü ve canlı veri akışı; hata dalları | Backend geliştiricisi, hoca | İP1 |
| 4 | [AI pipeline](04-ai-pipeline.md) | Veri ayrımı, eğitilen modeller, karar ve öğrenme döngüsü, değerlendirme; geleceği görme hatasına karşı önlemler | Yapay zekâ tarafında çalışan, hoca | İP1 |
| 5 | [ER diyagramı](05-er-diagram.md) | Veritabanı tabloları ve aralarındaki ilişkiler | Backend / veri geliştiricisi | İP2 |
| 6 | [Veri sözlüğü](06-data-dictionary.md) | Her tablonun her alanının tipi, kısıtı ve anlamı | Backend / veri geliştiricisi | İP2 |
| — | [`db/schema.sql`](db/schema.sql) | Veritabanını oluşturan SQL komutları (DDL) | Backend geliştiricisi | İP2 |
| 7 | [Teknoloji yığını](07-tech-stack.md) | Kullanılan kütüphane ve araçlar, seçim gerekçeleri ve hangi iş paketinde devreye girdikleri | Yeni geliştirici, hoca | İP2 |
| 8 | [Veri hattı, simülatör ve baseline](08-data-pipeline-baseline.md) | Gerçek veriyle çalışan ilk kod, LLM hız ölçümü ve ilk metriklerin hedeflerle karşılaştırılması | Hoca (sonuçlar), geliştirici (komutlar) | İP3 |
| 9 | [Arayüz tasarım sistemi](09-design-system.md) | Renkler, yazı tipleri, bileşenler ve erişilebilirlik kuralları | Frontend geliştiricisi | İP2–İP3 |

<a id="isterler"></a>

## İsterler ve GitHub Issues

Öneri formundaki her ister GitHub'da bir issue olarak takip edilir. Belgelerin başındaki "İlgili isterler" satırları bu tabloya bağlanır.

| İster | Kısaca | Issue |
|---|---|---|
| F1 | Kimlik doğrulama: JWT ile giriş, araştırmacı/izleyici rolleri | [#7](https://github.com/recepbulbul/Mindex/issues/7) |
| F2 | Deney yönetimi: deney oluşturma, YAML olarak dışa aktarma | [#8](https://github.com/recepbulbul/Mindex/issues/8) |
| F3 | Replay simülasyonu: hız ayarı, duraklat/devam, aynı seed ile aynı sonuç | [#9](https://github.com/recepbulbul/Mindex/issues/9) |
| F4 | Canlı paper-trading: Binance canlı akışı, otomatik yeniden bağlanma | [#10](https://github.com/recepbulbul/Mindex/issues/10) |
| F5 | Canlı borsa ekranı: mum grafiği, işlem işaretleri, lider tablosu | [#11](https://github.com/recepbulbul/Mindex/issues/11) |
| F6 | Ajan detayı: portföy geçmişi, karar gerekçesi, kullanılan anılar, güven skorları | [#12](https://github.com/recepbulbul/Mindex/issues/12) |
| F7 | Forum ve hafıza tarayıcı: güven görselleştirme, rejime göre filtre, arama | [#13](https://github.com/recepbulbul/Mindex/issues/13) |
| F8 | Raporlama: Sharpe, MDD, getiri, sürü korelasyonu, CSV/PDF | [#14](https://github.com/recepbulbul/Mindex/issues/14) |
| F9 | Ajan eklenti arayüzü (`BaseAgent`) ve MCP sunucusu | [#15](https://github.com/recepbulbul/Mindex/issues/15) |
| NF1 | Performans: karar p95 < 10 sn, tick→ekran p95 < 500 ms, 50 izleyici | [#16](https://github.com/recepbulbul/Mindex/issues/16) |
| NF2 | Güvenilirlik: şema doğrulama, yeniden deneme, güvenli varsayılan, checkpoint | [#17](https://github.com/recepbulbul/Mindex/issues/17) |
| NF3 | Güvenlik: Argon2id, `.env`, hız sınırlama, OWASP LLM01, MCP yetkisi | [#18](https://github.com/recepbulbul/Mindex/issues/18) |
| NF4 | Gözlemlenebilirlik: OpenTelemetry, structlog JSON, Langfuse | [#19](https://github.com/recepbulbul/Mindex/issues/19) |
| NF5 | Tekrarlanabilirlik ve bakım: uv kilidi, Docker, seed, CI, ≥ %70 test kapsamı | [#20](https://github.com/recepbulbul/Mindex/issues/20) |

Tamamlanan iş paketleri de kapalı issue olarak durur: İP1 [#21](https://github.com/recepbulbul/Mindex/issues/21), İP2 [#22](https://github.com/recepbulbul/Mindex/issues/22), İP3 [#23](https://github.com/recepbulbul/Mindex/issues/23).

## Diyagramları okuma

Belgelerdeki diyagramlar [Mermaid](https://mermaid.js.org/) ile yazılmıştır; GitHub bunları otomatik olarak çizer. Her diyagramın altında "Nasıl okunur" açıklaması vardır. Genel kurallar:

- **Dikdörtgen kutu** bir adımı ya da bileşeni, **silindir** bir veri deposunu (veritabanı, dosya), **eşkenar dörtgen** bir karar noktasını (evet/hayır sorusu) gösterir.
- **Düz ok** işin ya da verinin akış yönünü, **kesikli ok** isteğe bağlı ya da arka planda olan bir bağlantıyı gösterir.
- **Kırmızı kutular** hata dallarıdır: bir şey ters gittiğinde sistemin ne yaptığını gösterir.
- **Yeşil kutular** (yalnızca AI pipeline'da) projenin özgün katkısı olan bileşenlerdir.

## Terimler sözlüğü

### Proje ve süreç terimleri

| Terim | Anlamı |
|---|---|
| **İP1–İP10** | Öneri formundaki 10 haftalık iş planının iş paketleri; her hafta bir paket. Belgelerde ve kodda kısaca **P1–P10** olarak da geçer (P3 = İP3). İP1: analiz ve diyagramlar · İP2: tıklanabilir prototip, veritabanı tasarımı · İP3: veri hattı, simülatör, ilk ölçümler · İP4: FastAPI iskeleti, kimlik doğrulama, PPO ve HMM · İP5: arayüzün gerçek API'ye bağlanması, hafıza ve post-mortem · İP6: güven tabanlı forum, Langfuse, C0–C3 koşuları · İP7: uçtan uca MVP, canlı mod, MCP sunucusu · İP8: sunucuya dağıtım · İP9: stres, güvenlik ve uç durum testleri · İP10: final rapor, kılavuz, sunum. |
| **F1–F9** | Fonksiyonel isterler: sistemin *ne yapması* gerektiği (örn. F2 deney oluşturma). Tam liste için yukarıdaki tabloya bakın. |
| **NF1–NF5** | Fonksiyonel olmayan isterler: sistemin *nasıl* çalışması gerektiği (performans, güvenilirlik, güvenlik, izlenebilirlik, tekrarlanabilirlik). |
| **Use case (kullanım senaryosu)** | Bir kullanıcının sistemle bir amaca ulaşmak için yaptığı etkileşim (örn. "deney oluştur"). |
| **Aktör** | Sistemle etkileşen kişi ya da dış sistem (araştırmacı, Binance, yerel LLM…). |
| **ADR** | *Architecture Decision Record*, mimari karar kaydı: bir tasarım kararını, gerekçesini ve reddedilen alternatifi kısaca yazan not. |
| **Baseline (temel çizgi)** | Diğer sonuçların karşılaştırılacağı başlangıç ölçümü. Mindex'te baseline, hafızasız ve forumsuz (C0) LLM ajanı ile kural tabanlı ajanların ilk sonuçlarıdır. |
| **Seed** | Rastgele sayı üretecinin başlangıç değeri. Aynı seed ile aynı deney birebir aynı sonucu verir. |
| **Ablasyon** | Bir sistemin parçalarını tek tek kapatıp her parçanın etkisini ölçme yöntemi. C0–C3 koşulları bir ablasyon çalışmasıdır. |

### Deney koşulları

| Koşul | Kişisel hafıza | Forum | Açıklama |
|---|:-:|:-:|---|
| **C0** | — | — | Hafızasız, forumsuz LLM ajanı. Karşılaştırma tabanı. |
| **C1** | ✔ | — | Ajan yalnızca kendi geçmiş derslerini hatırlar. |
| **C1′** (`C1_NO_REGIME`) | ✔ | — | C1 ile aynı, ama dersler piyasa rejimine göre öne çıkarılmaz. Rejim etiketinin katkısını ölçer. |
| **C2** | ✔ | ✔ | Ajanlar forumda tavsiye paylaşır; herkesin sözü eşit ağırlıktadır. |
| **C3** | ✔ | ✔ | Forumdaki tavsiyeler, gönderenin geçmişteki isabetine göre ağırlıklandırılır (Beta güven skoru). |

### Finans ve ölçüm terimleri

| Terim | Anlamı |
|---|---|
| **Paper-trading** | Gerçek piyasa fiyatlarıyla ama sanal parayla yapılan işlem. Hiçbir gerçek borsa hesabına bağlanılmaz. |
| **Replay (tekrar) modu** | Geçmiş fiyat verisinin gün gün yeniden oynatıldığı simülasyon. Hızlandırılabilir, durdurulabilir. Karşıtı **canlı mod**: Binance'ten anlık gelen fiyatlarla çalışır. |
| **Al-ve-tut (buy-and-hold)** | İlk gün alıp hiç satmama stratejisi. Mindex'te ölçüt olarak BTC al-ve-tut (`buy-hold-btc`) kullanılır. |
| **Getiri** | Dönem sonundaki portföy değerinin başlangıca göre yüzde değişimi. |
| **Sharpe oranı** | Riske göre düzeltilmiş getiri: günlük getirilerin ortalamasının standart sapmasına oranı, yıllıklandırılmış (kriptoda yılda 365 gün). Yüksek olması iyidir; negatif değer, ajanın zarar ettiğini gösterir. |
| **MDD (maksimum düşüş, *maximum drawdown*)** | Portföy değerinin gördüğü en yüksek noktadan sonraki en derin düşüşü (%). Düşük olması iyidir; %50 MDD, portföyün bir noktada zirvesinin yarısına indiği anlamına gelir. |
| **Sürü korelasyonu** | Ajanların aynı günlerde aynı yönde pozisyon değiştirme eğilimi. Ajan çiftleri arasındaki günlük pozisyon değişimlerinin ortalama Pearson korelasyonudur; 1'e yakınsa ajanlar "sürü gibi" davranıyor demektir. |
| **Pozisyon** | Bir varlıkta tutulan miktar. "Pozisyonu korumak", hiçbir işlem yapmadan mevcut dağılımı aynen bırakmaktır. |
| **Long-only, kaldıraçsız** | Ajanlar yalnızca sahip oldukları parayla alım yapabilir; açığa satış (düşüşten kazanmak için borç alıp satmak) ve borçla işlem yoktur. |
| **Komisyon / kayma (slippage)** | Komisyon: her işlemde borsaya ödenen ücret (%0,1). Kayma: emrin beklenen fiyattan biraz kötü gerçekleşmesi; **bp** (baz puan) cinsinden, 1 bp = %0,01. |
| **PnL** | *Profit and Loss*, kâr/zarar. |
| **OHLCV** | Bir zaman dilimindeki fiyat özeti: açılış (*open*), en yüksek (*high*), en düşük (*low*), kapanış (*close*) ve işlem hacmi (*volume*). Grafikte bir **mum** olarak çizilir. |
| **Fear & Greed endeksi** | Kripto piyasasındaki genel duyarlılığı 0 (aşırı korku) ile 100 (aşırı açgözlülük) arasında özetleyen günlük endeks. |
| **Funding rate** | Vadeli işlem (perpetual) piyasasında alıcı ve satıcılar arasındaki periyodik ödeme oranı; piyasanın yön beklentisi hakkında ipucu verir. |
| **Rejim** | Piyasanın genel durumu: yükseliş (*bull*), düşüş (*bear*) ya da yatay (*sideways*). HMM modeliyle tahmin edilir. |
| **p50 / p95** | Yüzdelikler: ölçümlerin %50'si / %95'i bu değerin altındadır. "p95 < 10 sn", çağrıların %95'inin 10 saniyeden kısa sürmesi demektir. |
| **Blok bootstrap, %95 GA** | Zaman serisini bloklar halinde yeniden örnekleyerek iki koşul arasındaki farkın tesadüf olup olmadığını sınayan yöntem. GA: güven aralığı. |

### Yapay zekâ terimleri

| Terim | Anlamı |
|---|---|
| **LLM** | *Large Language Model*, büyük dil modeli. Mindex'te dizüstünde yerel çalışan Qwen3.5-9B. |
| **llama.cpp** | LLM'leri bulut olmadan, kişisel bilgisayarda çalıştıran açık kaynak yazılım. |
| **Q4_K_M** | Modelin 4 bitlik sıkıştırılmış (nicemlenmiş) sürümü; 8 GB ekran kartı belleğine sığması için. |
| **Prompt** | LLM'e verilen girdi metni. Sürümü (`decision-v1` gibi) kaydedilir ki sonuçlar tekrarlanabilsin. |
| **JSON şeması ile kısıtlı üretim** | LLM'in yalnızca önceden tanımlı yapıya uyan bir JSON yanıt üretmeye zorlanması; bozuk yanıt riskini azaltır. |
| **Düşünme modu** | Modelin cevap vermeden önce uzun bir iç akıl yürütme metni ürettiği mod. Karar adımında hız için kapalıdır, ders yazarken açıktır. |
| **Post-mortem** | Bir pozisyon kapandıktan sonra yapılan değerlendirme: "Ne oldu, başka ne yapabilirdim?" |
| **Karşı-olgusal (counterfactual) PnL** | "Bu işleme hiç girmeseydim / yarısıyla girseydim / zarar-kes koysaydım ne olurdu?" sorularının sayısal cevaplarını içeren tablo. LLM dersini bu tabloya dayanarak yazar. |
| **Hafıza** | Ajanın kabul edilmiş derslerinin saklandığı, anlam benzerliğiyle aranabilen veritabanı (pgvector). |
| **Embedding (vektör temsili)** | Bir metnin anlamını sayı dizisine çeviren temsil; benzer anlamlı metinlerin vektörleri birbirine yakındır. |
| **Hibrit arama** | Anlam benzerliği (vektör) ile anahtar kelime eşleşmesini (BM25 / tam metin arama) birleştiren arama. |
| **Beta güven skoru** | Bir ajanın diğerine güveni: `(a+1)/(a+b+2)`, burada `a` doğrulanan, `b` çürüyen tavsiye sayısıdır. Hiç bilgi yokken 0,5'ten başlar. |
| **HMM** | *Hidden Markov Model*, gizli Markov modeli. Fiyat hareketlerinden piyasa rejimini tahmin eder. |
| **PPO** | *Proximal Policy Optimization*, bir pekiştirmeli öğrenme (RL, *reinforcement learning*) algoritması. Arenadaki RL ajanı bununla eğitilir. |
| **Look-ahead bias (geleceği görme hatası)** | Modelin karar anında henüz bilinmemesi gereken bir bilgiye erişmesi. Örn. LLM, test dönemindeki fiyatları eğitim verisinden ezberlemiş olabilir; bu yüzden test dönemi model yayımından sonradır ve varlık adları gizlenir. |
| **Eğitim / doğrulama / test ayrımı** | Veri zamana göre üçe bölünür: eğitim (model öğrenir), doğrulama (ayar yapılır), test (yalnızca en sonda bir kez açılır, "mühürlü"). |
| **Prompt injection (OWASP LLM01)** | Bir metnin içine gizlenmiş talimatlarla LLM'i kandırma saldırısı. Forum mesajları bu yüzden güvenilmeyen veri sayılır. |

### Teknik terimler

| Terim | Anlamı |
|---|---|
| **MCP** | *Model Context Protocol*: dış LLM ajanlarının standart araçlar (piyasa verisi oku, emir ver) üzerinden sisteme bağlanmasını sağlayan protokol. |
| **JWT** | *JSON Web Token*: girişten sonra kullanıcıya verilen, kimliği ve rolü taşıyan imzalı anahtar. |
| **REST / WebSocket (WS, WSS)** | REST: istek-cevap tarzı web API'si. WebSocket: sunucunun tarayıcıya sürekli veri itebildiği açık bağlantı; WSS onun şifreli hâli. |
| **Redis Streams** | Deney işlerinin kuyruğa yazıldığı ve işçiler tarafından okunduğu mesaj kuyruğu. |
| **İşçi (worker)** | Uzun süren deneyleri web sunucusundan ayrı olarak çalıştıran arka plan süreci. |
| **Checkpoint** | Simülasyonun her gün sonunda kaydedilen durumu; bir çökme olursa kaldığı yerden devam edilir. |
| **pgvector, HNSW** | pgvector: PostgreSQL'e vektör saklama ve benzerlik araması ekleyen eklenti. HNSW: bu aramayı hızlandıran indeks türü. |
| **Parquet, anlık görüntü (snapshot)** | Parquet: sütun tabanlı veri dosyası biçimi. Anlık görüntü: belirli bir anda çekilmiş ve SHA-256 özetiyle mühürlenmiş veri kopyası; deneyler hep aynı veriyi okusun diye. |
| **Langfuse, OpenTelemetry (OTel)** | Her LLM çağrısının girdisini, çıktısını ve süresini kaydeden izleme araçları. |
| **CI** | *Continuous Integration*: her commit'te testleri ve denetimleri otomatik çalıştıran süreç (GitHub Actions). |
| **EDA** | *Exploratory Data Analysis*, keşifsel veri analizi. |
| **MSW** | *Mock Service Worker*: prototipin gerçek sunucu yokken sahte API ile çalışmasını sağlayan kütüphane. |
