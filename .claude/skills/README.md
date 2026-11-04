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

## Frontend kod kalitesi

Tasarım skill'leri neyin çizileceğine, bunlar React kodunun ve arayüz davranışının doğruluğuna bakar.

| Skill | Mindex'teki kullanımı | Kaynak (commit) |
|---|---|---|
| `react-best-practices` | Gereksiz render, paket boyutu, veri çekme ve React 19 kalıpları (Next.js'e özgü `server-*` kuralları bu projede geçerli değil) | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills/tree/1a2c79d4e6c4/skills/react-best-practices) |
| `composition-patterns` | Bileşen API'si: boolean prop yığını yerine bileşik bileşen ve açık varyant | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills/tree/1a2c79d4e6c4/skills/composition-patterns) |
| `web-design-guidelines` | Erişilebilirlik, odak, form, hareket, metin ve dokunma kuralları denetimi | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills/tree/1a2c79d4e6c4/skills/web-design-guidelines) · kurallar [vercel-labs/web-interface-guidelines](https://github.com/vercel-labs/web-interface-guidelines/blob/434b7f91364665f2f733b310ec54809bf8f37937/command.md) |

`agent-skills` deposunda LICENSE dosyası yok; skill'ler ön bilgilerinde MIT olarak işaretli. `web-design-guidelines` asıl hâlinde kuralları her çalışmada sabitlenmemiş bir URL'den çekiyordu; kurallar sabit commit'ten `guidelines.md` olarak kopyalandı ve `SKILL.md` bu yerel dosyayı okuyacak şekilde değiştirildi.

`impeccable` `scripts/` klasörü olmadan eklendi: başlatıcısı bir ikili dosya indirip çalıştırıyor, bu depo onu taşımaz. Skill bu durumda kendi "launcher unavailable" yolunu izler ve proje bağlamını doğrudan okur.

Güncellemek için kaynak depodaki klasörü yeniden kopyalayın, farkı inceleyin ve tablodaki commit'i güncelleyin.
