# Autonomous Outbound Lead Generation Pipeline — Production Deployment & Operator Manual

This document provides the complete, authoritative operational guide for deploying, running, backing up, and maintaining the Outbound Lead Pipeline at:

```text
https://work.raghavpatak.me
```

---

## 1. System Requirements

### Hardware & Operating System
- **Operating System**: Linux (Debian 12+, Ubuntu 22.04 LTS+, or Parrot OS 6+)
- **Architecture**: `x86_64` or `aarch64`
- **CPU**: 1–2 vCPUs
- **Memory**: 1–2 GB RAM
- **Disk Storage**: 10 GB SSD (for application, SQLite database, uploads, and backup tarballs)

### Software Prerequisites
- **Python**: Python 3.11, 3.12, or 3.13 (`python3-venv`, `python3-pip`)
- **Web Server**: Caddy v2 (`caddy`)
- **Process Manager**: systemd
- **Network / DNS**: Registered domain (`work.raghavpatak.me`) pointing to server public IP

---

## 2. Production Architecture

```text
Internet
   ↓ (Ports 80/443 TCP)
Caddy Reverse Proxy (HTTPS / Automatic TLS Let's Encrypt)
   ↓ (127.0.0.1:8000 TCP - loopback only)
FastAPI / Uvicorn (Single-instance worker, delivery mutex)
   ├── SQLite Database (WAL Mode, data/outbound.db)
   ├── Background Workers (ThreadPoolExecutor max_workers=2)
   ├── Quarantined Uploads (uploads/resumes/)
   ├── Staged Deliveries (staged_deliveries/)
   └── Contacted History (contacted_companies.jsonl)
```

---

## 3. Installation Guide

### Step 3.1: Create Dedicated Service User
```bash
sudo useradd -r -s /bin/false -d /home/raghavp/projects/outbound-pipeline raghavp || true
```

### Step 3.2: Clone & Directory Permissions
```bash
cd /home/raghavp/projects/outbound-pipeline

# Ensure runtime directories exist with proper ownership
mkdir -p data uploads/resumes staged_deliveries logs backups
chmod 700 .env || true
chmod 750 data uploads staged_deliveries logs backups
```

### Step 3.3: Python Virtual Environment & Dependencies
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 3.4: Configure Environment Secrets
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
chmod 600 .env
```
Generate a cryptographically random JWT signing key:
```bash
openssl rand -hex 32
```
Edit `.env` and set `JWT_SECRET_KEY` and your provider keys.

### Step 3.5: Initialize Database
```bash
.venv/bin/python -c "from server.database import init_db; init_db(); print('Database initialized successfully')"
```

---

## 4. Production Environment Configuration Reference

All environment variables used by the system:

| Variable | Category | Default | Description |
| :--- | :--- | :--- | :--- |
| `APP_ENV` | Required | `production` | Environment mode (`production`, `development`, `test`) |
| `HOST` | Required | `127.0.0.1` | Loopback binding host (never bind 0.0.0.0 publicly) |
| `PORT` | Required | `8000` | Internal ASGI server port |
| `DATABASE_URL` | Optional | `sqlite:///./data/outbound.db` | SQLAlchemy database connection string |
| `JWT_SECRET_KEY` | **Required** | *None* | 32-byte secret key for HMAC-SHA256 JWT tokens |
| `JWT_ALGORITHM` | Optional | `HS256` | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Optional | `1440` | Token lifetime in minutes |
| `SECURE_COOKIES` | Optional | `None` | Force `Secure` flag on cookies (auto-detected if HTTPS) |
| `CORS_ORIGINS` | Optional | `https://work.raghavpatak.me` | Comma-separated list of allowed origins |
| `DELIVERY_MODE` | **Safety** | `stage` | Delivery mode: `stage`, `stub`, `live` |
| `DRY_RUN` | **Safety** | `true` | When true, zero provider network dispatches |
| `CONFIRM_LIVE` | **Safety** | `false` | **Server-side live dispatch lock**. Must remain `false` by default |
| `MAX_SENDS_PER_DAY` | Policy | `10` | Daily outreach volume cap |
| `MAX_SENDS_PER_WEEK` | Policy | `50` | Weekly outreach volume cap |
| `DISCOVERY_MODE` | Pipeline | `research` | `research`, `live`, or `stub` |
| `ENRICHMENT_MODE` | Pipeline | `two_stage` | `two_stage`, `live`, or `stub` |
| `DRAFTING_MODE` | Pipeline | `live` | `live` or `stub` |
| `GEMINI_API_KEY` | Provider | *Blank* | Google AI Studio free-tier API key |
| `HUNTER_API_KEY` | Provider | *Blank* | Hunter.io API key for Stage 2 email resolution |
| `APOLLO_API_KEY` | Provider | *Blank* | Apollo.io API key |
| `INSTANTLY_API_KEY` | Provider | *Blank* | Instantly.ai webhook/API key |
| `LEMLIST_API_KEY` | Provider | *Blank* | Lemlist API key |

> [!CAUTION]
> **Live Sending Invariant**:
> Live sending requires `DELIVERY_MODE=live`, `DRY_RUN=false`, and `CONFIRM_LIVE=true`. These can only be set via `.env` on the server. The web UI has zero capability to toggle live sending.

---

## 5. systemd Service Management

The production unit file is located at `deploy/outbound-pipeline.service`.

### Installation
```bash
sudo cp deploy/outbound-pipeline.service /etc/systemd/system/outbound-pipeline.service
sudo systemctl daemon-reload
sudo systemctl enable outbound-pipeline.service
```

### Service Controls
```bash
# Start service
sudo systemctl start outbound-pipeline

# Restart service
sudo systemctl restart outbound-pipeline

# Stop service
sudo systemctl stop outbound-pipeline

# Check status
sudo systemctl status outbound-pipeline

# View live application logs
sudo journalctl -u outbound-pipeline -f --no-hostname
```

---

## 6. Caddy Reverse Proxy & TLS

The Caddy configuration is located at `deploy/Caddyfile`.

### Installation
```bash
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

### Automatic TLS
- Caddy automatically requests and renews valid TLS certificates from Let's Encrypt / ZeroSSL on port 443.
- Automatic HTTP-to-HTTPS redirect is enabled by default.
- Test certificate renewal dry-run:
  ```bash
  sudo caddy reload --config /etc/caddy/Caddyfile
  ```

---

## 7. Firewall & Network Hardening

Ensure only required ports are exposed to the public internet:
```bash
# Allow SSH, HTTP, and HTTPS
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# Verify port 8000 is NOT exposed
sudo ufw status verbose
curl -I http://127.0.0.1:8000/health
```

---

## 8. Backup Strategy

We provide an online, transactionally-atomic backup script `scripts/backup.py` that uses the SQLite online backup API.

### Run Manual Backup
```bash
.venv/bin/python scripts/backup.py --retention 14
```

### Automated Cron Job (Daily at 03:00 UTC)
Add to crontab (`crontab -e`):
```cron
0 3 * * * /home/raghavp/projects/outbound-pipeline/.venv/bin/python /home/raghavp/projects/outbound-pipeline/scripts/backup.py --retention 14 >> /home/raghavp/projects/outbound-pipeline/logs/backup.log 2>&1
```

---

## 9. Restore Procedure

### Step 9.1: Dry-Run Inspection
```bash
.venv/bin/python scripts/restore.py backups/outbound_backup_YYYYMMDD_HHMMSS.tar.gz --dry-run
```

### Step 9.2: Stop Service & Restore
```bash
sudo systemctl stop outbound-pipeline

.venv/bin/python scripts/restore.py backups/outbound_backup_YYYYMMDD_HHMMSS.tar.gz

sudo systemctl start outbound-pipeline
```

### Step 9.3: Verify Health
```bash
curl -s http://127.0.0.1:8000/health
```

---

## 10. Rollback Procedure

If a deployed code update introduces issues:

1. **Stop the Service**:
   ```bash
   sudo systemctl stop outbound-pipeline
   ```
2. **Revert Git Version**:
   ```bash
   git checkout <PREVIOUS_STABLE_COMMIT_OR_TAG>
   ```
3. **Restore Database from Pre-Deployment Backup**:
   ```bash
   .venv/bin/python scripts/restore.py backups/<PRE_DEPLOY_BACKUP>.tar.gz
   ```
4. **Restart Service & Verify**:
   ```bash
   sudo systemctl start outbound-pipeline
   curl -s http://127.0.0.1:8000/health
   ```

---

## 11. Troubleshooting Common Issues

### 1. `502 Bad Gateway` in Browser
- **Cause**: Uvicorn is not running or crashed on startup.
- **Check**: `sudo systemctl status outbound-pipeline` and `journalctl -u outbound-pipeline -n 50`.
- **Fix**: Check for missing environment variables (e.g. `JWT_SECRET_KEY` in `.env`).

### 2. `Database is locked` (SQLite)
- **Cause**: Multiple processes writing or WAL checkpoint contention.
- **Check**: `PRAGMA busy_timeout;` is set to 5000ms.
- **Fix**: Verify exactly 1 Uvicorn worker process is running (`--workers 1`). Do not run multiple application instances.

### 3. TLS Certificate Failure
- **Cause**: DNS A record for `work.raghavpatak.me` does not match the server's public IP address or port 80 is blocked.
- **Check**: `dig +short work.raghavpatak.me` and `sudo ufw status`.
- **Fix**: Ensure port 80/tcp is open for ACME challenge validation.

### 4. Resume Upload Rejection (400 / 413)
- **Cause**: File exceeds 10MB limit or has non-PDF/non-JSON extension.
- **Fix**: Ensure uploaded resumes are valid PDF or JSON under 10MB.
