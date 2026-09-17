# Phase 10 — Pre-Deployment Audit Report

**Date**: September 17, 2026  
**Audited Target**: Autonomous Outbound Lead Pipeline  
**Production Domain**: `https://work.raghavpatak.me`  
**Operator Account**: `raghavp`

---

## 1. Executive Summary

Prior to modifying code or configurations for Phase 10, an exhaustive audit was performed across `server/`, `pipeline/`, `tests/`, `main.py`, `.env`, `.env.example`, `.gitignore`, and Git commit history.

The audit confirmed:
- The system is functionally complete through Phases 1–9, with **207/207 passing tests**.
- The CLI (`main.py --help`) is fully operational.
- The authoritative delivery safety gates in `server/services/delivery.py` and `pipeline/delivery.py` are active and enforce strict pre-send checks (tenant ownership, run status, review approval, draft integrity, RFC syntax, anti-fabrication blacklist, email verification, person confidence threshold, 3-source deduplication union, rolling volume caps, and server-side live gate).
- Zero secrets or API keys are committed in Git history or tracked files.
- Live sending is safely disabled by default (`DELIVERY_MODE=stub`/`stage`, `DRY_RUN=true`, `CONFIRM_LIVE=false`).

Several deployment friction points were identified and resolved as part of Phase 10:
1. `server.app:app` was not directly exported as a module variable; `uvicorn server.app:app` required a factory or exported instance.
2. Security headers (HSTS, CSP, X-Frame-Options, etc.) were not yet applied at the FastAPI layer.
3. Host binding defaulted to `0.0.0.0` rather than loopback `127.0.0.1`.
4. The database was stored at `data/outbound.db` with proper WAL pragmas, but lacked an automated, online backup and restore script.

---

## 2. Discovered Configuration & Runtime Assumptions

| Parameter / Resource | Current Value / Implementation | Production Target | Notes |
| :--- | :--- | :--- | :--- |
| **ASGI Server Entrypoint** | `server.app:create_app()` | `server.app:app` (exported) | Export `app` with safe fallback initialization |
| **Startup Command** | `.venv/bin/uvicorn server.app:app` | Same, bound to `127.0.0.1:8000` | Single worker process to preserve delivery mutex |
| **CLI Entrypoint** | `python main.py` | `python main.py` | Unchanged; must remain 100% compatible |
| **Database Path** | `data/outbound.db` | `data/outbound.db` (outside web root) | WAL mode, foreign keys ON, busy timeout 5000ms |
| **Upload Storage** | `uploads/resumes/{user_id}/{resume_id}.{ext}` | Same (quarantined) | 10MB limit, PDF/JSON, UUID paths |
| **Staged Deliveries** | `staged_deliveries/*.json` | Same | JSON audit artifacts written on delivery |
| **Contacted History** | `contacted_companies.jsonl` | Same | Preserved across restarts and backups |
| **Delivery Mode** | `stage` / `stub` | `stage` (`DRY_RUN=true`, `CONFIRM_LIVE=false`) | Live dispatch disabled by default |
| **Host Binding** | `0.0.0.0` | `127.0.0.1` | Loopback only behind Caddy reverse proxy |
| **Port Binding** | `8000` | `8000` | Internal only; blocked from public network |
| **Reverse Proxy** | None configured | Caddy (`:80`, `:443`) | Automatic TLS, security headers, path blocks |
| **CORS Origins** | `localhost`, `work.raghavpathak.me` | `https://work.raghavpatak.me`, `https://work.raghavpathak.me` | Supports both domain spellings |
| **Security Headers** | None in FastAPI | HSTS, CSP, X-Frame-Options, nosniff | Custom CSP compatible with inline scripts & fonts |
| **Health Check** | `GET /api/v1/health` | `GET /health` and `GET /api/v1/health` | Non-leaking DB check (`SELECT 1`) |
| **Worker Threads** | `ThreadPoolExecutor(max_workers=2)` | Same (`max_workers=2`) | Bounded concurrency with stage checkpointing |

---

## 3. Secret Hygiene & Repository Scan

A full scan was performed using Git grep across all tracked files:
```bash
git grep -n "AIza"
git grep -n "sk-"
git grep -n "Bearer "
git grep -in "api_key"
```

**Results**:
- No Google Gemini, Hunter, Apollo, Lemlist, or Instantly production API keys exist in tracked files.
- All references in tests are mocks (`fake_hunter`, `mock_gemini_key_for_test`, `test_key`).
- The repository has a single commit `742fbf4` on `main`. No historical commits contain leaked secrets.
- The `.env` file in the working directory is untracked and listed in `.gitignore`.
- `.env.example` contains only blank placeholders.

---

## 4. Infrastructure & Privileges Audit

1. **User Account**: Running as `raghavp` (UID 1000).
2. **Sudo Privileges**: User `raghavp` requires a password for sudo execution. Installing system-wide packages or editing `/etc/systemd/system/` or `/etc/caddy/` requires operator intervention. Pre-configured service and Caddy files are staged under `deploy/`.
3. **DNS**:
   - `work.raghavpatak.me` -> `NXDOMAIN` (A/AAAA record not yet pointed).
   - DNS verification will be reported factually as `NOT TESTED` (awaiting DNS record propagation).
4. **Firewall Requirement**:
   - Only ports `80/tcp` and `443/tcp` should be exposed publicly.
   - Port `8000/tcp` must remain bound to `127.0.0.1`.

---

## 5. Pre-Deployment Verification Baseline

- **Pytest Suite**: 207 passed, 0 failures, 1 warning (Starlette deprecation).
- **CLI Command**: `main.py --help` exited with code 0.
- **Delivery Safety Gates**: All 11 authoritative server-side gates verified in `test_server_delivery.py`.
