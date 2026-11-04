# Katkı Rehberi

## İş akışı

1. Her iş bir GitHub Issue'ya bağlıdır (ister kodu F1–F9 / NF1–NF5 veya iş paketi P1–P10).
2. `main`'den dal açın: `feat/f5-candle-markers`, `fix/nf2-retry`, `docs/er-diagram`.
3. Commit mesajları [Conventional Commits](https://www.conventionalcommits.org/) biçimindedir:
   `feat(frontend): canlı ekranda işlem işaretleri (#5)`.
4. PR açın; CI (backend, frontend, security) yeşil olmadan birleştirilmez. PR şablonundaki kontrol listesini doldurun.
5. `main` dalı korumalıdır (yöneticiler dahil): doğrudan push ve force-push kapalıdır; Backend, Frontend ve Security CI işleri geçmeden ve PR yorumları çözülmeden birleştirilmez. Onay zorunlu değildir; birleşen dallar otomatik silinir.

## Yerel kontroller

```bash
cd backend && uv run pre-commit install   # bir kez
uv run pre-commit run --all-files         # tüm kancalar
```

| Alan | Komut |
|---|---|
| Backend lint/biçim | `uv run ruff check . && uv run ruff format --check .` |
| Backend tip | `uv run pyright` (strict) |
| Backend test | `uv run pytest` (kapsam ≥ %70 zorunlu) |
| Frontend lint/biçim | `npm run lint` (oxlint + Prettier) |
| Frontend tip | `npm run typecheck` |
| Frontend test | `npm test` (Vitest + Testing Library + MSW) |

## Claude Code kurulumu (bir kez)

`.claude/settings.json` eklentileri yalnızca **etkin** olarak işaretler; eklentiler makine başına kurulur. Depoyu ilk kez açtığınızda proje klasöründe çalıştırın:

```bash
claude plugin install superpowers@claude-plugins-official --scope project
claude plugin install context7@claude-plugins-official --scope project
claude plugin install pyright-lsp@claude-plugins-official --scope project
claude plugin install typescript-lsp@claude-plugins-official --scope project
```

Ardından bir `claude` oturumunda `/mcp` ile context7'yi yetkilendirin ve yeni oturum açın. Proje skill'leri (`.claude/skills/`) ve CLAUDE.md ek kurulum gerektirmez.

## Kurallar

- **Gizli anahtar commitlenmez.** `.env.example`'ı kopyalayın; gitleaks hem pre-commit'te hem CI'da çalışır.
- **Test seti mühürlüdür.** 2026-04 → 2026-09 verisi yalnızca nihai değerlendirmede açılır (look-ahead protokolü).
- **Prompt değişikliği = sürüm artışı.** `prompt_version` her deney kaydına yazılır.
- **API sözleşmesi önce.** Yeni uç noktalar önce `frontend/src/api/types.ts` + MSW handler'ında tanımlanır; backend aynı sözleşmeyi uygular.
- Kod tanımlayıcıları İngilizce, kullanıcı arayüzü ve dokümanlar Türkçedir.
