# mindex (backend)

Python 3.12 paketi. Bağımlılıklar [uv](https://docs.astral.sh/uv/) ile kilitlenir (`uv.lock`).

```bash
uv sync                 # .venv oluşturur, kilitli bağımlılıkları kurar
uv run pytest           # testler + kapsam (>= %70)
uv run ruff check .     # lint
uv run ruff format .    # biçimlendirme
uv run pyright          # strict tip kontrolü

uv run mindex fetch-data            # Binance + Fear & Greed → ../data/snapshots
uv run mindex baseline [--llm]      # doğrulama döneminde baseline → ../reports
uv run mindex bench-llm --calls 30  # llama-server karar çağrısı gecikmesi
uv run mindex bench-llm --calls 30 --prompt decision-v2 --lessons 3  # C1 bağlamı: hafıza dersleriyle
uv run mindex train-hmm             # rejim HMM'i, yalnızca eğitim dönemi → ../models/regime-hmm.json
uv sync --group eda                 # EDA notebook'u için jupyter, matplotlib, duckdb
uv sync --group rl                  # PPO eğitimi: stable-baselines3 + CPU torch (yalnızca eğitim makinesi / CI)
uv run mindex train-ppo --seed 0    # train'de eğit, validation'da seç → ../models/ppo/seed-0/

docker compose up -d db             # (kök dizinde) PostgreSQL 17 + pgvector, 127.0.0.1:5432
uv run alembic upgrade head         # şemayı kur / güncelle
uv run mindex serve --reload        # API + deney koşucusu: http://127.0.0.1:8000/api/docs
```

### Veritabanı ve testler

- Şema Alembic migration'larıyla yönetilir (`alembic/versions/`); referans DDL [`docs/db/schema.sql`](../docs/db/schema.sql). Model değişince: `uv run alembic revision --autogenerate -m "..."`, ardından üretilen dosyayı gözden geçirin.
- `@pytest.mark.db` testleri ayrı bir `mindex_test` veritabanında koşar (otomatik oluşturulur, her test kendi işleminde geri alınır). Veritabanı yoksa bu testler **atlanır**; CI'da `MINDEX_REQUIRE_DB=1` ile atlanmaz, başarısız olur.
- `tests/test_ppo_sb3.py` stable-baselines3 ister; `rl` grubu kurulu değilse (yerelde) **atlanır**, CI `--group rl` ile koşar.
- `@pytest.mark.model` testleri gerçek model ister (llama-server, embedding, eğitilmiş PPO); varsayılan koşuda yoktur, GPU'lu makinede `uv run pytest -m model --no-cov` ile çalıştırılır (kapsam eşiği yalnızca tam koşuda anlamlı).

### Kalıcı hafıza

`MemoryStore.search` ajanın kendi derslerini pgvector kosinüs benzerliği ve `lesson_tsv` tam metin eşleşmesiyle (`websearch_to_tsquery('simple', ...)`, kelimeler `or` ile) puanlar. İki sıralama RRF ile birleşir ve kosinüs benzerliğiyle çarpılır (ilgisiz ders bonuslarla tepeye çıkamasın diye); önem (`importance`) ve rejim eşleşmesi çarpan olarak eklenir. Rejim bonusu C1′ (`C1_NO_REGIME`) koşulunda `use_regime=False` ile kapanır. **Look-ahead:** yalnızca `day < as_of_day` olan dersler döner, yani aynı günün dersi dönmez. Ayrıntı ve formül: [docs/04-ai-pipeline.md](../docs/04-ai-pipeline.md#kalıcı-hafıza). Gerçek embedding sunucusu `MINDEX_EMBEDDING_BASE_URL` (llama-server `--embedding`); sözleşme testi `uv run pytest -m model --no-cov`.

## Modüller

| Modül | İçerik |
|---|---|
| `mindex.config` | `.env` / ortam değişkenlerinden tipli ayarlar (`MINDEX_` öneki) |
| `mindex.logging_config` | structlog JSON log yapılandırması (NF4) |
| `mindex.domain.decision` | LLM ajan kararı JSON sözleşmesi ve doğrulaması (NF2) |
| `mindex.domain.trust` | Beta itibar skoru `w = (a+1)/(a+b+2)` |
| `mindex.domain.metrics` | Sharpe, maksimum düşüş, sürü korelasyonu |
| `mindex.data` | ccxt + Fear & Greed kaynakları, Parquet anlık görüntüleri, zamansal ayrım ve mühürlü test seti (P3) |
| `mindex.sim` | `t` kapanışında karar, `t+1` açılışında komisyon + kaymayla yürütme; checkpoint (P3) |
| `mindex.agents` | `BaseAgent`, kural tabanlı ajanlar, llama.cpp ile ilk LLM ajanı (P3), eğitilmiş modelden `PPOAgent` (P4) |
| `mindex.rl` | Günlük Gymnasium ortamı (simülatörle aynı yürütme ve maliyet, look-ahead yok), PPO eğitimi, SHA-256 manifest (P4) |
| `mindex.regime` | Gauss HMM rejim modeli (boğa/ayı/yatay); filtrelenmiş olasılık, look-ahead yok (P4) |
| `mindex.evaluation` | Koşu özeti, nicel hedef karşılaştırması, LLM gecikmesi ve hesap bütçesi (P3) |
| `mindex.db` | SQLAlchemy 2 modelleri ve oturum fabrikası (P4) |
| `mindex.memory` | Kalıcı hafıza: `Embedder` (llama-server `/v1/embeddings`, testte `HashEmbedder`), pgvector + tam metin hibrit arama; `recall`: bir ajanın kararı öncesi kendi derslerini getirir, C1/C1′ (P5) |
| `mindex.postmortem` | Kapanan pozisyon için karşı-olgusal PnL tablosu (gerçek / girmemek / yarım / zarar-kes) ve sayısal tutarlılık denetimli ders yazımı (`postmortem-v1`, P5) |
| `mindex.api` | FastAPI uygulaması, `{detail, fields}` hata zarfı, `/api/health` (P4); `/agents`, `/experiments` CRUD + YAML, sonuç uçları (P5) |
| `mindex.services.runner` | Süreç içi deney koşucusu: `JobQueue` + `InProcessQueue`, gün sonu checkpoint, yeniden başlatmada sürdürme (NF2) |
| `mindex.cli` | `mindex fetch-data | baseline | bench-llm | train-hmm | train-ppo | create-user | serve` |

Ayrıntılar: [docs/08-data-pipeline-baseline.md](../docs/08-data-pipeline-baseline.md). Sonraki haftalarda: `mindex.mcp`.

## Deney koşucusu

`POST /api/experiments/:id/start` deneyi `queued` yapar; `mindex serve` içindeki tek iş parçacıklı kuyruk onu `Simulator.step` ile gün gün koşar. Her günün kararları, işlemleri, portföy anlık görüntüsü ve `experiments.checkpoint` tek işlemde yazılır; süreç yeniden başlarsa yarım kalan deneyler checkpoint'ten sürer ve sonuç kesintisiz koşuyla bit bit aynıdır (`tests/test_runner.py`). Hata olursa durum `failed` olur.

- Fiyatlar `MINDEX_SNAPSHOT_DIR` (varsayılan `data/snapshots`) Parquet anlık görüntüsünden okunur; dokunulan her bölme `ensure_readable`'dan geçer, test bölmesi okunmaz.
- LLM ajanları `MINDEX_LLM_BASE_URL` llama-server'ına deneyin `model_version` ve `seed` değeriyle bağlanır; testlerde sahte `ChatClient`.
- Henüz koşturulmayanlar (başlatmada 422): canlı mod, MCP misafir ajanı, eğitilmiş model yoksa PPO (`MINDEX_PPO_MODEL_DIR`), C0 dışı koşullarda LLM ajanları.
- Kuyruk süreç içidir: API'yi **tek süreçle** çalıştırın (birden fazla worker aynı deneyi sürdürmeye çalışır); çok süreçli kuyruk İP6–7'de Redis Streams ile gelir.
- Rejim: `MINDEX_REGIME_MODEL_PATH` (`mindex train-hmm` çıktısı) yoksa her gün `sideways` yer tutucusudur.
