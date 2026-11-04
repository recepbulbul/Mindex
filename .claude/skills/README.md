# Design skills

Third-party skills vendored for this project's UI work. Each folder keeps its upstream license.

| Skill | Source | Commit |
|---|---|---|
| `frontend-design` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design) | `main` (Nov 2026) |
| `emil-design-eng` | [emilkowalski/skills](https://github.com/emilkowalski/skills) | `c8a7962` |
| `impeccable` | [pbakaus/impeccable](https://github.com/pbakaus/impeccable) | `5af4319` |

`impeccable` is vendored without its `scripts/` folder: the launcher downloads and runs a binary, which this repo does not ship. The skill then follows its own "launcher unavailable" path and reads project context directly.
