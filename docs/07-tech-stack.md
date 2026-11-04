# 7. Teknoloji Yığını

> **Bu belge ne anlatır?** Mindex'in her katmanında hangi kütüphane ve aracın kullanıldığını, neden seçildiğini ve hangi iş paketinde devreye girdiğini listeler.
>
> **Neden önemli?** Seçimler bütçe ve donanım sınırlarına göre yapılmıştır (bulut yok, 8 GB ekran kartı belleği). Bu tablo, bir aracın neden tercih edildiğini ve projenin şu an hangi noktada olduğunu tek bakışta gösterir.
>
> **İlgili isterler:** [F9 #15](https://github.com/recepbulbul/Yunus_Hoca_Proje/issues/15) · [NF1 #16](https://github.com/recepbulbul/Yunus_Hoca_Proje/issues/16) · [NF4 #19](https://github.com/recepbulbul/Yunus_Hoca_Proje/issues/19) · [NF5 #20](https://github.com/recepbulbul/Yunus_Hoca_Proje/issues/20)
>
> **İş paketi:** İP2 (tablo); her satır kendi iş paketinde · **Önceki belge:** [Veri sözlüğü](06-data-dictionary.md) · **Sonraki belge:** [Veri hattı, simülatör ve baseline](08-data-pipeline-baseline.md) · Terimler için: [belge dizini ve sözlük](README.md#terimler-sözlüğü)

**"Durum" sütununu okuma:** **P3 ✔** o katmanın İP3'te tamamlandığını (ve varsa ilk ölçüm sonucunu), yalnızca **P6** gibi bir kod ise o iş paketinde devreye gireceğini gösterir (P = İP; [iş paketleri](README.md#terimler-sözlüğü)). Sık geçen kısaltmalar: LLM büyük dil modeli, VRAM ekran kartı belleği, p95 çağrıların %95'inin altında kaldığı süre, PPO pekiştirmeli öğrenme algoritması, MCP dış ajanların bağlandığı protokol, A2A (*Agent-to-Agent*) ajanlar arası iletişim protokolü, MSW sahte API kütüphanesi, CI her commit'te otomatik test süreci.

| Katman | Seçim | Gerekçe | Durum |
|---|---|---|---|
| LLM çıkarımı | Qwen3.5-9B (Q4_K_M, ≈5,6 GB) · llama.cpp `llama-server` (OpenAI uyumlu API) | 8 GB VRAM sınıfındaki en yüksek başarımlı açık modellerden (Apache-2.0); JSON şemasıyla kısıtlı üretim | **P3 ✔** p95 5,3 sn, bütçe ≈ 27 sa |
| Ajan çerçevesi | PydanticAI | Tip güvenli yapılandırılmış çıktı, model bağımsızlık, OpenTelemetry desteği | P6 |
| Hafıza | Qwen3-Embedding-0.6B · PostgreSQL + pgvector (HNSW) + tam metin arama | Hibrit arama; ilişkisel ve vektör veri tek veritabanında | P5 |
| Veri | ccxt · Polars · DuckDB · Parquet | Borsadan bağımsız API; hızlı kolonsal analiz, tekrarlanabilir veri anlık görüntüleri | **P3 ✔** (DuckDB EDA'da) |
| RL ve rejim | Gymnasium · Stable-Baselines3 (PPO) · hmmlearn | Standart ve iyi belgelenmiş kütüphaneler | P4 |
| Backend | FastAPI · Pydantic v2 · SQLAlchemy 2 + Alembic · Redis Streams işçisi | Asenkron API, otomatik OpenAPI; uzun deneyler API'den ayrı işçide | P4 |
| Protokol | MCP sunucusu (resmî Python SDK) · A2A (esneme) | Dış ajanların standart araç arayüzüyle katılımı | P7 |
| Frontend | React 19 · TypeScript · Vite · TanStack Query · Tailwind + shadcn/ui · Lightweight Charts v5 · MSW · Geist (fontsource) | Prototip aynı kodla ürüne dönüşür (MSW ile sahte API); hafif finans grafikleri; görsel dil [tasarım sisteminde](09-design-system.md) sabit | **P2 ✔** |
| Gözlemlenebilirlik | OpenTelemetry · Langfuse (self-host) · structlog | Her LLM çağrısının izi, prompt sürümleme, gecikme takibi | structlog **P1 ✔** |
| Test ve kalite | pytest · Vitest + Testing Library · Playwright · k6 · Ruff · pyright · oxlint · Prettier · pre-commit | Birim/entegrasyon, uçtan uca ve WebSocket yük testi; statik analiz | **P1 ✔** (k6/Playwright P9) |
| Dağıtım ve CI | uv · Docker Compose · Caddy · Tailscale · GitHub Actions · Trivy · gitleaks · Dependabot | Kilitli bağımlılıklar, otomatik HTTPS, laptop GPU'suna güvenli tünel, imaj ve sır taraması | CI **P1 ✔** |

## Sürüm politikası

- Python bağımlılıkları `backend/uv.lock`, Node bağımlılıkları `frontend/package-lock.json` ile kilitlidir; CI `uv sync --locked` ve `npm ci` kullanır.
- Dependabot haftalık gruplu güncelleme PR'ı açar; CI geçmeden birleştirilmez.
- LLM model dosyası SHA-256 ile, prompt'lar `prompt_version` ile sabitlenir ve her deney kaydına yazılır.

---

[← Belge dizini](README.md) · [← Önceki: Veri sözlüğü](06-data-dictionary.md) · [Sonraki: Veri hattı, simülatör ve baseline →](08-data-pipeline-baseline.md)
