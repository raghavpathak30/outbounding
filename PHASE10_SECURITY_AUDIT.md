# Phase 10 — Comprehensive Production Security Audit

**Audit Date**: September 17, 2026  
**Auditor**: Antigravity Autonomous Security Engineer  
**Scope**: Application, Infrastructure, Persistence, and Outbound Delivery Pipeline  
**Target Domain**: `https://work.raghavpatak.me`

---

## 1. Application Security

### Finding APP-01: Authentication & Password Storage
- **Evidence**: `server/services/auth.py` hashes passwords with `bcrypt.hashpw(..., bcrypt.gensalt(rounds=12))`. Tokens are signed with `HS256` using an unguessable 32-byte secret loaded from the environment, verified against expiration (`exp`), issued at (`iat`), subject (`sub`), and unique token ID (`jti`).
- **Risk**: Low.
- **Status**: **PASS**.
- **Remediation**: Work factor 12 and server-side token revocation via the `RevokedToken` SQLite table prevent brute-force attacks and session reuse after logout.

### Finding APP-02: Tenant Isolation & Insecure Direct Object References (IDOR)
- **Evidence**: All database queries across `/api/v1/campaigns/{id}`, `/api/v1/review/{id}`, `/api/v1/deliveries/{run_id}`, and `/api/v1/resumes/{id}` enforce ownership filters (`Campaign.user_id == current_user.id`, `Resume.user_id == current_user.id`).
- **Risk**: Low.
- **Status**: **PASS**.
- **Remediation**: Authoritative user scoping is enforced server-side; cross-tenant access returns HTTP 404 or HTTP 403.

### Finding APP-03: Cookie Security & Session Management
- **Evidence**: Auth tokens are stored in `httpOnly` cookies with `SameSite=Lax`. In Phase 10, dynamic HTTPS detection (`x-forwarded-proto == "https"` or `settings.secure_cookies is True`) sets `Secure=True` in production while preserving local development/testing flexibility.
- **Risk**: Low.
- **Status**: **PASS**.
- **Remediation**: Cookie tampering and client-side JavaScript theft via `document.cookie` are mitigated.

### Finding APP-04: Cross-Site Scripting (XSS) & Content-Security-Policy (CSP)
- **Evidence**: Security Headers middleware in `server/app.py` injects:
  `Content-Security-Policy: default-src 'self'; font-src 'self' https://fonts.gstatic.com data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; script-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data: https:; frame-ancestors 'none'; base-uri 'self'; form-action 'self';`
- **Risk**: Low.
- **Status**: **PASS**.
- **Remediation**: The CSP allows the operator cockpit's inline CSS styles, inline JS handlers, and Google Fonts while blocking untrusted external origins and frame embedding.

### Finding APP-05: SQL Injection Protection
- **Evidence**: All database interactions in `server/` use SQLAlchemy 2.0 ORM expressions (`select(...)`, `where(...)`, `mapped_column`) with parameterized binds. No raw SQL concatenation exists.
- **Risk**: Low.
- **Status**: **PASS**.
- **Remediation**: Standard ORM parameter binding eliminates SQL injection vectors.

### Finding APP-06: Resume Upload Quarantining & Path Traversal
- **Evidence**: `ResumeService.validate_upload` in `server/services/resume.py` enforces:
  1. 10MB maximum file size via streaming chunk evaluation.
  2. Whitelist of file extensions: `.pdf`, `.json`.
  3. Strict filename sanitization using `re.sub(r"[^a-zA-Z0-9_\-\.]", "_", Path(filename).name)`.
  4. UUID-partitioned storage: `uploads/resumes/{user_id}/{resume_id}{ext}` located outside the public web root.
- **Risk**: Low.
- **Status**: **PASS**.
- **Remediation**: Filename path traversal (`../../etc/passwd`) is stripped, executable scripts are rejected, and uploads are unreachable via direct web URLs.

---

## 2. Infrastructure & Network Security

### Finding INF-01: Network Exposure & Binding Interface
- **Evidence**: In `server/config.py`, the default binding host was changed from `0.0.0.0` to `127.0.0.1`. The systemd service `deploy/outbound-pipeline.service` specifies `--host 127.0.0.1 --port 8000`.
- **Risk**: Low.
- **Status**: **PASS**.
- **Remediation**: Port 8000 is loopback-only and inaccessible from the public internet. All traffic must pass through Caddy.

### Finding INF-02: systemd Sandboxing & Least Privilege
- **Evidence**: `deploy/outbound-pipeline.service` runs as unprivileged user `raghavp`, with `NoNewPrivileges=true`, `ProtectSystem=full`, `ProtectHome=read-only`, `PrivateTmp=true`, `ProtectKernelTunables=true`, and explicit `ReadWritePaths`.
- **Risk**: Low.
- **Status**: **PASS**.
- **Remediation**: If the application process were ever compromised, the attacker cannot escalate privileges, modify system binaries, or access home directory contents outside designated read-write paths.

### Finding INF-03: Caddy Reverse Proxy & Path Blocking
- **Evidence**: `deploy/Caddyfile` defines an explicit `@forbidden` matcher blocking direct HTTP access to `/data/*`, `/uploads/*`, `/staged_deliveries/*`, `/backups/*`, `/logs/*`, `*.db*`, `*.sqlite*`, and `.env*` with HTTP 403.
- **Risk**: Low.
- **Status**: **PASS**.
- **Remediation**: Internal database files, logs, and uploads cannot be downloaded directly via Caddy.

### Finding INF-04: Secrets Management & Git Cleanliness
- **Evidence**: A full scan across commit history (`742fbf4`) and tracked files showed zero committed API keys or JWT secrets. `.env` is properly ignored in `.gitignore`.
- **Risk**: Low.
- **Status**: **PASS**.
- **Remediation**: Secrets remain solely in the server's local, chmod 600 `.env` file.

---

## 3. Pipeline Delivery Safety Gates

### Finding DEL-01: Non-Live Staging Default
- **Evidence**: `server/config.py` and `.env.example` set `DELIVERY_MODE=stage`, `DRY_RUN=true`, `CONFIRM_LIVE=false`.
- **Risk**: Low.
- **Status**: **PASS**.
- **Remediation**: Live network dispatch to email providers (Instantly, Lemlist) is physically impossible without all three variables explicitly enabled on the server.

### Finding DEL-02: Authoritative Server-Side Delivery Gates
- **Evidence**: `DeliveryService.deliver_pipeline_run` validates all 11 gates server-side before any send attempt:
  1. Tenant ownership validation
  2. PipelineRun status == `waiting_for_delivery`
  3. Review status == `approved`
  4. Immutable draft subject and body integrity
  5. RFC email syntax verification
  6. Canonical blacklist & anti-fabrication filtering
  7. Email verification status
  8. Technical leader confidence threshold (>= 0.70)
  9. 3-source deduplication union (CLI JSONL + DB Deliveries + Company records)
  10. Rolling volume caps (10/day, 50/week)
  11. Server-side live configuration gate
- **Risk**: Low.
- **Status**: **PASS**.
- **Remediation**: Gates cannot be bypassed by frontend tampering, modified query parameters, or direct API requests.

### Finding DEL-03: Provider Failure & Mutex Concurrency
- **Evidence**: Outbound delivery claims are serialized using `_delivery_lock` (threading.Lock). Delivery status is marked as `claimed` in the database prior to provider dispatch.
- **Risk**: Medium (Known Provider Limitation).
- **Status**: **ACCEPTED RISK (DOCUMENTED)**.
- **Remediation**: Instantly's `lead/add` API does not accept an operator-generated client idempotency key. A crash between provider HTTP success and local SQLite transaction commit remains a provider-imposed window. The process-level mutex is appropriate for the single-instance production deployment.
