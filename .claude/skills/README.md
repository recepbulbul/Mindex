# Proje skill'leri

Claude Code bu klasördeki skill'leri depoyu açan herkes için otomatik yükler. Her biri, açıklamasındaki işe girişildiğinde devreye girer.
Hepsi topluluk depolarından alındı, her klasör kendi lisansını taşır ve eklenmeden önce içerikleri incelendi (ağ çağrısı veya gizli talimat yok).
Tek değişiklik: `stable-baselines3/SKILL.md` içindeki `allowed-tools` satırı silindi; böylece skill komut çalıştırma iznini kendiliğinden almaz.

## Model, veri ve değerlendirme

| Skill | Mindex'teki kullanımı | Kaynak (commit) |
|---|---|---|
| `stable-baselines3` | İP4 PPO ajanı: Gymnasium ortamı, VecNormalize, değerlendirme | [K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills/tree/a25cf9ec00e2/skills/stable-baselines3) |
| `backtesting-frameworks` | Simülatörde look-ahead / survivorship yanlılığı, işlem maliyeti | [wshobson/agents](https://github.com/wshobson/agents/tree/7e2fb559cf4b/plugins/quantitative-trading/skills/backtesting-frameworks) |
| `risk-metrics-calculation` | Sharpe, Sortino, MDD, VaR/CVaR hesapları | [wshobson/agents](https://github.com/wshobson/agents/tree/7e2fb559cf4b/plugins/quantitative-trading/skills/risk-metrics-calculation) |
| `llama-cpp` | 8 GB VRAM'de 4-bit Qwen: GGUF, sunucu, performans ayarı | [Orchestra-Research/AI-Research-SKILLs](https://github.com/Orchestra-Research/AI-Research-SKILLs/tree/773a52944ba4/12-inference-serving/llama-cpp) |
| `outlines` | LLM ajan kararlarını JSON şemasına / Pydantic modeline zorlamak | [Orchestra-Research/AI-Research-SKILLs](https://github.com/Orchestra-Research/AI-Research-SKILLs/tree/773a52944ba4/16-prompt-engineering/outlines) |

## Arayüz tasarımı

Arayüz kararları bu üç skill'le alınır; kurallar [docs/09-design-system.md](../../docs/09-design-system.md)'dedir.

| Skill | Mindex'teki kullanımı | Kaynak (commit) |
|---|---|---|
| `frontend-design` | Görsel yön, tipografi, şablon dışı kararlar | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design) (`main`, Kasım 2026) |
| `impeccable` | Tasarım kalitesi tabanı, eleştiri, cilalama | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) (`5af4319`) |
| `emil-design-eng` | Hareket, etkileşim ve bileşen cilası | [emilkowalski/skills](https://github.com/emilkowalski/skills) (`c8a7962`) |

`impeccable` `scripts/` klasörü olmadan eklendi: başlatıcısı bir ikili dosya indirip çalıştırıyor, bu depo onu taşımaz. Skill bu durumda kendi "launcher unavailable" yolunu izler ve proje bağlamını doğrudan okur.

Güncellemek için kaynak depodaki klasörü yeniden kopyalayın, farkı inceleyin ve tablodaki commit'i güncelleyin.
