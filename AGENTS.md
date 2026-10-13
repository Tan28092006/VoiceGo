# VoiceGo (repo router)

Đặt xe bằng giọng nói cho người khiếm thị. App nằm trong `voicego/` (FastAPI `backend/` + React/Vite `frontend/`, 1 image Docker).
Production: https://voicego-9k11.onrender.com (Render free). **Push lên `main` = auto-deploy** (`render.yaml`).

- **Trước khi chạy, test, deploy hoặc sửa vòng giọng nói: đọc [`voicego/AGENTS.md`](voicego/AGENTS.md)** (bản đồ, lệnh đã kiểm, env, deploy gotchas, trạng thái).
- Kiểm nhanh: `cd voicego/frontend && npm test` (unit) · `npm run eval` (eval offline, không gọi API) · `cd voicego/backend && py -m pytest -q`
- GitNexus index theo commit; `analyze` repo này cần `NODE_OPTIONS=--max-old-space-size=6144` (thiếu là hết heap). MCP không kết nối được thì dùng CLI `node .gitnexus/run.cjs impact|detect-changes`.
- Tự làm được: test, server local, build vào thư mục tạm. **Hỏi user trước:** commit/push (push `main` = deploy production), gọi API trả phí/quota (DeepSeek, Gemini, Groq, `smoke_test.sh`, `test:live`), đụng `.env`/secret. Chi tiết: `voicego/AGENTS.md` mục 0.
- Bất biến: `/api/health` không được gọi Mongo/mạng; `index.html` luôn `Cache-Control: no-cache`; không in/commit giá trị trong `backend/.env`.
- Một số docs trong `voicego/` là lịch sử (FPT.AI, Vercel); `voicego/AGENTS.md` mục 9 ghi cái nào còn đúng.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **GRAB-HACKATHON-_-TEAM-S** (1929 symbols, 3993 relationships, 162 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/GRAB-HACKATHON-_-TEAM-S/context` | Codebase overview, check index freshness |
| `gitnexus://repo/GRAB-HACKATHON-_-TEAM-S/clusters` | All functional areas |
| `gitnexus://repo/GRAB-HACKATHON-_-TEAM-S/processes` | All execution flows |
| `gitnexus://repo/GRAB-HACKATHON-_-TEAM-S/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
