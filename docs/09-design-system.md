# 9. Arayüz Tasarım Sistemi

Mindex arayüzünün görsel dili bu dokümanda sabitlenmiştir. Yeni ekranlar ve bileşenler buradaki kurallara uyar; kuralı değiştirmek gerekiyorsa önce bu doküman güncellenir.

Kurallar üç tasarım skill'ine dayanır. Skill'ler [`.claude/skills/`](../.claude/skills/) altında projeye eklenmiştir: Anthropic `frontend-design`, Paul Bakaus `impeccable` ve Emil Kowalski `emil-design-eng`.

## Yön: "gece camı"

Ağır ve lüks bir koyu arayüz: lacivert-siyah zemin, üzerinde derin ve soluk indigo ile çelik mavisi ışık kütleleri, ışığı kıran buzlu cam kartlar. Ana eylemler beyaz düğmelerdir; tek vurgu gümüşi buz tonudur.

- **Zemin ışıktır, desen değil.** Lacivert ışık kütlelerinin üstüne yukarıdan gelen soluk gümüş bir parlama düşer (`body::before`, `body::after`); cilalı metal üzerindeki ışık gibi. Çizgi, ızgara, örgü, doku ya da süs deseni kullanılmaz.
- **Buzlu cam kartlar (`glass`).** Zemine %4 beyaz ekler, arkasını 24 px bulanıklaştırır; üstte 1 px ışık çizgisi, altta derin siyah gölge taşır. Fare üzerine gelince imleci izleyen ince bir ışık belirir (`.spotlight`).
- **Her şey kart değildir.** Cam kart yalnızca ekranın ana nesnesi içindir (öne çıkan grafik, canlı grafik, lider tablosu). Liste ve özet alanları kartsızdır: deneyler geniş satırlardır, varlık fiyatları çizgilerle ayrılmış açık bir şerittir, ajan başlığı ve öne çıkan sonuç metni çerçevesizdir. Büyük başlık ve geniş boşluk, kutudan daha çok hiyerarşi taşır.
- **Gümüş malzeme.** Birincil düğme fırçalanmış gümüştür (açık gümüşten koyu gümüşe dikey geçiş, koyu metin). Fiyatlar, metrik rakamları ve sayfa başlıkları `text-silver` ile metal gibi parlar; kazanç/kayıp rengi taşıyan değerler bundan muaftır.
- **Grafik sayfadadır, kutuda değil.** Ana grafikler (canlı mum grafiği, portföy yarışı, rapor ve güven grafikleri) kart içinde durmaz; `stage` arkalarına kenarsız, soluk gümüş-lacivert bir ışık koyar. Çizgi serilerinin son noktası yavaşça nabız atar.
- **Yer yer siyah.** `band` siyah bir şerittir: oynatma kontrolleri ve deney listesi gibi denetim/liste alanlarını lacivert ışıklı zeminden ayırır. Zeminin alt kısmı siyaha koyulaşır, üstünden çapraz soluk bir gümüş parıltı geçer.
- **Doygun mavi ve neon yok.** Vurgu gümüşi buz (`#b9c6e4`); gradyan (`bg-brand`) yalnızca küçük işaretlerde (logo, lider çubuğu, ilerleme) ve başlıktaki vurgu kelimede kullanılır ve gümüşten çelik mavisine soluk bir geçiştir.
- **Skill'ler.** Tasarım kararları `frontend-design`, `impeccable` ve `emil-design-eng` skill'leriyle ([`.claude/skills/`](../.claude/skills/)) alınır. Skill'ler cam ve gradyanı varsayılan olarak "kaçınılacak" sayar; ancak "brief her zaman kazanır" kuralı gereği, kullanıcının açıkça istediği cam kartlar ve lacivert-siyah zemin korunmuştur.

## Tokenlar

Tek token seti [`frontend/src/index.css`](../frontend/src/index.css) içinde `:root` altındadır; yazdırma için açık renk değerleri aynı dosyadadır.

| Token | Değer | Görev |
|---|---|---|
| `background` | `#040711` | Lacivert-siyah zemin |
| `card` · `elevated` · `muted` | %4 · %7 · %8 beyaz | Cam katmanları |
| `foreground` · `muted-foreground` | `#f1f4fa` · `#98a2b8` | Metin |
| `border` · `border-strong` | %9 · %16 beyaz | Ayraçlar |
| `primary` | `#b9c6e4` | Gümüşi buz: simge, odak, seçili öğe |
| `brand-from` → `brand-to` | `#dfe6f5` → `#8396bd` | Küçük işaretlerde soluk gümüş geçişi |
| `up` · `down` | `#5fdcb0` · `#ff7d93` | Kazanç ve kayıp |
| `warn` · `info` | `#f4c35c` · `#a9b9dc` | Uyarı ve bilgi |

Kazanç/kayıp çifti `dataviz` doğrulayıcısından geçti: renk körlüğü ayrımı ΔE 7,7 (ikincil kodlamayla birlikte kullanılır). Yine de her değer `+`/`−` işareti, ok ya da "AL"/"SAT" etiketiyle birlikte gösterilir.

### Ajan kimlik renkleri

Ajan ve seri renkleri [`lib/identity.ts`](../frontend/src/lib/identity.ts) içindedir. Renkler sabit sırayla atanır; rengi sıra değil ajan belirler. BTC al ve tut ölçüt çizgisi gridir.

| Sıra | Ajan | Renk |
|---|---|---|
| 1 | LLM · Momentum | `#4f86d9` |
| 2 | LLM · Ortalamaya dönüş | `#c8743f` |
| 3 | LLM · Duyarlılık | `#2fa07c` |
| 4 | LLM · Riskten kaçınan | `#b48c24` |
| 5 | MA kesişimi | `#c7608a` |
| 6 | Eşit ağırlık | `#3f8f3f` |
| 7 | PPO | `#8f7ae0` |
| 8 | MCP misafir ajanı | `#d0605c` |
| – | Al ve tut BTC (ölçüt) | `#8f8a80` |

Bu palet `#0b1812` zümrüt panel yüzeyinde, koyu modda ve komşu çiftlerle doğrulandı; tüm kontroller geçti. En kötü renk körlüğü ayrımı ΔE 8,7, normal görüş ayrımı ΔE 15,8; her renk yüzeye karşı ≥ 3:1. Palet değişirse doğrulayıcı yeniden çalıştırılır.

`lightweight-charts` CSS değişkeni okuyamadığı için grafik renkleri [`charts.tsx`](../frontend/src/components/charts/charts.tsx) içinde aynı tonların hex karşılıklarıyla tutulur.

## Tipografi

Tek aile kullanılır: **Manrope** (variable, `@fontsource-variable/manrope`; uygulamaya gömülüdür). Açık iç boşlukları ve sakin geometrisiyle lüks ama küçük boyutta da okunur; Türkçe karakterleri tam destekler. Grafik eksenleri de aynı aileyi kullanır.

- Rakamlar `num` yardımcı sınıfıyla aynı ailenin tablo rakamlarıyla (`tabular-nums`) dizilir; monospace yazı tipi yoktur.
- Simgeler lucide'dir ve 1,6 px kalemle çizilir (varsayılan 2 px'ten ince), yazıyla aynı ağırlıkta durur. Başlıktaki eylem düğmeleri `size="sm"` olur ki durum rozetiyle aynı hizada dursun.
- Uygulama ekranlarında sabit rem ölçeği kullanılır: sayfa başlığı 28–32 px (düz beyaz, gradyansız), panel başlığı 14 px, gövde 14–16 px.
- Sayfa başlığının üstündeki bağlam satırı (`eyebrow`) hap/rozet değil, 12 px soluk metindir.
- Etiketler `caption` sınıfıyla cümle düzeninde ve 12 px'tir; büyük harf kullanılmaz.

## Bileşenler

Tamamı [`frontend/src/components`](../frontend/src/components) altındadır.

- **`Card`:** Düz panel; 1 px çizgi, 6 px köşe, gölge yok.
- **`PageTitle`:** Başlık, açıklama, eylemler ve isteğe bağlı geri bağlantısı (`back`); altında ince bir çizgi vardır.
- **`Stat` ve `StatGrid`:** Çizgilerle ayrılmış metrik satırı.
- **`Table`:** Uygulamanın birincil düzenidir. Deney listesi kart değil tablodur.
- **`AgentAvatar`:** Ajanın renginde ince bir halka ve hafif tonlu zemin. Renk tek kaynaktan gelir: `agentColor(id)`.
- **Segment kontrolü:** `segmentedClass` ve `segmentClass`. Ok tuşları, Home ve End ile gezilir (`rovingKeyDown`).
- **Yerleşim:** Masaüstünde sabit sol yan menü (Tüm deneyler, Yeni deney, başlamış deneylerin kısayolları; en altta hesap satırı `/account` sayfasına gider), dar ekranda üst çubuk. Yan menü deney açılınca değişmez. Bir deneyin bütün ekranları ortak bir başlık paylaşır (`ExperimentLayout`): konum satırı (Deneyler › deney adı), başlık, özet satırı, durum ve sekmeler (Canlı borsa · Forum ve hafıza · Rapor). Ekranın kendi eylemleri (CSV, PDF) sekme satırının sağına küçük metin düğmeleri olarak `ExperimentActions` ile taşınır. Çıkış yalnızca Hesap sayfasındadır. Giriş ekranı tek ekrana sığar; kaydırma yoktur.
- **Lider tablosu** kart değil, grafiğin sağında ince bir çizgiyle ayrılmış açık bir sütundur; metrik şeridi (`StatGrid`) üst ve alt çizgili açık bir şerittir.
- **Etiketler** (`eyebrow`) aralıklı büyük harf değil, 12 px cümle düzeninde soluk metindir.

## Hareket (emil-design-eng)

- Arayüz geçişleri 150 ms'dir ve güçlü bir ease-out eğrisi kullanır (`--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`). `ease-in` ve `transition: all` kullanılmaz.
- Düğmeler basıldığında `scale(0.97)` ile küçülür; böylece arayüzün tıklamayı aldığı hissedilir.
- Hover efektleri yalnızca fareli cihazlarda çalışır (Tailwind v4 `hover:` varyantı).
- **Tek düzenlenmiş an:** Tanıtım sayfasında kaydırdıkça piyasa çizgileri soldan sağa açılır (`clip-path`) ve gün sayacı 30'dan 183'e ilerler. Bu yalnızca CSS ile yapılır (`animation-timeline: view()`). Hareket kısıtlaması açıksa, ekran 1024 px'ten darsa ya da tarayıcı desteklemiyorsa tamamlanmış grafik görünür. Başka giriş animasyonu yoktur.
- Grafikler çerçevesizdir: dikey ızgara yok, yatay ızgara %3,5 beyaz, eksen yazısı sans-serif, imleç mıknatıslı ve yalnızca kesikli yatay çizgi. TradingView logosu grafikte değil, alt bilgide atıf bağlantısıdır.
- Canlı borsa ekranında grafik ilk ekranın ana nesnesidir: varlık seçimi grafiğin başlığındaki küçük sekmelerdir, grafik yüksekliği ekrana göre ayarlanır (`clamp(360px, 100dvh − 340px, 640px)`); 1366 × 768'de grafik tamamen görünür.

## Erişilebilirlik ve tarayıcı yüzeyleri

- Her etkileşimli öğede görünür odak halkası vardır (`:focus-visible`).
- Metin seçimi, yazı imleci, kaydırma çubuğu ve alt çizgi aralığı temadan renk alır. Impeccable bunu "kurulmuş" sayfanın en ucuz işareti sayar.
- Yalnızca simgeden oluşan düğmelerin `aria-label`'ı vardır. Grafikler `role="figure"` ve açıklayıcı etiket taşır.
- Yerleşim 375 px genişlikte yatay kaydırma olmadan çalışır.

## Performans

- Bulanıklaştırma yalnızca yapışkan üst çubuklarda kullanılır. Arka plan efekti ve hareketli katman yoktur.
- Grafik kütüphanesi ilk ekranın paketine girmez (`React.lazy`).
- Sayı ve tarih biçimlendiricileri bir kez oluşturulur.
- Ölçüm (geliştirme sunucusu, 1440 × 900, 20× oynatma): saniyede 113 kare, 95. yüzdelik kare süresi 14 ms, uzun görev yok.
