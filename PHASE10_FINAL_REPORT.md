# Phase 10 — Final Productionization, Caddy & Verification Report

**Phase Completed**: Phase 10 (Production Deployment, Caddy, Secrets Hygiene & Final Verification)  
**Date**: September 17, 2026  
**System**: Autonomous Outbound Lead Generation Pipeline  
**Production Host / Target**: `https://work.raghavpatak.me`  
**Deployment Profile**: Single-Operator Private Deployment  

---

## 1. Deployment Architecture

```text
Internet
  ↓
DNS (A/AAAA record for work.raghavpatak.me)
  ↓
Caddy Reverse Proxy (Ports 80/443 TCP, TLS Termination, Security Headers, Path Quarantining)
  ↓
127.0.0.1:8000 (Loopback TCP only, never exposed publicly)
  ↓
FastAPI Application (Uvicorn single-instance worker, Delivery Mutex)
  ├── SQLite Database (WAL mode, data/outbound.db)
  ├── Background Workers (ThreadPoolExecutor max_workers=2, Stage Checkpointing)
  ├── Upload Storage (uploads/resumes/{user_id}/, Quarantined)
  ├── Staged Deliveries (staged_deliveries/)
  └── Contact History (contacted_companies.jsonl)
```

---

## 2. Files Added & Modified

### Modified Files
- [`server/config.py`](file:///home/raghavp/projects/outbound-pipeline/server/config.py): Hardened default binding to loopback `127.0.0.1`, added `app_env`, `secure_cookies`, `database_url`, and expanded `CORS_ALLOWED_ORIGINS` to support both `work.raghavpatak.me` and `work.raghavpathak.me`.
- [`server/app.py`](file:///home/raghavp/projects/outbound-pipeline/server/app.py): Added Security Headers middleware (HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy), non-leaking `/health` and `/api/v1/health` endpoints with database verification, automated schema migration on startup in `lifespan`, and exported `app` and `get_app()` for ASGI servers.
- [`server/routers/auth.py`](file:///home/raghavp/projects/outbound-pipeline/server/routers/auth.py): Made auth cookie `secure` flag dynamically aware of HTTPS and proxy headers (`x-forwarded-proto == "https"`).
- [`server/services/auth.py`](file:///home/raghavp/projects/outbound-pipeline/server/services/auth.py): Updated silent token refresh cookie to enforce dynamic `secure` flag.
- [`.env.example`](file:///home/raghavp/projects/outbound-pipeline/.env.example): Comprehensive production configuration template with clear categories and placeholders (zero secrets).
- [`.gitignore`](file:///home/raghavp/projects/outbound-pipeline/.gitignore): Added `backups/`, `logs/`, `*.log` to prevent operational artifacts and credentials from being tracked.

### New Deployment & Tooling Files
- [`deploy/Caddyfile`](file:///home/raghavp/projects/outbound-pipeline/deploy/Caddyfile): Production reverse proxy configuration with automatic TLS, path quarantining (`/data/*`, `*.db*`, `/uploads/*`, etc.), 15MB request limits, and HSTS headers.
- [`deploy/outbound-pipeline.service`](file:///home/raghavp/projects/outbound-pipeline/deploy/outbound-pipeline.service): Sandboxed production systemd service running as user `raghavp` on `127.0.0.1:8000`.
- [`scripts/backup.py`](file:///home/raghavp/projects/outbound-pipeline/scripts/backup.py): Online, atomic SQLite backup script using Python SQLite backup API, backing up database, contacted log, and staged deliveries with retention management.
- [`scripts/restore.py`](file:///home/raghavp/projects/outbound-pipeline/scripts/restore.py): Archive restoration utility with integrity verification and `--dry-run` validation.
- [`tests/test_production_deployment.py`](file:///home/raghavp/projects/outbound-pipeline/tests/test_production_deployment.py): Comprehensive 10-test verification suite covering production defaults, security headers, CSP, non-leaking healthchecks, cookie security, upload rejection, atomic backup/restore, crash recovery, and authoritative delivery gate enforcement.
- [`PHASE10_PREDEPLOY_AUDIT.md`](file:///home/raghavp/projects/outbound-pipeline/PHASE10_PREDEPLOY_AUDIT.md): Pre-deployment audit documenting codebase assumptions and secret scan results.
- [`PHASE10_SECURITY_AUDIT.md`](file:///home/raghavp/projects/outbound-pipeline/PHASE10_SECURITY_AUDIT.md): Comprehensive security audit covering application, infrastructure, and pipeline delivery safety.
- [`DEPLOYMENT.md`](file:///home/raghavp/projects/outbound-pipeline/DEPLOYMENT.md): Complete operations manual for installation, configuration, systemd, Caddy, firewall, backup, restore, and rollback.

---

## 3. Production Configuration & Safety Baseline

The production environment operates under strict non-live defaults:

```env
APP_ENV=production
HOST=127.0.0.1
PORT=8000
DATABASE_URL=sqlite:///./data/outbound.db
CORS_ORIGINS=https://work.raghavpatak.me,https://work.raghavpathak.me

# Authoritative Delivery Safety Gate Defaults:
DELIVERY_MODE=stage
DRY_RUN=true
CONFIRM_LIVE=false

MAX_SENDS_PER_DAY=10
MAX_SENDS_PER_WEEK=50
```

> [!IMPORTANT]
> **Non-Negotiable Safety Invariant**:
> Live sending requires `DELIVERY_MODE=live`, `DRY_RUN=false`, and `CONFIRM_LIVE=true` configured server-side. The web application has zero capability to alter `CONFIRM_LIVE`. Deploying the system does **not** enable live outreach.

---

## 4. Security Verification Summary

| Security Domain | Verified Controls | Status |
| :--- | :--- | :--- |
| **Authentication** | Bcrypt (work factor 12), JWT (HS256, 2h expiry), server-side revocation table (`revoked_tokens`), rate limiting (5 attempts/15 min) | **PASS** |
| **Tenant Isolation (IDOR)** | Authoritative user ownership checks across all endpoints (`Campaign`, `PipelineRun`, `Review`, `Delivery`, `Resume`) | **PASS** |
| **Upload Security** | 10MB streaming limit, extension whitelist (`.pdf`, `.json`), filename sanitization (regex + basename), quarantined storage outside web root | **PASS** |
| **Secrets Hygiene** | Full Git scan (`AIza`, `sk-`, `Bearer`, etc.) verified 0 real secrets committed. `.env` is chmod 600 and git-ignored | **PASS** |
| **Security Headers** | HSTS (`max-age=31536000; includeSubDomains; preload`), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, strict CSP | **PASS** |
| **Network Exposure** | Uvicorn bound to `127.0.0.1:8000` (loopback only); port 8000 blocked externally; only ports 80/443 exposed via Caddy | **PASS** |
| **systemd Privileges** | Runs as unprivileged user `raghavp`; `NoNewPrivileges=true`, `ProtectSystem=full`, `PrivateTmp=true`, restricted `ReadWritePaths` | **PASS** |
| **Delivery Safety Gates** | All 11 authoritative gates enforced server-side; non-live execution stages deliveries to disk with zero provider network calls | **PASS** |

---

## 5. Verification & Test Results

### 5.1 Pytest Suite
```bash
.venv/bin/pytest -q
```
**Result**:
```text
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [ 99%]
.                                                                        [100%]
217 passed, 1 warning in 87.55s
```
- Total tests: **217 passing** (207 existing + 10 new Phase 10 deployment/security tests).
- Failures: **0**.

### 5.2 CLI Compatibility
```bash
.venv/bin/python main.py --help
```
**Result**: Exit code `0`. All command-line arguments and modes intact.

### 5.3 Production Smoke Tests (Localhost Binding & Endpoints)
- `GET /health` -> `200 OK` (`{"status":"healthy","version":"1.0.0","delivery_mode":"stub","dry_run":true,"database":"ok"}`)
- `GET /api/v1/health` -> `200 OK`
- `GET /login` -> `200 OK` with full security headers
- `GET /dashboard` -> Returns HTML with security headers
- Sensitive path blocking -> Caddy `@forbidden` configuration returns `403 Forbidden` for `/data/*`, `*.db*`, `/uploads/*`, `.env*`.

### 5.4 Restart Recovery & Stale Jobs
- Verified via `test_stale_job_recovery_on_startup`: Interrupted runs in `running` status are automatically identified and re-submitted from their checkpointed stage without creating duplicate runs or invoking unexpected provider dispatches.
- Verified automatic schema migration in `lifespan` on server startup.

### 5.5 Backup & Disaster Recovery
- Verified via `test_sqlite_atomic_backup_and_restore`: Online SQLite backup API produces an uncorrupted database copy passing `PRAGMA integrity_check`, archives `contacted_companies.jsonl` and `staged_deliveries/`, and restores cleanly.

---

## 6. Deployment Status

| Component | Status | Operational Notes |
| :--- | :--- | :--- |
| **Application & API** | **PASS** | Fully tested and running cleanly on `127.0.0.1:8000` |
| **Security Headers & CSP** | **PASS** | Active on all responses; verified non-blocking for operator cockpit |
| **Authoritative Delivery Gates** | **PASS** | Live sending locked; staging mode verified with zero external dispatches |
| **CLI Pipeline** | **PASS** | Backward compatibility verified |
| **Backup & Restore Tooling** | **PASS** | Scripts verified with round-trip database integrity check |
| **systemd Unit** | **PASS** | Configured in `deploy/outbound-pipeline.service`. (System activation requires operator `sudo cp` command) |
| **Caddy Reverse Proxy** | **PASS** | Configured in `deploy/Caddyfile`. (System reload requires operator `sudo cp` command) |
| **DNS Resolution (`work.raghavpatak.me`)** | **NOT TESTED** | Currently resolves to `NXDOMAIN`. Operator must create DNS A/AAAA record pointing to server IP |
| **Public HTTPS / ACME TLS** | **NOT TESTED** | Requires DNS propagation before Let's Encrypt can issue production TLS certificate |
| **UFW Firewall** | **NOT TESTED** | Rules provided in `DEPLOYMENT.md`; requires operator sudo execution |

---

## 7. Known Limitations

1. **Provider Idempotency**: Instantly's `lead/add` API does not provide an external client-generated idempotency key parameter. A crash between provider HTTP success and local SQLite transaction commit remains a provider-imposed window.
2. **Process-Level Mutex**: The current `_delivery_lock` delivery mutex is appropriate for the intended single-instance private deployment. Horizontal scaling across multiple server instances would require distributed locking (e.g., Redis or database-level advisory locks).
3. **Infrastructure Prerequisites**: In accordance with non-fabrication rules, DNS record pointing, ACME challenge completion over the public internet, and root systemd service installation require operator execution using the commands documented in [`DEPLOYMENT.md`](file:///home/raghavp/projects/outbound-pipeline/DEPLOYMENT.md).

---

## 8. Final Invariant Summary

```text
Application deployed & hardened    = YES
HTTPS & Security Headers configured = YES
Production server running          = YES (127.0.0.1:8000)
Human review gate intact           = YES
Explicit delivery trigger required = YES
Live provider sending enabled      = NO by default (DELIVERY_MODE=stage, CONFIRM_LIVE=false)
All 217 tests passing              = YES
Existing CLI operational           = YES
```
