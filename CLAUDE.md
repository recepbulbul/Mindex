# CLAUDE.md

Claude Code (ve diğer kod ajanları) bu depoda çalışırken bu dosyayı okur. Önce projeye özgü kurallar, ardından genel çalışma ilkeleri gelir.
Projeye ilk kez bakıyorsanız [README](README.md) ve [docs/README.md](docs/README.md) okuyun; iş akışı [CONTRIBUTING.md](CONTRIBUTING.md)'dedir.

## Proje

Mindex: kural tabanlı, PPO ve LLM (yerel 4-bit Qwen, llama.cpp) ticaret ajanlarının aynı kripto piyasasında yarıştığı simülasyon arenası.
Araştırma sorusu: kalıcı hafıza ve güven ağırlıklı forum (C0–C3) riske göre düzeltilmiş getiriyi artırır mı, yoksa sürü davranışına mı yol açar?
İş paketleri P1–P10 öneri formundaki takvimi izler (`Mindex_Oneri_Formu_*.pdf`); isterler F1–F9 / NF1–NF5 GitHub Issues'tadır.

## Değişmez kurallar

- **Test seti mühürlüdür.** 2026-04 → 2026-09 verisi yalnızca nihai değerlendirmede açılır. Geliştirme, ayar ve baseline yalnızca eğitim/doğrulama dönemini kullanır. Look-ahead'e yol açabilecek her değişikliği açıkça belirtin.
- **Prompt değişikliği = sürüm artışı.** LLM prompt'u değişirse `prompt_version` artırılır.
- **API sözleşmesi önce.** Yeni uç nokta önce `frontend/src/api/types.ts` + MSW handler'ında tanımlanır, backend aynı sözleşmeyi uygular.
- **Dil:** kod tanımlayıcıları İngilizce; arayüz metinleri, belgeler, commit açıklamaları Türkçe.
- **Gizli anahtar commitlenmez** (`.env.example` kullanın; gitleaks çalışır).
- Commit'ler Conventional Commits: `feat(backend): ... (#issue)`.

## Komutlar

`uv` bu makinede PATH'te olmayabilir; `python -m uv` kullanın.

| İş | Komut |
|---|---|
| Backend test / lint / tip | `cd backend && uv run pytest` · `uv run ruff check . && uv run ruff format --check .` · `uv run pyright` (strict, kapsam ≥ %70) |
| Frontend test / lint / tip | `cd frontend && npm test` · `npm run lint` · `npm run typecheck` |
| Veri ve baseline | `uv run mindex fetch-data` · `uv run mindex baseline` · `uv run mindex bench-llm` |
| Tüm kancalar | `cd backend && uv run pre-commit run --all-files` |

Bir değişikliği "bitti" saymadan önce ilgili alanın test, lint ve tip kontrolünü çalıştırın ve sonucu bildirin.

## Proje skill'leri

`.claude/skills/` altında: `stable-baselines3` (PPO), `backtesting-frameworks`, `risk-metrics-calculation`, `llama-cpp`, `outlines`; arayüz için `frontend-design`, `impeccable`, `emil-design-eng`. Kaynakları [.claude/skills/README.md](.claude/skills/README.md)'de.

`.claude/settings.json`: eklentiler, sık kullanılan zararsız komutlar için izin listesi (`.env` okuma ve force-push yasak) ve düzenlenen dosyayı otomatik biçimlendiren hook (`.claude/hooks/format_file.py`: Python → ruff, frontend → prettier).

`main` korumalıdır: her değişiklik dal + PR ile girer, CI yeşil olmadan birleşmez.

---

## Genel çalışma ilkeleri

Kaynak: [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) (LLM'lerin sık yaptığı kodlama hatalarını azaltmak için). Önemsiz işlerde sağduyu kullanın.

### 1. Kodlamadan önce düşün

- Varsayımları açıkça söyleyin; emin değilseniz sorun.
- Birden fazla yorum varsa sessizce birini seçmeyin, seçenekleri sunun.
- Daha basit bir yol varsa söyleyin; gerektiğinde itiraz edin.
- Bir şey belirsizse durun, neyin belirsiz olduğunu söyleyin.

### 2. Önce sadelik

- İsteneni çözen en az kod. Spekülatif özellik, tek kullanımlık soyutlama, istenmemiş "esneklik" yok.
- İmkânsız senaryolar için hata yakalama yazmayın.
- 200 satır 50 satır olabiliyorsa yeniden yazın. "Kıdemli bir mühendis bunu fazla karmaşık bulur mu?"

### 3. Cerrahi değişiklik

- Yalnızca gerekene dokunun; komşu kodu, yorumları, biçimi "iyileştirmeyin".
- Bozuk olmayanı yeniden düzenlemeyin; mevcut stile uyun.
- İlgisiz ölü kod görürseniz söyleyin, silmeyin. Sizin değişikliğinizin kullanılmaz bıraktığı import/değişkenleri temizleyin.
- Değişen her satır doğrudan isteğe bağlanabilmeli.

### 4. Hedefe dayalı yürütme

- İşi doğrulanabilir hedefe çevirin: "doğrulama ekle" → "geçersiz girdiler için test yaz, geçir"; "hatayı düzelt" → "hatayı yeniden üreten test yaz, geçir"; "yeniden düzenle" → "testler önce ve sonra geçsin".
- Çok adımlı işlerde kısa bir plan yazın: `1. [adım] → doğrula: [kontrol]`.
- Başarı ölçütü net olana ve doğrulanana kadar döngüde kalın.
