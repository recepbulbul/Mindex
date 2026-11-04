# 9. Arayüz Tasarım Sistemi

> **Bu belge ne anlatır?** Mindex web arayüzünün görsel dilini tanımlar: renkler, yazı tipleri, bileşenler, erişilebilirlik ve performans kuralları.
>
> **Neden önemli?** Arayüzün tüm ekranlarda tutarlı görünmesini ve renk körlüğü olanlar dahil herkes tarafından okunabilmesini sağlar. Yeni bir ekran eklenirken buradaki kurallara uyulur.
>
> **İlgili isterler:** [F5 #11](https://github.com/recepbulbul/Yunus_Hoca_Proje/issues/11) · [F6 #12](https://github.com/recepbulbul/Yunus_Hoca_Proje/issues/12) · [F7 #13](https://github.com/recepbulbul/Yunus_Hoca_Proje/issues/13) · [F8 #14](https://github.com/recepbulbul/Yunus_Hoca_Proje/issues/14)
>
> **İş paketi:** İP2–İP3 · **Önceki belge:** [Veri hattı, simülatör ve baseline](08-data-pipeline-baseline.md) · Terimler için: [belge dizini ve sözlük](README.md#terimler-sözlüğü)

Bu belge çoğunlukla frontend geliştiricileri içindir. Kısaltmalar: **token** tasarımda tek yerde tanımlanan ve her yerde adıyla kullanılan renk/ölçü değişkeni; **kontrast oranı** (örn. 4,5:1) metin ile zemin arasındaki parlaklık farkı, yüksek olan daha okunaklı; **ΔE** iki rengin göze ne kadar farklı göründüğünün ölçüsü; **KPI** temel performans göstergesi; **axe** otomatik erişilebilirlik tarama aracı.

Mindex arayüzünün görsel dili bu dokümanda sabitlenmiştir. Yeni ekranlar ve bileşenler buradaki kurallara uyar; kuralı değiştirmek gerekiyorsa önce bu doküman güncellenir.

## Yön: "gece camı"

Modern ve iddialı bir finans aracı: mürekkep siyahı zemin, onu aydınlatan kobalt, camgöbeği ve mor ışık kütleleri, üstünde buzlu cam yüzeyler. Ana eylemler beyaz düğmelerle yapılır; tek vurgu kobalt → camgöbeği gradyanıdır. Sarı/altın tonları, serif başlıklar ve neon kullanılmaz.

- **Arka plan bir görseldir.** Sabit ışık kütleleri, çok soluk bir mühendislik ızgarası ve film greni (`body::before`, `body::after`). Cam kartlar bu ışığın üzerine oturur; bulanıklık bu yüzden görünür. Tanıtım sayfasında ajanları temsil eden yörüngeler (`Orbit`) ve önündeki cam arena önizlemesi bu katmanlı etkiyi büyütür.
- **Buzlu cam.** Kartlar zemine %4 beyaz ekler ve arkasını 24 px bulanıklaştırır (`glass`). Üstte 1 px ışık çizgisi ve derin, siyah bir gölge taşırlar.
- **Beyaz birincil düğme.** Ana eylem beyaz zemin üzerinde koyu metindir (18,7:1). İkincil eylemler cam çerçevelidir.
- **Tek vurgu gradyanı.** Kobalt → camgöbeği (`bg-brand`) yalnızca işaretlerde kullanılır: logo, aktif menü çizgisi, lider çubuğu, oynatma ilerlemesi, bölüm çizgileri (`rule-accent`) ve başlıklardaki vurgu kelimeleri (`text-brand`).
- **Başlıklar.** Geist, yarı kalın, çok sıkı harf aralığı; sayfa başlıkları yukarıdan aşağı solan beyaz gradyan (`text-headline`) taşır.
- **Kaydırma.** Tanıtım sayfasındaki bölümler kaydırıldıkça yükselir (`reveal`), arena önizlemesi paralaks hareketi yapar (`parallax`). Yalnızca CSS (`animation-timeline: view()`); `prefers-reduced-motion` açıksa ya da tarayıcı desteklemiyorsa her şey doğrudan görünür.

## Tokenlar

Tek token seti [`frontend/src/index.css`](../frontend/src/index.css) içinde `:root` altındadır; yazdırma için aynı dosyada açık renk değerleri tanımlanır. Bileşenler ham renk değil, yalnızca token kullanır.

| Token | Değer | Görev |
|---|---|---|
| `background` | `#05060b` | Mürekkep siyahı zemin |
| `card` · `elevated` · `muted` | %4 · %7 · %8 beyaz | Cam katmanları |
| `foreground` · `muted-foreground` | `#f4f6fb` · `#9aa3b5` | Metin |
| `border` · `border-strong` | %9 · %16 beyaz | Ayraçlar |
| `primary` | `#8fb2ff` | Vurgu metni, simgeler, odak halkası |
| `brand-from` → `brand-to` | `#5b7cff` → `#3fd5f3` | Vurgu gradyanı (yalnızca işaretler) |
| `up` · `down` | `#5fdcb0` · `#ff7d93` | Getiri yönü, AL/SAT |
| `warn` · `info` | `#f4c35c` · `#8fb2ff` | Uyarı ve bilgi |

Kontrast, kobalt ışığın en parlak olduğu noktadaki cam üzerinde ölçüldü: ikincil metin 5,1:1, vurgu 6,1:1, yükseliş 7,6:1, düşüş 5,3:1. Kırmızı-yeşil çifti renk körlüğünde zayıf olduğu için kazanç ve kayıp her zaman `+`/`−` işareti, ok ya da "AL"/"SAT" etiketiyle birlikte gösterilir.

### Ajan kimlik renkleri

Ajan ve seri renkleri [`lib/identity.ts`](../frontend/src/lib/identity.ts) içindedir: değerli taş tonlarından oluşan kategorik bir palet. Renkler sabit sırayla atanır ve rengi sıra değil ajan belirler. BTC al-ve-tut ölçüt çizgisi sıcak gridir.

| Sıra | Ajan | Renk |
|---|---|---|
| 1 | LLM · Momentum | `#4f86d9` safir |
| 2 | LLM · Ortalamaya dönüş | `#c8743f` bakır |
| 3 | LLM · Duyarlılık | `#2fa07c` yeşim |
| 4 | LLM · Riskten kaçınan | `#b48c24` altın |
| 5 | MA kesişimi | `#c7608a` gül |
| 6 | Eşit ağırlık | `#3f8f3f` yeşil |
| 7 | PPO | `#8f7ae0` ametist |
| 8 | MCP misafir ajanı | `#d0605c` lal |
| – | Al-ve-tut BTC (ölçüt) | `#8f8a80` |

`dataviz` skill'inin doğrulayıcısıyla, yeni zeminin cam yüzeyi `#0f1322` üzerinde, koyu modda ve komşu çiftlerle kontrol edildi: tüm kontroller geçti. En kötü renk körlüğü ayrımı ΔE 8,7, normal görüş ayrımı ΔE 15,8; her renk L 0,48–0,67 bandında ve yüzeye karşı ≥ 3:1. Palet değişirse aynı doğrulayıcı yeniden çalıştırılır.

`lightweight-charts` CSS değişkeni okuyamadığı için grafik renkleri [`charts.tsx`](../frontend/src/components/charts/charts.tsx) içinde aynı tonların hex karşılıklarıyla tutulur. Token değişirse bu dosya da güncellenir.

## Tipografi

| Rol | Yazı tipi | Kullanım |
|---|---|---|
| Başlık | Geist Variable, yarı kalın, sıkı harf aralığı | Sayfa başlıkları ve giriş ekranı |
| Metin | Geist Variable (`font-sans`) | Arayüzün tamamı |
| Sayı | Geist Mono Variable (`num` yardımcı sınıfı) | Fiyat, getiri, tarih, seed, skor: hizalı rakamlar, sıfır çizgili, satır kırılmaz |
| Etiket | `eyebrow` yardımcı sınıfı | Tablo başlıkları, KPI etiketleri, bölüm adları: 11 px, büyük harf, aralıklı |

Yazı tipleri `@fontsource` paketleriyle uygulamaya gömülüdür; internet bağlantısı gerekmez.

## Bileşenler

Tamamı [`frontend/src/components`](../frontend/src/components) altındadır.

- **Yerleşim:** Masaüstünde (≥ 1024 px) sol yan menü. "Çalışma alanı" bölümü her zaman, "Deney" bölümü bir deney açıkken görünür. Daha dar ekranlarda üst çubuk ve yatay kaydırılan menü kullanılır.
- **Ajan kimliği:** `AgentAvatar`, ajanın renginde ince bir halka ve o rengin hafif tonunda bir zemin üzerinde baş harfleri gösterir. Renk tek kaynaktan gelir: `agentColor(id)`.
- **Arena önizlemesi:** `ArenaPreview` ([`components/arena-preview.tsx`](../frontend/src/components/arena-preview.tsx)) tanıtım ve giriş sayfalarında aynı bileşendir.
- **Metrik:** `Stat` tek metrik bileşenidir; başlık bölümlerinde `size="lg"` ile büyür. Lider tablosu, forum, işlem akışı, rapor ve grafik çizgileri aynı rengi kullanır; bir ajan her ekranda aynı renkle tanınır.
- **Varlık simgeleri:** `AssetOrb` coin renkleriyle küçük bir küredir; `Sparkline` son 30 günün kısa eğrisini çizer.
- **Spot ışığı:** Her `Card` fare imlecini takip eden yumuşak bir ışık ve parlayan bir kenar taşır (`.spotlight`).
- **Sayfa yerleşimleri:**
  - *Tanıtım (`/`):* Herkese açık. Büyük başlık, gerçek arayüz parçalarından kurulu arena önizlemesi, deney ölçeği, "Nasıl çalışır" adımları, C0–C3 koşul tablosu ve sonuç hedefleri.
  - *Deneyler:* Üstte öne çıkan deneyin büyük bölümü (en iyi ajan, Sharpe, MDD azalması, portföy yarışı grafiği); altında durum filtreli deney kartları.
  - *Canlı borsa:* Üstte seçilebilir varlık şeridi (fiyat, değişim, mini eğri). Solda grafik ve son işlemler, sağda sabit duran lider tablosu. Sıralama değiştikçe satırlar kayarak yer değiştirir. Dar ekranda sıra: grafik, lider tablosu, işlemler.
  - *Ajan:* Ajanın kendi renkleriyle boyanmış büyük bir başlık bölümü (avatar, sıra, dört metrik, portföy grafiği).
- **`PageTitle`:** üstte simgeli hap etiket, gradyanlı başlık, açıklama ve sağda eylemler.
- **`Card` / `CardHeader`:** tüm içerik blokları. Tabloyu kenara yaslamak için `p-0` kullanılır.
- **`StatGrid` + `Stat`:** tek cam kart içinde KPI satırı. Kutucuklar 1 px çizgiyle ayrılır.
- **`Badge`:** `tone` ile anlam taşır. Durum rozetleri noktalıdır; "Çalışıyor" rozeti nabız atar.
- **Segment kontrolü:** `segmentedClass` / `segmentClass` ile sekme, hız ve varlık seçicileri aynı görünür.
- **`EmptyState`, `ErrorState`, `Skeleton`:** boş, hatalı ve yükleniyor durumları için tek bileşen seti. Sayfalar kendi boş durum metnini yazar, görünümünü değiştirmez.

## Etkileşim ve erişilebilirlik

- Her etkileşimli öğede görünür odak halkası vardır (`:focus-visible`, vurgu rengi).
- Yalnızca simgeden oluşan düğmelerin `aria-label`'ı vardır. Dar ekranda gizlenen düğme metinleri `sr-only` ile ekran okuyucuda kalır.
- Segment kontrolleri (sekme, hız, varlık) ok tuşları, Home ve End ile gezilir (`rovingKeyDown`).
- Grafikler `role="figure"` ve açıklayıcı `aria-label` taşır. Kaydırılan listeler, klavyeyle odaklanabilen ve adı olan `region` içindedir.
- Renk çiftleri en az 4,5:1 kontrast sağlar; buna rozetlerin kendi renk tonlu zemini de dahildir. Her değişiklikten sonra axe taraması hatasız geçmelidir.
- Hareket kısa ve işlevseldir: sayfa girişinde 8 px yükselme, iskelet parıltısı, lider tablosunda sıra değişimi. `prefers-reduced-motion` açıksa tüm animasyonlar kapanır.
- Yerleşim 375 px genişlikte yatay kaydırma olmadan çalışır. Geniş tablolar kendi kartı içinde kayar.

## Performans

- Cam bulanıklığı (`backdrop-filter`) kartlarda kullanılır, ama arkasındaki katmanlar sabittir: hareketli arka plan ve tam ekran `filter: blur` yoktur. Kaydırma animasyonları yalnızca `opacity` ve `transform` değiştirir.
- Arka plan ışıkları sabittir; animasyonla hareket etmez.
- Grafik kütüphanesi (`lightweight-charts`, yaklaşık 58 kB gzip) ilk ekranın paketine girmez. Grafikli sayfalar ve Deneyler sayfasındaki grafik sonradan yüklenir (`React.lazy`).
- Sayı ve tarih biçimlendiricileri (`Intl`) modül yüklenirken bir kez oluşturulur; oynatma sırasında her karede yeniden yaratılmaz.
- Tanıtım sayfasındaki yörünge yalnızca `transform` ile döner ve `prefers-reduced-motion` altında durur.
- Ölçüm (geliştirme sunucusu, 1440 × 900, 20× oynatma, cam ve ışıklar açıkken): saniyede 79 kare, 95. yüzdelik kare süresi 28 ms, uzun görev yok.

---

[← Belge dizini](README.md) · [← Önceki: Veri hattı, simülatör ve baseline](08-data-pipeline-baseline.md)
