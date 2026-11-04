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
uv sync --group eda                 # EDA notebook'u için jupyter, matplotlib, duckdb
```

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
| `mindex.agents` | `BaseAgent`, kural tabanlı ajanlar, llama.cpp ile ilk LLM ajanı (P3) |
| `mindex.evaluation` | Koşu özeti, nicel hedef karşılaştırması, LLM gecikmesi ve hesap bütçesi (P3) |
| `mindex.cli` | `mindex fetch-data | baseline | bench-llm` |

Ayrıntılar: [docs/08-data-pipeline-baseline.md](../docs/08-data-pipeline-baseline.md). Sonraki haftalarda: `mindex.api` (FastAPI), `mindex.mcp`.
