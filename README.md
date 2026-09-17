# Outbound Pipeline

A private, human-in-the-loop outbound outreach pipeline built with **FastAPI, LangGraph, SQLite, background workers, and a web-based operator cockpit**.

The system discovers companies, enriches contacts, generates personalized outreach drafts, routes them through mandatory human review, and enforces server-side safety gates before any delivery can occur.

> **Current status:** Phases 1–10 complete. The application is production-hardened and deployment-ready. Live outreach remains disabled by default.

---

## Overview

Outbound Pipeline started as a terminal-driven LangGraph pipeline and has been progressively transformed into a private web application while preserving the original CLI workflow.

The application provides:

* Campaign creation and management
* Company discovery and deterministic ranking
* Contact enrichment
* Resume-aware outreach drafting
* Human review and editing
* Background pipeline execution
* Delivery history and audit trails
* SQLite persistence
* Secure authentication
* Production deployment assets
* Backup and restore tooling
* CLI compatibility

The intended deployment is a private operator application at:

`https://work.raghavpatak.me`

---

## Architecture

```text
                         Internet
                            │
                            ▼
                  work.raghavpatak.me
                            │
                            ▼
                     ┌─────────────┐
                     │    Caddy    │
                     │ HTTPS / TLS │
                     └──────┬──────┘
                            │
                     127.0.0.1:8000
                            │
                            ▼
                     ┌─────────────┐
                     │   FastAPI   │
                     └──────┬──────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
           SQLite        Workers      Filesystem
                                      ├── uploads
                                      ├── staged_deliveries
                                      ├── backups
                                      └── contact history
```

### Pipeline

```text
Discovery
   ↓
Person Research
   ↓
Email Resolution
   ↓
Draft Generation
   ↓
Human Review
   ↓
Approval
   ↓
waiting_for_delivery
   ↓
Explicit Delivery Trigger
   ↓
Authoritative Safety Gates
   ↓
Staging / Live Provider
```

---

## Core Safety Model

The application is designed so that generating a draft and approving a draft **never automatically sends an email**.

A delivery requires an explicit delivery trigger followed by authoritative server-side validation.

The delivery service currently enforces 11 gates:

1. Tenant ownership
2. Valid `PipelineRun` state
3. Approved review associated with the same run
4. Draft integrity and revision consistency
5. Email syntax and consistency
6. Anti-fabrication and canonical blacklist checks
7. Email verification status
8. Person confidence threshold
9. Unified deduplication
10. Rolling delivery volume caps
11. Explicit server-side live configuration

If any safety gate fails, the provider is not called.

---

## Live Outreach Defaults

Live outreach is intentionally disabled by default.

Production-safe baseline:

```env
DELIVERY_MODE=stage
DRY_RUN=true
CONFIRM_LIVE=false
```

This means the application can execute the full workflow while staging delivery artifacts instead of contacting the live provider.

Actual live delivery requires all three server-side conditions:

```env
DELIVERY_MODE=live
DRY_RUN=false
CONFIRM_LIVE=true
```

`CONFIRM_LIVE` is a server-side kill switch and cannot be changed from the frontend.

Deployment does **not** automatically enable live outreach.

---

## Features

### Authentication

* Password hashing with bcrypt
* JWT authentication
* Token expiration
* Token revocation
* Silent refresh
* Login rate limiting
* Secure production cookies
* Tenant-aware authorization

### Campaigns

Campaigns support targeting by:

* Industry
* Technology
* Geography
* Company size
* Company stage
* Target roles
* Employment type
* Remote preference

### Discovery & Ranking

Candidates are normalized, verified, deduplicated, and ranked using a deterministic 100-point model:

```text
Industry       30 points
Technology     30 points
Stage / Size   20 points
Geography      20 points
-------------------------
Total         100 points
```

Each candidate stores the reasoning/signals behind its ranking.

### Enrichment

The enrichment pipeline uses a two-stage process:

```text
Person Research
      ↓
Email Resolution
```

Checkpointing allows recovery without unnecessarily repeating completed enrichment stages.

### Human Review

The review cockpit provides:

* Review queue
* Company intelligence
* Contact quality information
* Draft editing
* Approve / reject actions
* Previous / next navigation
* Audit trail
* Explicit delivery transition

Approval moves a run to:

```text
waiting_for_delivery
```

It does not send the message.

### Delivery

Delivery supports:

* Authoritative revalidation
* Staging mode
* Live mode
* Delivery history
* Safety-block auditing
* Provider failure handling
* Duplicate prevention
* Volume caps
* Atomic delivery claiming

The current live provider integration is Instantly.

---

## Web Interface

The operator cockpit includes:

```text
/login
/dashboard
/campaigns
/campaigns/{id}
/review
/review/{id}
/deliveries
/profile
/settings
```

The interface uses a responsive dark-mode design with consistent status indicators, confirmation flows, and audit information.

---

## API

Major API areas include:

```text
/api/v1/auth
/api/v1/profile
/api/v1/resumes
/api/v1/campaigns
/api/v1/campaigns/{id}/companies
/api/v1/review
/api/v1/deliveries
/api/v1/dashboard/stats
/api/v1/health
/health
```

Exact routes should be treated according to the implementation in `server/routers/`.

---

## Project Structure

```text
outbound-pipeline/
├── pipeline/
│   ├── adapters/
│   ├── config.py
│   ├── contacted_log.py
│   ├── delivery.py
│   ├── discovery.py
│   ├── drafting.py
│   ├── enrichment.py
│   ├── graph.py
│   ├── review.py
│   └── state.py
│
├── server/
│   ├── routers/
│   ├── services/
│   ├── app.py
│   ├── cli.py
│   ├── config.py
│   └── views.py
│
├── scripts/
│   ├── backup.py
│   └── restore.py
│
├── deploy/
│   ├── Caddyfile
│   └── outbound-pipeline.service
│
├── tests/
│
├── data/
├── uploads/
├── staged_deliveries/
├── backups/
├── logs/
│
├── main.py
├── DEPLOYMENT.md
├── PHASE10_PREDEPLOY_AUDIT.md
├── PHASE10_SECURITY_AUDIT.md
├── PHASE10_FINAL_REPORT.md
└── walkthrough.md
```

---

## Running Locally

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Install dependencies using the project's dependency file:

```bash
pip install -r requirements.txt
```

Create `.env` from `.env.example` and configure the required credentials.

For safe local development, keep:

```env
DELIVERY_MODE=stage
DRY_RUN=true
CONFIRM_LIVE=false
```

Start the application:

```bash
uvicorn server.app:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

---

## CLI Compatibility

The original CLI remains supported.

Verify:

```bash
python main.py --help
```

The web application does not replace the existing pipeline interface.

---

## Testing

Run the complete test suite:

```bash
pytest -q
```

Current Phase 10 verification:

```text
217 passed
0 failures
```

The suite covers:

* Authentication
* Authorization
* Campaign workflows
* Discovery
* Enrichment
* Background jobs
* Review
* Delivery safety
* IDOR protection
* Production configuration
* Security headers
* Health endpoints
* Cookie security
* Upload validation
* Backup/restore
* Restart recovery
* Delivery gate invariance

---

## Production Deployment

Production deployment assets are located in:

```text
deploy/
```

The deployment architecture uses:

```text
Caddy
  ↓
127.0.0.1:8000
  ↓
FastAPI
```

The application is intended to run as an unprivileged systemd service.

See:

```text
DEPLOYMENT.md
```

for the complete deployment procedure.

---

## Backup & Recovery

SQLite backups use the SQLite backup API to safely create backups while the database may be operating in WAL mode.

Backup utility:

```bash
python scripts/backup.py
```

Restore utility:

```bash
python scripts/restore.py
```

Restore supports integrity validation and dry-run inspection.

Backups should include application state required for recovery, including:

```text
SQLite database
contacted_companies.jsonl
staged_deliveries/
```

Sensitive credentials should not be included in backups unless separately secured.

---

## Security

The application includes production security controls including:

* Restricted CORS
* Secure authentication cookies
* JWT expiration and revocation
* Login rate limiting
* Tenant isolation
* Upload validation
* Path traversal protection
* Security headers
* CSP
* HSTS
* X-Frame-Options
* `nosniff`
* Referrer-Policy
* Loopback-only application binding
* Delivery safety gates
* Unified deduplication
* Delivery volume limits
* Audit events
* Secret exclusion from Git

The application is designed for a private single-operator deployment.

---

## Environment Variables

Never commit `.env`.

Use:

```text
.env.example
```

as the configuration reference.

Important variables include:

```env
APP_ENV=production
DATABASE_URL=...
JWT_SECRET_KEY=...

CORS_ALLOWED_ORIGINS=...

GEMINI_API_KEY=...
HUNTER_API_KEY=...
INSTANTLY_API_KEY=...

DELIVERY_MODE=stage
DRY_RUN=true
CONFIRM_LIVE=false
```

Use the exact variables defined by the current configuration implementation.

---

## Current Status

```text
Phase 1   Database / domain models              COMPLETE
Phase 2   FastAPI scaffold                      COMPLETE
Phase 3   Authentication / UI shell             COMPLETE
Phase 4   Resume parsing                        COMPLETE
Phase 5   Campaign / discovery / ranking       COMPLETE
Phase 6   Background execution                  COMPLETE
Phase 7   Human review                          COMPLETE
Phase 8   Delivery safety                       COMPLETE
Phase 9   Frontend / E2E verification           COMPLETE
Phase 10  Production hardening                  COMPLETE
```

Current automated verification:

```text
217 / 217 tests passing
0 failures
CLI compatibility verified
Secrets audit passed
Production configuration tests passed
```

---

## Known Limitations

### Provider idempotency

The current Instantly lead/add operation does not provide an external client-generated idempotency key.

Therefore, a narrow crash window remains:

```text
Provider succeeds
      ↓
Process crashes
      ↓
Local DB commit never occurs
      ↓
A retry may potentially call the provider again
```

The application mitigates duplicate execution through local locking and database state, but this provider-level limitation cannot be completely eliminated without provider-side idempotency support or an equivalent reconciliation mechanism.

### Single-instance deployment

The current delivery mutex is process-local and is appropriate for the intended single-instance private deployment.

Horizontal scaling would require a distributed locking/idempotency mechanism.

---

## Deployment Safety

Production deployment and live outreach activation are intentionally separate operations.

The application may be publicly reachable over HTTPS while remaining in:

```env
DELIVERY_MODE=stage
DRY_RUN=true
CONFIRM_LIVE=false
```

This allows the complete application to be tested without enabling actual outreach.

---

## License

Private project. All rights reserved.
