"""
HTML & CSS frontend views for the Outbound Lead Pipeline Operator Cockpit.
Provides responsive, high-density, cybersecurity-themed operator consoles:
- /login: Operator authentication gate
- /dashboard: Real-time operational cockpit with volume caps, metric cards, and needs attention queues
- /campaigns: Campaign management, creation modal, and target summaries
- /campaigns/{id}: Candidate discovery grid, deterministic ranking, selection, enqueue, and run progress
- /review: Review cockpit with authoritative human editing, separate delivery trigger, and audit timeline
- /deliveries: Outbound delivery history, safety audit inspector, and status filtering
- /profile: Candidate profile bio editor and resume parser management
- /settings: Read-only dispatch safety configuration and volume invariant monitor
"""

SHARED_CSS = """
    :root {
      --bg-base: #0a0f1d;
      --card-bg: #111827;
      --card-border: #1f2937;
      --card-hover: #1e293b;
      --accent: #3b82f6;
      --accent-glow: rgba(59, 130, 246, 0.25);
      --text-main: #f9fafb;
      --text-muted: #9ca3af;
      --text-dim: #6b7280;
      --success: #10b981;
      --success-glow: rgba(16, 185, 129, 0.2);
      --warning: #f59e0b;
      --warning-glow: rgba(245, 158, 11, 0.2);
      --purple: #8b5cf6;
      --purple-glow: rgba(139, 92, 246, 0.2);
      --cyan: #06b6d4;
      --danger: #ef4444;
      --danger-glow: rgba(239, 68, 68, 0.2);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg-base);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .navbar {
      background: rgba(17, 24, 39, 0.92);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--card-border);
      padding: 0.85rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .brand { display: flex; align-items: center; gap: 1.5rem; }
    .brand-logo { display: flex; align-items: center; gap: 0.6rem; font-weight: 700; font-size: 1.15rem; color: #fff; text-decoration: none; }
    .brand-icon { font-size: 1.3rem; }
    .nav-links { display: flex; gap: 1.25rem; }
    .nav-link { color: var(--text-muted); text-decoration: none; font-size: 0.88rem; font-weight: 500; transition: color 0.2s; padding: 0.35rem 0.6rem; border-radius: 6px; }
    .nav-link:hover { color: #fff; text-decoration: none; }
    .nav-link.active { color: #60a5fa; background: rgba(59, 130, 246, 0.12); font-weight: 600; }
    .user-section { display: flex; align-items: center; gap: 1rem; }
    .user-badge { font-size: 0.82rem; color: var(--text-muted); display: flex; align-items: center; gap: 0.4rem; }
    .user-email { color: #60a5fa; font-weight: 600; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--success); display: inline-block; }
    .btn-logout {
      background: transparent;
      border: 1px solid #374151;
      color: var(--text-muted);
      border-radius: 6px;
      padding: 0.4rem 0.8rem;
      font-size: 0.8rem;
      cursor: pointer;
      transition: all 0.2s;
    }
    .btn-logout:hover { color: #f87171; border-color: #ef4444; }
    .main-content {
      flex: 1;
      max-width: 1360px;
      width: 100%;
      margin: 0 auto;
      padding: 2rem;
    }
    .page-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 2rem;
      flex-wrap: wrap;
      gap: 1rem;
    }
    .page-title { font-size: 1.5rem; font-weight: 700; letter-spacing: -0.02em; display: flex; align-items: center; gap: 0.75rem; }
    .page-subtitle { color: var(--text-muted); font-size: 0.88rem; margin-top: 0.25rem; }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      padding: 0.55rem 1.1rem;
      font-size: 0.88rem;
      font-weight: 600;
      border-radius: 8px;
      border: none;
      cursor: pointer;
      transition: all 0.2s;
      text-decoration: none;
    }
    .btn:hover { opacity: 0.92; text-decoration: none; }
    .btn-primary { background: linear-gradient(135deg, #2563eb, #3b82f6); color: #fff; box-shadow: 0 0 15px var(--accent-glow); }
    .btn-success { background: linear-gradient(135deg, #059669, #10b981); color: #fff; box-shadow: 0 0 15px var(--success-glow); }
    .btn-warning { background: linear-gradient(135deg, #d97706, #f59e0b); color: #fff; }
    .btn-danger { background: linear-gradient(135deg, #dc2626, #ef4444); color: #fff; box-shadow: 0 0 15px var(--danger-glow); }
    .btn-purple { background: linear-gradient(135deg, #7c3aed, #8b5cf6); color: #fff; box-shadow: 0 0 15px var(--purple-glow); }
    .btn-secondary { background: #1f2937; color: var(--text-main); border: 1px solid #374151; }
    .btn-secondary:hover { background: #374151; }
    .btn-sm { padding: 0.35rem 0.75rem; font-size: 0.8rem; }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 1.5rem;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.25);
      margin-bottom: 1.5rem;
    }
    .card-title { font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 0.75rem; display: flex; justify-content: space-between; align-items: center; }
    .table-container { overflow-x: auto; border-radius: 8px; border: 1px solid var(--card-border); background: #0c111e; }
    table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.88rem; }
    th { background: #131b2e; padding: 0.85rem 1rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; border-bottom: 1px solid var(--card-border); }
    td { padding: 0.85rem 1rem; border-bottom: 1px solid #1a2333; color: var(--text-main); vertical-align: middle; }
    tr:hover td { background: rgba(30, 41, 59, 0.5); }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.25rem 0.6rem;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      white-space: nowrap;
    }
    .badge-blue { background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }
    .badge-green { background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
    .badge-amber { background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    .badge-purple { background: rgba(139, 92, 246, 0.15); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.3); }
    .badge-cyan { background: rgba(6, 182, 212, 0.15); color: #22d3ee; border: 1px solid rgba(6, 182, 212, 0.3); }
    .badge-red { background: rgba(239, 68, 68, 0.15); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3); }
    .badge-gray { background: rgba(107, 114, 128, 0.15); color: #9ca3af; border: 1px solid rgba(107, 114, 128, 0.3); }
    .toast {
      position: fixed;
      bottom: 2rem;
      right: 2rem;
      padding: 0.85rem 1.25rem;
      border-radius: 8px;
      font-size: 0.88rem;
      font-weight: 500;
      z-index: 1000;
      display: none;
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
      animation: slideUp 0.3s ease;
    }
    .toast-success { background: #065f46; border: 1px solid #10b981; color: #ecfdf5; }
    .toast-error { background: #7f1d1d; border: 1px solid #ef4444; color: #fef2f2; }
    .modal-backdrop {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.75);
      backdrop-filter: blur(4px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 200;
      padding: 1.5rem;
    }
    .modal {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      width: 100%;
      max-width: 620px;
      max-height: 90vh;
      overflow-y: auto;
      padding: 2rem;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
      animation: zoomIn 0.2s ease;
    }
    .modal-title { font-size: 1.25rem; font-weight: 700; margin-bottom: 0.5rem; }
    .modal-subtitle { font-size: 0.85rem; color: var(--text-muted); margin-bottom: 1.5rem; }
    .form-group { margin-bottom: 1.25rem; }
    label { display: block; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 0.4rem; }
    input[type="text"], input[type="email"], input[type="number"], select, textarea {
      width: 100%;
      background: #0b0f19;
      border: 1px solid #374151;
      border-radius: 8px;
      padding: 0.65rem 0.9rem;
      color: var(--text-main);
      font-size: 0.9rem;
      font-family: inherit;
    }
    input:focus, select:focus, textarea:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-glow);
    }
    .modal-actions { display: flex; justify-content: flex-end; gap: 0.75rem; margin-top: 1.75rem; }
    @keyframes slideUp { from { transform: translateY(20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
    @keyframes zoomIn { from { transform: scale(0.95); opacity: 0; } to { transform: scale(1); opacity: 1; } }
"""

NAVBAR_TEMPLATE = """
  <header class="navbar">
    <div class="brand">
      <a href="/dashboard" class="brand-logo">
        <span class="brand-icon">⚡</span>
        <span>Outbound Pipeline</span>
      </a>
      <nav class="nav-links">
        <a href="/dashboard" class="nav-link {active_dashboard}">Dashboard</a>
        <a href="/campaigns" class="nav-link {active_campaigns}">Campaigns</a>
        <a href="/review" class="nav-link {active_review}">Review Cockpit</a>
        <a href="/deliveries" class="nav-link {active_deliveries}">Deliveries</a>
        <a href="/profile" class="nav-link {active_profile}">Profile & Resumes</a>
        <a href="/settings" class="nav-link {active_settings}">Settings</a>
      </nav>
    </div>
    <div class="user-section">
      <span class="user-badge" id="nav-user-badge"><span class="status-dot"></span> <span id="nav-user-email">Operator</span></span>
      <button class="btn-logout" id="logout-btn">Sign Out</button>
    </div>
  </header>
"""

SHARED_JS = """
  function showToast(msg, isError = false) {
    const el = document.getElementById('global-toast');
    if (!el) return;
    el.textContent = msg;
    el.className = 'toast ' + (isError ? 'toast-error' : 'toast-success');
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 4000);
  }

  function escapeHtml(text) {
    if (text === null || text === undefined) return '';
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  async function checkAuth() {
    try {
      const res = await fetch('/api/v1/auth/me');
      if (!res.ok) {
        window.location.href = '/login';
        return null;
      }
      const data = await res.json();
      const emailEl = document.getElementById('nav-user-email');
      if (emailEl) emailEl.textContent = data.email;
      return data;
    } catch (e) {
      window.location.href = '/login';
      return null;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('logout-btn')?.addEventListener('click', async () => {
      try { await fetch('/api/v1/auth/logout', { method: 'POST' }); }
      finally { window.location.href = '/login'; }
    });
  });
"""


# =====================================================================
# 1. /login
# =====================================================================
def get_login_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Sign In - Outbound Pipeline Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-base: #090d16;
      --card-bg: #111827;
      --card-border: #1f2937;
      --accent: #3b82f6;
      --accent-glow: rgba(59, 130, 246, 0.4);
      --text-main: #f9fafb;
      --text-muted: #9ca3af;
      --danger: #ef4444;
      --danger-bg: rgba(239, 68, 68, 0.15);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: radial-gradient(circle at 50% 20%, #1e1b4b 0%, var(--bg-base) 70%);
      color: var(--text-main);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1.5rem;
    }
    .login-container {
      width: 100%;
      max-width: 420px;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 2.5rem;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6), 0 0 40px var(--accent-glow);
    }
    .header { text-align: center; margin-bottom: 2rem; }
    .header h1 { font-size: 1.6rem; font-weight: 700; margin-bottom: 0.5rem; letter-spacing: -0.02em; }
    .header p { color: var(--text-muted); font-size: 0.88rem; }
    .form-group { margin-bottom: 1.25rem; }
    label { display: block; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 0.5rem; }
    input[type="email"], input[type="password"] {
      width: 100%;
      background: #0b0f19;
      border: 1px solid #374151;
      border-radius: 8px;
      padding: 0.75rem 1rem;
      color: var(--text-main);
      font-size: 0.95rem;
      transition: all 0.2s ease;
    }
    input[type="email"]:focus, input[type="password"]:focus {
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--accent-glow);
    }
    .btn-submit {
      width: 100%;
      background: linear-gradient(135deg, #2563eb 0%, #3b82f6 100%);
      color: #fff;
      border: none;
      border-radius: 8px;
      padding: 0.85rem;
      font-size: 1rem;
      font-weight: 600;
      cursor: pointer;
      transition: opacity 0.2s, transform 0.1s;
      margin-top: 0.5rem;
    }
    .btn-submit:hover { opacity: 0.95; }
    .btn-submit:active { transform: scale(0.98); }
    .alert-error {
      display: none;
      background: var(--danger-bg);
      border: 1px solid var(--danger);
      color: #fca5a5;
      padding: 0.75rem 1rem;
      border-radius: 8px;
      font-size: 0.85rem;
      margin-bottom: 1.25rem;
    }
    .badge {
      display: inline-block;
      padding: 0.25rem 0.6rem;
      background: rgba(59, 130, 246, 0.15);
      color: #60a5fa;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      margin-bottom: 0.75rem;
    }
  </style>
</head>
<body>
  <div class="login-container">
    <div class="header">
      <span class="badge">Operator Security Gate</span>
      <h1>Outbound Pipeline</h1>
      <p>Sign in to access campaign controls and dispatch logs</p>
    </div>

    <div id="error-alert" class="alert-error" role="alert"></div>

    <form id="login-form">
      <div class="form-group">
        <label for="email">Operator Email</label>
        <input type="email" id="email" name="email" required placeholder="operator@example.com" autocomplete="email">
      </div>
      <div class="form-group">
        <label for="password">Security Password</label>
        <input type="password" id="password" name="password" required placeholder="••••••••••••" autocomplete="current-password">
      </div>
      <button type="submit" class="btn-submit" id="submit-btn">Sign In</button>
    </form>
  </div>

  <script>
    const form = document.getElementById('login-form');
    const alertBox = document.getElementById('error-alert');
    const submitBtn = document.getElementById('submit-btn');

    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      alertBox.style.display = 'none';
      submitBtn.disabled = true;
      submitBtn.textContent = 'Verifying...';

      const email = document.getElementById('email').value.trim();
      const password = document.getElementById('password').value;

      try {
        const res = await fetch('/api/v1/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password })
        });

        const data = await res.json();
        if (res.ok) {
          window.location.href = '/dashboard';
        } else {
          alertBox.textContent = data.detail || data.error || 'Authentication failed.';
          alertBox.style.display = 'block';
        }
      } catch (err) {
        alertBox.textContent = 'Network or server error during sign in.';
        alertBox.style.display = 'block';
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Sign In';
      }
    });
  </script>
</body>
</html>"""


# =====================================================================
# 2. /dashboard
# =====================================================================
def get_dashboard_html() -> str:
    navbar = NAVBAR_TEMPLATE.format(
        active_dashboard="active",
        active_campaigns="",
        active_review="",
        active_deliveries="",
        active_profile="",
        active_settings="",
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dashboard - Outbound Pipeline Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    {SHARED_CSS}
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 1rem;
      margin-bottom: 2rem;
    }}
    .metric-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 1.25rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .metric-label {{ font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); font-weight: 600; }}
    .metric-value {{ font-size: 2rem; font-weight: 700; margin: 0.5rem 0 0.25rem 0; font-family: 'JetBrains Mono', monospace; }}
    .metric-card.attention-amber {{ border-color: rgba(245, 158, 11, 0.4); background: linear-gradient(180deg, rgba(245, 158, 11, 0.08) 0%, var(--card-bg) 100%); }}
    .metric-card.attention-purple {{ border-color: rgba(139, 92, 246, 0.4); background: linear-gradient(180deg, rgba(139, 92, 246, 0.08) 0%, var(--card-bg) 100%); }}
    .metric-card.attention-red {{ border-color: rgba(239, 68, 68, 0.4); background: linear-gradient(180deg, rgba(239, 68, 68, 0.08) 0%, var(--card-bg) 100%); }}
    .gauges-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 1.5rem;
      margin-bottom: 2rem;
    }}
    .gauge-bar-bg {{ background: #1f2937; height: 8px; border-radius: 9999px; overflow: hidden; margin: 0.75rem 0; }}
    .gauge-fill {{ height: 100%; border-radius: 9999px; transition: width 0.5s ease; }}
    .attention-tabs {{ display: flex; gap: 0.5rem; margin-bottom: 1rem; border-bottom: 1px solid var(--card-border); padding-bottom: 0.5rem; }}
    .tab-btn {{ background: transparent; border: none; color: var(--text-muted); padding: 0.5rem 1rem; font-size: 0.88rem; font-weight: 600; cursor: pointer; border-radius: 6px; }}
    .tab-btn.active {{ color: #60a5fa; background: rgba(59, 130, 246, 0.12); }}
    .attention-table td {{ font-size: 0.85rem; }}
    .empty-state {{ padding: 2.5rem; text-align: center; color: var(--text-muted); font-size: 0.9rem; }}
  </style>
</head>
<body>
  {navbar}

  <main class="main-content">
    <div class="page-header">
      <div>
        <h1 class="page-title"><span>🛰️</span> Operations Cockpit</h1>
        <p class="page-subtitle">Authoritative lead generation pipeline monitoring and dispatch queue</p>
      </div>
      <div style="display: flex; gap: 0.75rem;">
        <a href="/campaigns" class="btn btn-secondary btn-sm">+ New Campaign</a>
        <a href="/review" class="btn btn-warning btn-sm">Open Review Queue</a>
        <a href="/deliveries" class="btn btn-purple btn-sm">Inspect Deliveries</a>
      </div>
    </div>

    <!-- Live Authoritative Metric Summary Cards -->
    <div class="metrics-grid">
      <div class="metric-card">
        <span class="metric-label">Active Campaigns</span>
        <div class="metric-value" id="stat-campaigns">-</div>
        <span style="font-size:0.75rem; color:var(--text-dim)">Target outreach</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Discovered</span>
        <div class="metric-value" id="stat-discovered">-</div>
        <span style="font-size:0.75rem; color:var(--text-dim)">Candidate pool</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Selected</span>
        <div class="metric-value" id="stat-selected">-</div>
        <span style="font-size:0.75rem; color:var(--text-dim)">Ready/Enqueued</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Processing</span>
        <div class="metric-value" id="stat-processing">-</div>
        <span style="font-size:0.75rem; color:var(--text-dim)">Queued & running</span>
      </div>
      <div class="metric-card attention-amber">
        <span class="metric-label" style="color:#fbbf24">Waiting Review</span>
        <div class="metric-value" style="color:#fbbf24" id="stat-waiting-review">-</div>
        <span style="font-size:0.75rem; color:#f59e0b">Human action required</span>
      </div>
      <div class="metric-card attention-purple">
        <span class="metric-label" style="color:#c084fc">Waiting Delivery</span>
        <div class="metric-value" style="color:#c084fc" id="stat-waiting-delivery">-</div>
        <span style="font-size:0.75rem; color:#a855f7">Approved for dispatch</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Sent</span>
        <div class="metric-value" style="color:#34d399" id="stat-sent">-</div>
        <span style="font-size:0.75rem; color:var(--text-dim)">Live dispatches</span>
      </div>
      <div class="metric-card">
        <span class="metric-label">Staged</span>
        <div class="metric-value" style="color:#22d3ee" id="stat-staged">-</div>
        <span style="font-size:0.75rem; color:var(--text-dim)">Dry-run safe</span>
      </div>
      <div class="metric-card attention-red">
        <span class="metric-label" style="color:#fca5a5">Failed Runs</span>
        <div class="metric-value" style="color:#fca5a5" id="stat-failed">-</div>
        <span style="font-size:0.75rem; color:#ef4444">Needs audit</span>
      </div>
    </div>

    <!-- Volume Caps and Safety Invariant Gauges -->
    <div class="gauges-grid">
      <div class="card" style="margin-bottom:0">
        <div class="card-title">
          <span>Daily Volume Cap (Unified)</span>
          <span class="badge badge-green" id="daily-cap-status">Safe</span>
        </div>
        <div style="font-size: 1.6rem; font-weight: 700; font-family: 'JetBrains Mono', monospace;" id="daily-cap-text">0 / 10</div>
        <div class="gauge-bar-bg">
          <div class="gauge-fill" id="daily-cap-bar" style="width: 0%; background: #10b981;"></div>
        </div>
        <p style="font-size: 0.8rem; color: var(--text-muted);">Max 10 dispatches per rolling 24h window (CLI + Web unified dedupe).</p>
      </div>

      <div class="card" style="margin-bottom:0">
        <div class="card-title">
          <span>Weekly Volume Cap (Unified)</span>
          <span class="badge badge-blue" id="weekly-cap-status">Safe</span>
        </div>
        <div style="font-size: 1.6rem; font-weight: 700; font-family: 'JetBrains Mono', monospace;" id="weekly-cap-text">0 / 50</div>
        <div class="gauge-bar-bg">
          <div class="gauge-fill" id="weekly-cap-bar" style="width: 0%; background: #3b82f6;"></div>
        </div>
        <p style="font-size: 0.8rem; color: var(--text-muted);">Max 50 dispatches per rolling 7-day window across all channels.</p>
      </div>

      <div class="card" style="margin-bottom:0">
        <div class="card-title">
          <span>Server Dispatch Mode</span>
          <span class="badge badge-cyan" id="mode-badge">Dry-Run Staging</span>
        </div>
        <div style="font-size: 1.2rem; font-weight: 600; margin-top: 0.35rem;" id="mode-headline">Safe Staging Active</div>
        <p style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.75rem;">
          Emails stage safely to disk under <code>staged_deliveries/</code>. External email provider calls are strictly zero.
        </p>
      </div>
    </div>

    <!-- Actionable Needs Attention Section -->
    <div class="card" style="margin-top: 2rem;">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
        <h2 style="font-size: 1.1rem; font-weight: 700;">Needs Attention Queue</h2>
        <span class="badge badge-amber" id="attention-total-badge">0 items</span>
      </div>

      <div class="attention-tabs">
        <button class="tab-btn active" id="tab-review-btn" onclick="switchAttentionTab('review')">Waiting for Review (<span id="count-att-review">0</span>)</button>
        <button class="tab-btn" id="tab-delivery-btn" onclick="switchAttentionTab('delivery')">Waiting for Delivery (<span id="count-att-delivery">0</span>)</button>
        <button class="tab-btn" id="tab-failed-btn" onclick="switchAttentionTab('failed')">Failed Runs (<span id="count-att-failed">0</span>)</button>
      </div>

      <div id="attention-review-pane">
        <div class="table-container">
          <table class="attention-table">
            <thead>
              <tr>
                <th>Company</th>
                <th>Campaign</th>
                <th>Detail</th>
                <th>Enqueued</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="attention-review-tbody"></tbody>
          </table>
        </div>
      </div>

      <div id="attention-delivery-pane" style="display:none">
        <div class="table-container">
          <table class="attention-table">
            <thead>
              <tr>
                <th>Company</th>
                <th>Campaign</th>
                <th>Review State</th>
                <th>Approved Date</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="attention-delivery-tbody"></tbody>
          </table>
        </div>
      </div>

      <div id="attention-failed-pane" style="display:none">
        <div class="table-container">
          <table class="attention-table">
            <thead>
              <tr>
                <th>Company</th>
                <th>Campaign</th>
                <th>Failure Reason</th>
                <th>Timestamp</th>
                <th>Inspect</th>
              </tr>
            </thead>
            <tbody id="attention-failed-tbody"></tbody>
          </table>
        </div>
      </div>
    </div>
  </main>

  <div id="global-toast" class="toast"></div>

  <script>
    {SHARED_JS}

    let statsData = null;

    async function loadDashboard() {{
      const user = await checkAuth();
      if (!user) return;

      try {{
        const res = await fetch('/api/v1/dashboard/stats');
        if (!res.ok) throw new Error('Failed to load dashboard statistics');
        statsData = await res.json();

        // Populate metric counts
        document.getElementById('stat-campaigns').textContent = statsData.active_campaigns_count;
        document.getElementById('stat-discovered').textContent = statsData.companies_discovered_count;
        document.getElementById('stat-selected').textContent = statsData.companies_selected_count;
        document.getElementById('stat-processing').textContent = statsData.runs_processing_count;
        document.getElementById('stat-waiting-review').textContent = statsData.waiting_for_review_count;
        document.getElementById('stat-waiting-delivery').textContent = statsData.waiting_for_delivery_count;
        document.getElementById('stat-sent').textContent = statsData.sent_count;
        document.getElementById('stat-staged').textContent = statsData.staged_count;
        document.getElementById('stat-failed').textContent = statsData.failed_count;

        // Volume Caps
        const caps = statsData.volume_caps || {{}};
        const dayUsed = caps.sends_today || 0;
        const dayMax = caps.max_day || 10;
        const weekUsed = caps.sends_week || 0;
        const weekMax = caps.max_week || 50;

        document.getElementById('daily-cap-text').textContent = `${{dayUsed}} / ${{dayMax}}`;
        const dayPct = Math.min(100, Math.round((dayUsed / dayMax) * 100));
        const dayBar = document.getElementById('daily-cap-bar');
        dayBar.style.width = dayPct + '%';
        if (dayPct >= 100) {{
          dayBar.style.background = '#ef4444';
          document.getElementById('daily-cap-status').textContent = 'Cap Reached';
          document.getElementById('daily-cap-status').className = 'badge badge-red';
        }} else if (dayPct >= 80) {{
          dayBar.style.background = '#f59e0b';
          document.getElementById('daily-cap-status').textContent = 'Approaching Cap';
          document.getElementById('daily-cap-status').className = 'badge badge-amber';
        }}

        document.getElementById('weekly-cap-text').textContent = `${{weekUsed}} / ${{weekMax}}`;
        const weekPct = Math.min(100, Math.round((weekUsed / weekMax) * 100));
        const weekBar = document.getElementById('weekly-cap-bar');
        weekBar.style.width = weekPct + '%';
        if (weekPct >= 100) {{
          weekBar.style.background = '#ef4444';
          document.getElementById('weekly-cap-status').textContent = 'Cap Reached';
          document.getElementById('weekly-cap-status').className = 'badge badge-red';
        }}

        // Attention Counts
        const revItems = statsData.needs_attention?.waiting_for_review || [];
        const delItems = statsData.needs_attention?.waiting_for_delivery || [];
        const failItems = statsData.needs_attention?.failed_runs || [];

        document.getElementById('count-att-review').textContent = revItems.length;
        document.getElementById('count-att-delivery').textContent = delItems.length;
        document.getElementById('count-att-failed').textContent = failItems.length;
        document.getElementById('attention-total-badge').textContent = (revItems.length + delItems.length + failItems.length) + ' items';

        // Render Waiting for Review Table
        const revTbody = document.getElementById('attention-review-tbody');
        if (revItems.length === 0) {{
          revTbody.innerHTML = '<tr><td colspan="5" class="empty-state">No drafts currently waiting for human review.</td></tr>';
        }} else {{
          revTbody.innerHTML = revItems.map(item => `
            <tr>
              <td><strong>${{escapeHtml(item.company_name)}}</strong><br><span style="color:var(--text-muted);font-size:0.75rem">${{escapeHtml(item.domain)}}</span></td>
              <td>${{escapeHtml(item.campaign_name)}}</td>
              <td><span class="badge badge-blue">${{escapeHtml(item.detail)}}</span></td>
              <td style="color:var(--text-muted);font-size:0.8rem">${{item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : '-'}}</td>
              <td><a href="/review" class="btn btn-warning btn-sm">Review Draft</a></td>
            </tr>
          `).join('');
        }}

        // Render Waiting for Delivery Table
        const delTbody = document.getElementById('attention-delivery-tbody');
        if (delItems.length === 0) {{
          delTbody.innerHTML = '<tr><td colspan="5" class="empty-state">No approved runs waiting for delivery dispatch.</td></tr>';
        }} else {{
          delTbody.innerHTML = delItems.map(item => `
            <tr>
              <td><strong>${{escapeHtml(item.company_name)}}</strong><br><span style="color:var(--text-muted);font-size:0.75rem">${{escapeHtml(item.domain)}}</span></td>
              <td>${{escapeHtml(item.campaign_name)}}</td>
              <td><span class="badge badge-purple">Review Approved</span></td>
              <td style="color:var(--text-muted);font-size:0.8rem">${{item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : '-'}}</td>
              <td><button onclick="triggerDelivery('${{item.run_id}}', '${{escapeHtml(item.domain)}}')" class="btn btn-purple btn-sm">Deliver Outbound</button></td>
            </tr>
          `).join('');
        }}

        // Render Failed Runs Table
        const failTbody = document.getElementById('attention-failed-tbody');
        if (failItems.length === 0) {{
          failTbody.innerHTML = '<tr><td colspan="5" class="empty-state">No pipeline run failures reported.</td></tr>';
        }} else {{
          failTbody.innerHTML = failItems.map(item => `
            <tr>
              <td><strong>${{escapeHtml(item.company_name)}}</strong><br><span style="color:var(--text-muted);font-size:0.75rem">${{escapeHtml(item.domain)}}</span></td>
              <td>${{escapeHtml(item.campaign_name)}}</td>
              <td><span class="badge badge-red" title="${{escapeHtml(item.detail)}}">${{escapeHtml((item.detail || '').slice(0, 45))}}...</span></td>
              <td style="color:var(--text-muted);font-size:0.8rem">${{item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : '-'}}</td>
              <td><a href="/campaigns/${{item.campaign_id}}" class="btn btn-secondary btn-sm">Inspect Campaign</a></td>
            </tr>
          `).join('');
        }}

      }} catch (err) {{
        showToast('Error loading cockpit data: ' + err.message, true);
      }}
    }}

    function switchAttentionTab(tab) {{
      document.getElementById('tab-review-btn').className = 'tab-btn' + (tab === 'review' ? ' active' : '');
      document.getElementById('tab-delivery-btn').className = 'tab-btn' + (tab === 'delivery' ? ' active' : '');
      document.getElementById('tab-failed-btn').className = 'tab-btn' + (tab === 'failed' ? ' active' : '');

      document.getElementById('attention-review-pane').style.display = tab === 'review' ? 'block' : 'none';
      document.getElementById('attention-delivery-pane').style.display = tab === 'delivery' ? 'block' : 'none';
      document.getElementById('attention-failed-pane').style.display = tab === 'failed' ? 'block' : 'none';
    }}

    async function triggerDelivery(runId, domain) {{
      if (!confirm(`Execute authoritative delivery for ${{domain}}?\\n\\nThis will run through all 11 server safety gates and stage to disk or live send based on server configuration.`)) {{
        return;
      }}

      try {{
        const res = await fetch(`/api/v1/deliveries/${{runId}}`, {{ method: 'POST' }});
        const data = await res.json();
        if (res.ok) {{
          showToast(`Delivery completed: ${{data.delivery_status}} (${{data.delivery_mode}})`);
          await loadDashboard();
        }} else {{
          showToast(data.detail || data.error || 'Delivery rejected by safety gate', true);
        }}
      }} catch (e) {{
        showToast('Delivery request failed: ' + e.message, true);
      }}
    }}

    document.addEventListener('DOMContentLoaded', loadDashboard);
  </script>
</body>
</html>"""


# =====================================================================
# 3. /campaigns
# =====================================================================
def get_campaigns_html() -> str:
    navbar = NAVBAR_TEMPLATE.format(
        active_dashboard="",
        active_campaigns="active",
        active_review="",
        active_deliveries="",
        active_profile="",
        active_settings="",
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Campaigns - Outbound Pipeline Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    {SHARED_CSS}
    .campaigns-table td {{ vertical-align: middle; }}
    .stats-pill-group {{ display: flex; gap: 0.35rem; font-size: 0.75rem; flex-wrap: wrap; }}
  </style>
</head>
<body>
  {navbar}

  <main class="main-content">
    <div class="page-header">
      <div>
        <h1 class="page-title"><span>🎯</span> Outreach Campaigns</h1>
        <p class="page-subtitle">Configure ICP targeting, candidate discovery filters, and execution parameters</p>
      </div>
      <button class="btn btn-primary" onclick="openCreateModal()">+ Create Campaign</button>
    </div>

    <div class="card">
      <div class="table-container">
        <table class="campaigns-table">
          <thead>
            <tr>
              <th>Campaign Name</th>
              <th>Status</th>
              <th>Target Geography & Industry</th>
              <th>Size / Stage</th>
              <th>Pipeline Progress</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="campaigns-tbody">
            <tr><td colspan="6" class="empty-state">Loading campaigns...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </main>

  <!-- Create Campaign Modal -->
  <div class="modal-backdrop" id="create-modal">
    <div class="modal">
      <h2 class="modal-title">Create Outreach Campaign</h2>
      <p class="modal-subtitle">Define candidate targeting criteria and link candidate resume highlights</p>

      <form id="create-campaign-form">
        <div class="form-group">
          <label for="c-name">Campaign Name *</label>
          <input type="text" id="c-name" required placeholder="e.g. India Cybersecurity Startups — Q3">
        </div>
        <div class="form-group">
          <label for="c-objective">Outreach Objective *</label>
          <textarea id="c-objective" rows="2" required placeholder="Describe the purpose of this outreach campaign..."></textarea>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
          <div class="form-group">
            <label for="c-geography">Target Geography</label>
            <input type="text" id="c-geography" value="India">
          </div>
          <div class="form-group">
            <label for="c-industry">Industry</label>
            <input type="text" id="c-industry" value="Cybersecurity">
          </div>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
          <div class="form-group">
            <label for="c-size">Company Size</label>
            <select id="c-size">
              <option value="small" selected>Small (Seed - Early)</option>
              <option value="established">Established</option>
              <option value="any">Any Size</option>
            </select>
          </div>
          <div class="form-group">
            <label for="c-stage">Company Stage</label>
            <input type="text" id="c-stage" value="Seed / Early-Stage">
          </div>
        </div>
        <div class="form-group">
          <label for="c-roles">Target Roles (comma-separated)</label>
          <input type="text" id="c-roles" value="CISO, VP Security, Head of Engineering, CTO">
        </div>
        <div class="form-group">
          <label for="c-tech">Technologies (comma-separated)</label>
          <input type="text" id="c-tech" value="Python, Cloud Security, AWS, Kubernetes">
        </div>
        <div class="form-group">
          <label for="c-resume">Linked Resume Profile</label>
          <select id="c-resume">
            <option value="">-- No Resume Linked (Default Persona) --</option>
          </select>
        </div>

        <div class="modal-actions">
          <button type="button" class="btn btn-secondary" onclick="closeCreateModal()">Cancel</button>
          <button type="submit" class="btn btn-primary" id="save-campaign-btn">Create Campaign</button>
        </div>
      </form>
    </div>
  </div>

  <div id="global-toast" class="toast"></div>

  <script>
    {SHARED_JS}

    async function loadCampaigns() {{
      const user = await checkAuth();
      if (!user) return;

      try {{
        const res = await fetch('/api/v1/campaigns');
        if (!res.ok) throw new Error('Failed to load campaigns');
        const campaigns = await res.json();
        const tbody = document.getElementById('campaigns-tbody');

        if (campaigns.length === 0) {{
          tbody.innerHTML = `
            <tr>
              <td colspan="6" class="empty-state">
                No campaigns created yet.<br><br>
                <button class="btn btn-primary btn-sm" onclick="openCreateModal()">Create Your First Campaign</button>
              </td>
            </tr>
          `;
          return;
        }}

        tbody.innerHTML = campaigns.map(c => `
          <tr>
            <td>
              <a href="/campaigns/${{c.id}}" style="font-weight:700; font-size:0.95rem; color:#fff;">${{escapeHtml(c.name)}}</a>
              <div style="font-size:0.75rem; color:var(--text-muted); margin-top:0.2rem;">${{escapeHtml((c.objective || '').slice(0, 50))}}...</div>
            </td>
            <td><span class="badge badge-${{c.status === 'active' ? 'green' : 'blue'}}">${{escapeHtml(c.status)}}</span></td>
            <td>
              <div>${{escapeHtml(c.target_geography)}}</div>
              <span class="badge badge-gray" style="margin-top:0.25rem">${{escapeHtml(c.industry)}}</span>
            </td>
            <td>
              <div>${{escapeHtml(c.company_size)}}</div>
              <span style="font-size:0.75rem; color:var(--text-muted)">${{escapeHtml(c.company_stage)}}</span>
            </td>
            <td>
              <div class="stats-pill-group">
                <span class="badge badge-gray" title="Discovered Companies">${{c.total_companies || 0}} comps</span>
                <span class="badge badge-blue" title="Selected Companies">${{c.selected_companies || 0}} sel</span>
                <span class="badge badge-amber" title="Waiting Review">${{c.waiting_for_review_count || 0}} rev</span>
                <span class="badge badge-purple" title="Waiting Delivery">${{c.waiting_for_delivery_count || 0}} del</span>
                <span class="badge badge-green" title="Delivered Sent">${{c.sent_count || 0}} sent</span>
              </div>
            </td>
            <td>
              <a href="/campaigns/${{c.id}}" class="btn btn-secondary btn-sm">Open Console &rarr;</a>
            </td>
          </tr>
        `).join('');
      }} catch (err) {{
        showToast('Error: ' + err.message, true);
      }}
    }}

    async function loadResumesForSelect() {{
      try {{
        const res = await fetch('/api/v1/resumes');
        if (!res.ok) return;
        const resumes = await res.json();
        const select = document.getElementById('c-resume');
        select.innerHTML = '<option value="">-- No Resume Linked (Default Persona) --</option>' +
          resumes.map(r => `<option value="${{r.id}}">${{escapeHtml(r.filename)}} (${{r.is_active ? 'Active' : r.parsing_status}})</option>`).join('');
      }} catch (e) {{}}
    }}

    function openCreateModal() {{
      loadResumesForSelect();
      document.getElementById('create-modal').style.display = 'flex';
      document.getElementById('c-name').focus();
    }}

    function closeCreateModal() {{
      document.getElementById('create-modal').style.display = 'none';
      document.getElementById('create-campaign-form').reset();
    }}

    document.getElementById('create-campaign-form').addEventListener('submit', async (e) => {{
      e.preventDefault();
      const saveBtn = document.getElementById('save-campaign-btn');
      saveBtn.disabled = true;
      saveBtn.textContent = 'Creating...';

      const payload = {{
        name: document.getElementById('c-name').value.trim(),
        objective: document.getElementById('c-objective').value.trim(),
        target_geography: document.getElementById('c-geography').value.trim(),
        industry: document.getElementById('c-industry').value.trim(),
        company_size: document.getElementById('c-size').value,
        company_stage: document.getElementById('c-stage').value.trim(),
        target_roles: document.getElementById('c-roles').value.split(',').map(s => s.trim()).filter(Boolean),
        technologies: document.getElementById('c-tech').value.split(',').map(s => s.trim()).filter(Boolean),
        resume_id: document.getElementById('c-resume').value || null,
      }};

      try {{
        const res = await fetch('/api/v1/campaigns', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(payload)
        }});

        if (res.ok) {{
          const camp = await res.json();
          closeCreateModal();
          showToast('Campaign created successfully!');
          window.location.href = `/campaigns/${{camp.id}}`;
        }} else {{
          const err = await res.json();
          showToast(err.detail || 'Failed to create campaign', true);
        }}
      }} catch (err) {{
        showToast('Network error creating campaign', true);
      }} finally {{
        saveBtn.disabled = false;
        saveBtn.textContent = 'Create Campaign';
      }}
    }});

    document.addEventListener('DOMContentLoaded', loadCampaigns);
  </script>
</body>
</html>"""


# =====================================================================
# 4. /campaigns/{id}
# =====================================================================
def get_campaign_detail_html() -> str:
    navbar = NAVBAR_TEMPLATE.format(
        active_dashboard="",
        active_campaigns="active",
        active_review="",
        active_deliveries="",
        active_profile="",
        active_settings="",
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Campaign Console - Outbound Pipeline</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    {SHARED_CSS}
    .targeting-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1rem;
      background: #0d1322;
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 1rem;
      margin-bottom: 1.5rem;
    }}
    .targeting-item-label {{ font-size: 0.72rem; text-transform: uppercase; color: var(--text-muted); font-weight: 600; }}
    .targeting-item-val {{ font-size: 0.88rem; color: #fff; font-weight: 500; margin-top: 0.25rem; }}
    .toolbar {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 0.75rem; }}
    .filters-group {{ display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }}
    .selection-banner {{
      background: rgba(59, 130, 246, 0.1);
      border: 1px solid rgba(59, 130, 246, 0.25);
      border-radius: 8px;
      padding: 0.85rem 1.25rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1rem;
    }}
    .tag-pill {{
      display: inline-block;
      background: #1e293b;
      color: #94a3b8;
      border-radius: 4px;
      padding: 0.15rem 0.4rem;
      font-size: 0.7rem;
      margin: 0.1rem;
    }}
    .timeline-item {{
      position: relative;
      padding-left: 1.5rem;
      padding-bottom: 1.25rem;
      border-left: 2px solid #2d3748;
    }}
    .timeline-item:last-child {{ border-left: 2px solid transparent; padding-bottom: 0; }}
    .timeline-dot {{
      position: absolute;
      left: -6px;
      top: 2px;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--accent);
    }}
  </style>
</head>
<body>
  {navbar}

  <main class="main-content">
    <div style="margin-bottom: 1rem;">
      <a href="/campaigns" style="color:var(--text-muted); font-size:0.85rem;">&larr; Back to Campaigns</a>
    </div>

    <div class="page-header">
      <div>
        <div style="display:flex; align-items:center; gap: 0.75rem;">
          <h1 class="page-title" id="campaign-title">Loading Campaign...</h1>
          <span class="badge badge-blue" id="campaign-status-badge">draft</span>
        </div>
        <p class="page-subtitle" id="campaign-desc">-</p>
      </div>
      <div style="display:flex; gap:0.5rem; align-items:center;">
        <select id="discovery-limit" style="width: auto; padding: 0.5rem 0.75rem;">
          <option value="5">Discover 5</option>
          <option value="10" selected>Discover 10</option>
          <option value="20">Discover 20</option>
        </select>
        <button class="btn btn-primary" id="run-discover-btn" onclick="triggerDiscovery()">⚡ Run Discovery</button>
      </div>
    </div>

    <!-- Targeting Summary Card -->
    <div class="targeting-grid">
      <div>
        <span class="targeting-item-label">Target Geography</span>
        <div class="targeting-item-val" id="tg-geo">-</div>
      </div>
      <div>
        <span class="targeting-item-label">Industry</span>
        <div class="targeting-item-val" id="tg-ind">-</div>
      </div>
      <div>
        <span class="targeting-item-label">Company Size</span>
        <div class="targeting-item-val" id="tg-size">-</div>
      </div>
      <div>
        <span class="targeting-item-label">Stage</span>
        <div class="targeting-item-val" id="tg-stage">-</div>
      </div>
      <div>
        <span class="targeting-item-label">Target Roles</span>
        <div class="targeting-item-val" id="tg-roles">-</div>
      </div>
    </div>

    <!-- Selection & Enqueue Banner -->
    <div class="selection-banner" id="enqueue-banner">
      <div>
        <strong id="selected-summary-text">0 companies selected</strong>
        <p style="font-size: 0.78rem; color: var(--text-muted); margin-top: 0.2rem;">
          Enqueuing submits selected companies for background research, email resolution, and draft generation. Emails are NOT sent at this stage.
        </p>
      </div>
      <div style="display:flex; gap:0.5rem;">
        <button class="btn btn-secondary btn-sm" onclick="saveCurrentSelection()">Save Selection</button>
        <button class="btn btn-success btn-sm" id="enqueue-btn" onclick="enqueueSelectedRuns()">Enqueue Selected Companies &rarr;</button>
      </div>
    </div>

    <!-- Candidate Discovery Table Section -->
    <div class="card">
      <div class="card-title">
        <span>Candidate Discovery Grid (Deterministic 100-Point Ranking)</span>
        <span id="comps-count-badge" class="badge badge-gray">0 candidates</span>
      </div>

      <div class="toolbar">
        <div class="filters-group">
          <input type="text" id="filter-search" placeholder="Search domain or company..." style="width: 220px;" oninput="applyFilters()">
          <select id="filter-status" onchange="applyFilters()" style="width: auto;">
            <option value="">All Statuses</option>
            <option value="discovered">Discovered</option>
            <option value="selected">Selected</option>
            <option value="contacted">Already Contacted</option>
          </select>
          <select id="filter-score" onchange="applyFilters()" style="width: auto;">
            <option value="">All Scores</option>
            <option value="80">Score &ge; 80</option>
            <option value="70">Score &ge; 70</option>
            <option value="60">Score &ge; 60</option>
          </select>
        </div>
        <div style="display:flex; gap:0.5rem;">
          <button class="btn btn-secondary btn-sm" onclick="selectAllFiltered(true)">Select All Visible</button>
          <button class="btn btn-secondary btn-sm" onclick="selectAllFiltered(false)">Deselect All</button>
        </div>
      </div>

      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th style="width: 40px;"><input type="checkbox" id="master-checkbox" onchange="toggleMasterCheckbox(this)"></th>
              <th>Company / Domain</th>
              <th>Location</th>
              <th>Industry / Stage</th>
              <th>Size</th>
              <th>Match Score</th>
              <th>Signals</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody id="candidates-tbody">
            <tr><td colspan="8" class="empty-state">No candidates discovered yet. Click <strong>Run Discovery</strong> above to find target companies.</td></tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Pipeline Runs Progress Section -->
    <div class="card" style="margin-top: 2rem;">
      <div class="card-title">
        <span>Pipeline Execution Runs</span>
        <span id="runs-count-badge" class="badge badge-purple">0 runs</span>
      </div>

      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Run Status</th>
              <th>Last Stage</th>
              <th>Started</th>
              <th>Completed</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="runs-tbody">
            <tr><td colspan="6" class="empty-state">No execution runs enqueued yet. Select candidates above and click Enqueue.</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </main>

  <!-- Run Inspection Modal -->
  <div class="modal-backdrop" id="run-modal">
    <div class="modal" style="max-width: 750px;">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom: 1rem;">
        <div>
          <h2 class="modal-title" id="m-run-company">Run Detail</h2>
          <p class="modal-subtitle" id="m-run-id" style="font-family:'JetBrains Mono',monospace; font-size:0.75rem; margin-bottom:0;"></p>
        </div>
        <span class="badge" id="m-run-status-badge">-</span>
      </div>

      <!-- Stage & Contact Summary -->
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:1rem; background:#0b0f19; padding:1rem; border-radius:8px; margin-bottom:1.5rem;">
        <div>
          <span class="targeting-item-label">Verified Contact</span>
          <div style="font-weight:600; font-size:0.9rem; color:#fff;" id="m-run-person">Searching...</div>
          <div style="font-size:0.75rem; color:#60a5fa;" id="m-run-email">-</div>
        </div>
        <div>
          <span class="targeting-item-label">Review / Delivery</span>
          <div style="font-weight:600; font-size:0.9rem; color:#fff;" id="m-run-review">Pending Review</div>
          <div style="font-size:0.75rem; color:#34d399;" id="m-run-delivery">-</div>
        </div>
      </div>

      <!-- Draft Preview if available -->
      <div id="m-run-draft-section" style="margin-bottom:1.5rem; display:none;">
        <span class="targeting-item-label">Generated Outreach Draft</span>
        <div style="background:#090d16; border:1px solid #374151; border-radius:8px; padding:1rem; margin-top:0.4rem;">
          <div style="font-weight:600; margin-bottom:0.5rem; font-size:0.85rem;" id="m-draft-subject"></div>
          <div style="font-size:0.8rem; color:#d1d5db; line-height:1.5; white-space:pre-wrap;" id="m-draft-body"></div>
        </div>
      </div>

      <!-- Audit Timeline -->
      <span class="targeting-item-label">Audit Event Timeline</span>
      <div id="m-run-events" style="margin-top:0.75rem; max-height:220px; overflow-y:auto; padding-right:0.5rem;"></div>

      <div class="modal-actions">
        <button class="btn btn-secondary" onclick="closeRunModal()">Close</button>
      </div>
    </div>
  </div>

  <div id="global-toast" class="toast"></div>

  <script>
    {SHARED_JS}

    const campaignId = window.location.pathname.split('/')[2];
    let allCompanies = [];
    let selectedIds = new Set();

    async function loadCampaign() {{
      const user = await checkAuth();
      if (!user) return;

      try {{
        const res = await fetch(`/api/v1/campaigns/${{campaignId}}`);
        if (!res.ok) throw new Error('Failed to load campaign');
        const camp = await res.json();

        document.getElementById('campaign-title').textContent = camp.name;
        document.getElementById('campaign-status-badge').textContent = camp.status;
        document.getElementById('campaign-desc').textContent = camp.objective;
        document.getElementById('tg-geo').textContent = camp.target_geography;
        document.getElementById('tg-ind').textContent = camp.industry;
        document.getElementById('tg-size').textContent = camp.company_size;
        document.getElementById('tg-stage').textContent = camp.company_stage;
        document.getElementById('tg-roles').textContent = (camp.target_roles || []).join(', ') || 'Default';

        await loadCompanies();
        await loadRuns();
      }} catch (err) {{
        showToast('Error: ' + err.message, true);
      }}
    }}

    async function loadCompanies() {{
      try {{
        const res = await fetch(`/api/v1/campaigns/${{campaignId}}/companies`);
        if (!res.ok) return;
        allCompanies = await res.json();
        document.getElementById('comps-count-badge').textContent = allCompanies.length + ' candidates';

        // Pre-populate selection set
        allCompanies.forEach(c => {{
          if (c.selection_status === 'selected') selectedIds.add(c.id);
        }});
        updateSelectedBanner();
        renderCompanies(allCompanies);
      }} catch (e) {{}}
    }}

    function renderCompanies(comps) {{
      const tbody = document.getElementById('candidates-tbody');
      if (comps.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No matching candidate companies.</td></tr>';
        return;
      }}

      tbody.innerHTML = comps.map(c => {{
        const isContacted = c.selection_status === 'contacted';
        const isChecked = selectedIds.has(c.id);
        const score = c.match_score || 0;
        let scoreClass = 'badge-gray';
        if (score >= 80) scoreClass = 'badge-green';
        else if (score >= 60) scoreClass = 'badge-blue';
        else if (score > 0) scoreClass = 'badge-amber';

        const signals = (c.technical_signals || []).concat(c.why_match || []).slice(0, 3);

        return `
          <tr style="${{isContacted ? 'opacity:0.6' : ''}}">
            <td>
              <input type="checkbox" value="${{c.id}}"
                ${{isChecked ? 'checked' : ''}}
                ${{isContacted ? 'disabled title="Already contacted"' : ''}}
                onchange="toggleCompanySelect('${{c.id}}', this.checked)">
            </td>
            <td>
              <strong>${{escapeHtml(c.company_name)}}</strong><br>
              <a href="https://${{encodeURIComponent(c.domain)}}" target="_blank" rel="noopener noreferrer" style="font-size:0.75rem; color:#60a5fa;">${{escapeHtml(c.domain)}} &nearr;</a>
            </td>
            <td style="font-size:0.8rem">${{escapeHtml(c.location || 'Remote')}}</td>
            <td>
              <span class="badge badge-gray">${{escapeHtml(c.industry || 'Tech')}}</span><br>
              <span style="font-size:0.75rem; color:var(--text-muted)">${{escapeHtml(c.stage || '-')}}</span>
            </td>
            <td style="font-size:0.8rem">${{c.size || '-'}}</td>
            <td><span class="badge ${{scoreClass}}">${{score}}/100</span></td>
            <td>${{signals.map(s => `<span class="tag-pill">${{escapeHtml(s)}}</span>`).join('')}}</td>
            <td>
              <span class="badge badge-${{isContacted ? 'cyan' : (isChecked ? 'blue' : 'gray')}}">
                ${{escapeHtml(c.selection_status)}}
              </span>
            </td>
          </tr>
        `;
      }}).join('');
    }}

    function applyFilters() {{
      const q = document.getElementById('filter-search').value.toLowerCase();
      const statusFilter = document.getElementById('filter-status').value.toLowerCase();
      const minScore = parseInt(document.getElementById('filter-score').value || '0', 10);

      const filtered = allCompanies.filter(c => {{
        if (q && !c.company_name.toLowerCase().includes(q) && !c.domain.toLowerCase().includes(q)) return false;
        if (statusFilter && c.selection_status.toLowerCase() !== statusFilter) return false;
        if (minScore && (c.match_score || 0) < minScore) return false;
        return true;
      }});

      renderCompanies(filtered);
    }}

    function toggleCompanySelect(id, checked) {{
      if (checked) selectedIds.add(id);
      else selectedIds.delete(id);
      updateSelectedBanner();
    }}

    function toggleMasterCheckbox(master) {{
      const checkboxes = document.querySelectorAll('#candidates-tbody input[type="checkbox"]:not(:disabled)');
      checkboxes.forEach(cb => {{
        cb.checked = master.checked;
        if (master.checked) selectedIds.add(cb.value);
        else selectedIds.delete(cb.value);
      }});
      updateSelectedBanner();
    }}

    function selectAllFiltered(selectVal) {{
      const checkboxes = document.querySelectorAll('#candidates-tbody input[type="checkbox"]:not(:disabled)');
      checkboxes.forEach(cb => {{
        cb.checked = selectVal;
        if (selectVal) selectedIds.add(cb.value);
        else selectedIds.delete(cb.value);
      }});
      updateSelectedBanner();
    }}

    function updateSelectedBanner() {{
      const count = selectedIds.size;
      document.getElementById('selected-summary-text').textContent = `${{count}} companies selected`;
      const btn = document.getElementById('enqueue-btn');
      btn.disabled = count === 0;
    }}

    async function saveCurrentSelection() {{
      const ids = Array.from(selectedIds);
      if (ids.length === 0) {{
        showToast('No companies selected to save', true);
        return;
      }}

      try {{
        const res = await fetch(`/api/v1/campaigns/${{campaignId}}/companies/select`, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ company_ids: ids }})
        }});

        if (res.ok) {{
          showToast(`Saved ${{ids.length}} selected companies!`);
          await loadCompanies();
        }} else {{
          const err = await res.json();
          showToast(err.detail || 'Failed to save selection', true);
        }}
      }} catch (e) {{
        showToast('Network error saving selection', true);
      }}
    }}

    async function triggerDiscovery() {{
      const limit = parseInt(document.getElementById('discovery-limit').value, 10);
      const btn = document.getElementById('run-discover-btn');
      btn.disabled = true;
      btn.textContent = 'Discovering...';

      try {{
        const res = await fetch(`/api/v1/campaigns/${{campaignId}}/discover?limit=${{limit}}`, {{ method: 'POST' }});
        const data = await res.json();
        if (res.ok) {{
          showToast(`Discovered ${{data.discovered_count}} new candidate companies!`);
          await loadCompanies();
        }} else {{
          showToast(data.detail || 'Discovery failed', true);
        }}
      }} catch (e) {{
        showToast('Discovery network error: ' + e.message, true);
      }} finally {{
        btn.disabled = false;
        btn.textContent = '⚡ Run Discovery';
      }}
    }}

    async function enqueueSelectedRuns() {{
      if (selectedIds.size === 0) return;
      if (!confirm(`Enqueue ${{selectedIds.size}} selected companies for background pipeline processing?\\n\\nThis will run leader research, email resolution, and draft generation. (Emails are NOT dispatched without human review and explicit delivery).`)) {{
        return;
      }}

      // Ensure selection is persisted first
      await saveCurrentSelection();

      try {{
        const res = await fetch(`/api/v1/campaigns/${{campaignId}}/enqueue-selected`, {{ method: 'POST' }});
        const data = await res.json();
        if (res.ok) {{
          showToast(`Enqueued ${{data.enqueued_count}} runs for execution!`);
          await loadCompanies();
          await loadRuns();
        }} else {{
          showToast(data.detail || 'Failed to enqueue', true);
        }}
      }} catch (e) {{
        showToast('Enqueue network error', true);
      }}
    }}

    async function loadRuns() {{
      try {{
        const res = await fetch(`/api/v1/campaigns/${{campaignId}}/runs`);
        if (!res.ok) return;
        const runs = await res.json();
        document.getElementById('runs-count-badge').textContent = runs.length + ' runs';
        const tbody = document.getElementById('runs-tbody');

        if (runs.length === 0) {{
          tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No execution runs enqueued yet. Select candidates above and click Enqueue.</td></tr>';
          return;
        }}

        tbody.innerHTML = runs.map(r => {{
          let badgeClass = 'badge-gray';
          let actionBtn = `<button onclick="inspectRun('${{r.id}}')" class="btn btn-secondary btn-sm">Inspect</button>`;

          if (r.status === 'queued') badgeClass = 'badge-gray';
          else if (r.status === 'running') badgeClass = 'badge-blue';
          else if (r.status === 'waiting_for_review') {{
            badgeClass = 'badge-amber';
            actionBtn = `<a href="/review" class="btn btn-warning btn-sm">Review Now</a> <button onclick="inspectRun('${{r.id}}')" class="btn btn-secondary btn-sm">Inspect</button>`;
          }} else if (r.status === 'waiting_for_delivery') {{
            badgeClass = 'badge-purple';
            actionBtn = `<button onclick="triggerDeliveryFromRun('${{r.id}}', '${{escapeHtml(r.domain)}}')" class="btn btn-purple btn-sm">Deliver</button> <button onclick="inspectRun('${{r.id}}')" class="btn btn-secondary btn-sm">Inspect</button>`;
          }} else if (r.status === 'completed') badgeClass = 'badge-green';
          else if (r.status === 'failed') badgeClass = 'badge-red';

          return `
            <tr>
              <td>
                <strong>${{escapeHtml(r.company_name || r.domain)}}</strong><br>
                <span style="font-size:0.75rem; color:var(--text-muted)">${{escapeHtml(r.domain)}}</span>
              </td>
              <td><span class="badge ${{badgeClass}}">${{escapeHtml(r.status)}}</span></td>
              <td style="font-size:0.8rem">${{escapeHtml(r.last_completed_stage || 'queued')}}</td>
              <td style="font-size:0.8rem; color:var(--text-muted)">${{r.started_at ? new Date(r.started_at).toLocaleTimeString() : '-'}}</td>
              <td style="font-size:0.8rem; color:var(--text-muted)">${{r.completed_at ? new Date(r.completed_at).toLocaleTimeString() : '-'}}</td>
              <td><div style="display:flex; gap:0.4rem;">${{actionBtn}}</div></td>
            </tr>
          `;
        }}).join('');
      }} catch (e) {{}}
    }}

    async function triggerDeliveryFromRun(runId, domain) {{
      if (!confirm(`Execute authoritative delivery for ${{domain}}?`)) return;
      try {{
        const res = await fetch(`/api/v1/deliveries/${{runId}}`, {{ method: 'POST' }});
        const data = await res.json();
        if (res.ok) {{
          showToast(`Delivery completed: ${{data.delivery_status}}`);
          await loadRuns();
        }} else {{
          showToast(data.detail || 'Delivery failed', true);
        }}
      }} catch (e) {{
        showToast('Error: ' + e.message, true);
      }}
    }}

    async function inspectRun(runId) {{
      try {{
        const res = await fetch(`/api/v1/campaigns/${{campaignId}}/runs/${{runId}}`);
        if (!res.ok) throw new Error('Could not load run detail');
        const data = await res.json();

        document.getElementById('m-run-company').textContent = data.company_name || data.domain;
        document.getElementById('m-run-id').textContent = 'ID: ' + data.id;
        document.getElementById('m-run-status-badge').textContent = data.status;
        document.getElementById('m-run-status-badge').className = 'badge ' + (data.status === 'waiting_for_review' ? 'badge-amber' : (data.status === 'completed' ? 'badge-green' : 'badge-blue'));

        if (data.person) {{
          document.getElementById('m-run-person').textContent = `${{data.person.full_name}} (${{data.person.role}})`;
        }} else {{
          document.getElementById('m-run-person').textContent = 'No leader verified';
        }}

        if (data.contact) {{
          document.getElementById('m-run-email').textContent = `${{data.contact.email || 'None'}} [${{data.contact.verification_status}}]`;
        }} else {{
          document.getElementById('m-run-email').textContent = 'No email resolved';
        }}

        if (data.review) {{
          document.getElementById('m-run-review').textContent = `Review: ${{data.review.status}}`;
        }} else {{
          document.getElementById('m-run-review').textContent = 'Review not reached';
        }}

        if (data.delivery) {{
          document.getElementById('m-run-delivery').textContent = `Delivery: ${{data.delivery.delivery_status}} (${{data.delivery.delivery_mode}})`;
        }} else {{
          document.getElementById('m-run-delivery').textContent = 'Delivery not triggered';
        }}

        // Draft
        if (data.draft) {{
          document.getElementById('m-run-draft-section').style.display = 'block';
          document.getElementById('m-draft-subject').textContent = 'Subject: ' + data.draft.subject;
          document.getElementById('m-draft-body').textContent = data.draft.body;
        }} else {{
          document.getElementById('m-run-draft-section').style.display = 'none';
        }}

        // Events
        const eventsEl = document.getElementById('m-run-events');
        if (!data.events || data.events.length === 0) {{
          eventsEl.innerHTML = '<p style="color:var(--text-muted);font-size:0.8rem">No events logged yet.</p>';
        }} else {{
          eventsEl.innerHTML = data.events.map(ev => `
            <div class="timeline-item">
              <div class="timeline-dot"></div>
              <div style="font-size:0.75rem; color:#60a5fa; font-weight:600;">${{escapeHtml(ev.event_type)}} &bull; ${{new Date(ev.created_at).toLocaleTimeString()}}</div>
              <div style="font-size:0.8rem; color:#d1d5db; margin-top:0.2rem;">${{escapeHtml(ev.message)}}</div>
            </div>
          `).join('');
        }}

        document.getElementById('run-modal').style.display = 'flex';
      }} catch (err) {{
        showToast('Error inspecting run: ' + err.message, true);
      }}
    }}

    function closeRunModal() {{
      document.getElementById('run-modal').style.display = 'none';
    }}

    document.addEventListener('DOMContentLoaded', loadCampaign);
  </script>
</body>
</html>"""


# =====================================================================
# 5. /review
# =====================================================================
def get_review_html() -> str:
    navbar = NAVBAR_TEMPLATE.format(
        active_dashboard="",
        active_campaigns="",
        active_review="active",
        active_deliveries="",
        active_profile="",
        active_settings="",
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Review Cockpit - Outbound Pipeline Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    {SHARED_CSS}
    .cockpit-container {{
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 1.5rem;
      align-items: start;
    }}
    .queue-sidebar {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      max-height: calc(100vh - 120px);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .queue-header {{
      padding: 1rem;
      border-bottom: 1px solid var(--card-border);
      background: #131b2e;
    }}
    .queue-list {{
      overflow-y: auto;
      flex: 1;
    }}
    .queue-item {{
      padding: 0.85rem 1rem;
      border-bottom: 1px solid #1a2333;
      cursor: pointer;
      transition: all 0.15s;
    }}
    .queue-item:hover {{ background: rgba(30, 41, 59, 0.5); }}
    .queue-item.active {{
      background: rgba(59, 130, 246, 0.15);
      border-left: 3px solid var(--accent);
    }}
    .editor-section textarea {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.88rem;
      line-height: 1.6;
    }}
    .review-action-banner {{
      background: rgba(16, 185, 129, 0.1);
      border: 1px solid rgba(16, 185, 129, 0.25);
      border-radius: 8px;
      padding: 1rem 1.25rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1.5rem;
    }}
  </style>
</head>
<body>
  {navbar}

  <main class="main-content">
    <div class="page-header" style="margin-bottom: 1rem;">
      <div>
        <h1 class="page-title"><span>🛡️</span> Human Review Cockpit</h1>
        <p class="page-subtitle">Inspect intelligence signals, edit drafts with authoritative human persistence, and authorize staged delivery</p>
      </div>
      <div style="display: flex; gap: 0.5rem; align-items: center;">
        <select id="review-filter-status" onchange="loadQueue()" style="width: auto; padding: 0.4rem 0.8rem;">
          <option value="pending" selected>Pending Review</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="all">All Reviews</option>
        </select>
      </div>
    </div>

    <div class="cockpit-container">
      <!-- Left Sidebar Queue -->
      <div class="queue-sidebar">
        <div class="queue-header">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong style="font-size:0.85rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-muted);">Review Queue</strong>
            <span class="badge badge-amber" id="q-count-badge">0</span>
          </div>
        </div>
        <div class="queue-list" id="queue-container">
          <div style="padding:1.5rem; text-align:center; color:var(--text-muted); font-size:0.85rem;">Loading queue...</div>
        </div>
      </div>

      <!-- Right Detail & Edit Console -->
      <div id="detail-panel">
        <div class="card" id="empty-detail-card" style="display:block; text-align:center; padding: 3rem;">
          <p style="color:var(--text-muted);">Select a candidate draft from the queue to begin review.</p>
        </div>

        <div id="active-review-content" style="display:none;">
          <!-- Status & Actions Header -->
          <div class="card" style="padding: 1.25rem; margin-bottom: 1rem;">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:1rem;">
              <div>
                <span class="badge" id="rev-status-pill">-</span>
                <span style="font-size: 0.8rem; color: var(--text-muted); margin-left: 0.5rem;" id="rev-campaign-name"></span>
              </div>
              <div style="display:flex; gap:0.5rem;" id="decision-actions">
                <button class="btn btn-secondary btn-sm" onclick="saveDraftEdits()">💾 Save Edits</button>
                <button class="btn btn-danger btn-sm" onclick="openRejectModal()">✕ Reject</button>
                <button class="btn btn-success btn-sm" onclick="approveCurrentReview()">✓ Approve (Wait for Delivery)</button>
              </div>
            </div>
          </div>

          <!-- Waiting for Delivery Banner (if already approved) -->
          <div class="review-action-banner" id="delivery-trigger-banner" style="display:none;">
            <div>
              <strong style="color: #34d399; font-size: 0.95rem;">✓ Approved — Waiting for Explicit Delivery</strong>
              <p style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.2rem;">
                Review decision is authoritative. Triggering delivery runs all 11 server safety gates and stages to disk or sends live.
              </p>
            </div>
            <button class="btn btn-purple btn-sm" id="deliver-now-btn" onclick="executeDeliveryForCurrentRun()">⚡ Deliver Outbound Email</button>
          </div>

          <!-- Intelligence Grid -->
          <div style="display:grid; grid-template-columns: 1fr 1fr; gap:1rem; margin-bottom:1rem;">
            <div class="card" style="margin-bottom:0">
              <div class="card-title"><span>Company Intelligence</span><span class="badge badge-blue" id="d-comp-score">-</span></div>
              <h3 style="font-size: 1.1rem; font-weight:700;" id="d-comp-name">-</h3>
              <p style="font-size: 0.8rem; color:#60a5fa;" id="d-comp-domain">-</p>
              <div style="font-size: 0.82rem; color:var(--text-muted); margin: 0.5rem 0;" id="d-comp-industry">-</div>
              <div id="d-comp-signals" style="margin-top:0.5rem;"></div>
            </div>

            <div class="card" style="margin-bottom:0">
              <div class="card-title"><span>Verified Contact Quality</span><span class="badge" id="d-contact-badge">-</span></div>
              <h3 style="font-size: 1.1rem; font-weight:700;" id="d-person-name">-</h3>
              <p style="font-size: 0.8rem; color:var(--text-muted);" id="d-person-role">-</p>
              <div style="font-size: 0.88rem; font-family:'JetBrains Mono',monospace; color:#34d399; margin: 0.5rem 0;" id="d-contact-email">-</div>
              <div style="font-size: 0.78rem; color:var(--text-muted);" id="d-person-confidence"></div>
            </div>
          </div>

          <!-- Draft Editor -->
          <div class="card editor-section">
            <div class="card-title">
              <span>Authoritative Email Draft Editor</span>
              <span class="badge badge-purple" id="d-draft-persona">persona</span>
            </div>
            <div class="form-group">
              <label for="draft-subject">Subject Line</label>
              <input type="text" id="draft-subject" style="font-family:'JetBrains Mono',monospace; font-weight:600;">
            </div>
            <div class="form-group">
              <label for="draft-body">Email Body (Human edits remain strictly authoritative)</label>
              <textarea id="draft-body" rows="9"></textarea>
            </div>
          </div>

          <!-- Audit Events Timeline -->
          <div class="card">
            <div class="card-title">
              <span>Pipeline Event Audit Trail</span>
              <button class="btn btn-secondary btn-sm" onclick="toggleAuditTimeline()" style="padding:0.2rem 0.5rem; font-size:0.75rem;">Toggle Trail</button>
            </div>
            <div id="audit-trail-container" style="max-height: 200px; overflow-y:auto;"></div>
          </div>
        </div>
      </div>
    </div>
  </main>

  <!-- Reject Reason Modal -->
  <div class="modal-backdrop" id="reject-modal">
    <div class="modal" style="max-width: 480px;">
      <h2 class="modal-title">Reject Email Draft</h2>
      <p class="modal-subtitle">Candidate run will transition to 'skipped'. No delivery will occur.</p>
      <div class="form-group">
        <label for="reject-reason">Rejection Reason</label>
        <textarea id="reject-reason" rows="3" placeholder="e.g. Irrelevant ICP match, unqualified role..."></textarea>
      </div>
      <div class="modal-actions">
        <button class="btn btn-secondary" onclick="closeRejectModal()">Cancel</button>
        <button class="btn btn-danger" onclick="confirmReject()">Confirm Rejection</button>
      </div>
    </div>
  </div>

  <div id="global-toast" class="toast"></div>

  <script>
    {SHARED_JS}

    let currentReviewId = null;
    let currentReview = null;
    let reviewQueue = [];

    async function loadQueue() {{
      const user = await checkAuth();
      if (!user) return;

      const status = document.getElementById('review-filter-status').value;
      try {{
        const res = await fetch(`/api/v1/review?status=${{status}}`);
        if (!res.ok) throw new Error('Failed to fetch review queue');
        reviewQueue = await res.json();

        document.getElementById('q-count-badge').textContent = reviewQueue.length;
        const container = document.getElementById('queue-container');

        if (reviewQueue.length === 0) {{
          container.innerHTML = '<div style="padding:1.5rem; text-align:center; color:var(--text-muted); font-size:0.85rem;">No reviews in this status.</div>';
          document.getElementById('active-review-content').style.display = 'none';
          document.getElementById('empty-detail-card').style.display = 'block';
          return;
        }}

        container.innerHTML = reviewQueue.map(item => `
          <div class="queue-item ${{item.id === currentReviewId ? 'active' : ''}}" onclick="selectReview('${{item.id}}')">
            <div style="font-weight:700; font-size:0.88rem; color:#fff;">${{escapeHtml(item.company_name)}}</div>
            <div style="font-size:0.75rem; color:#60a5fa;">${{escapeHtml(item.person_name || 'Leader Unresolved')}}</div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:0.35rem;">
              <span class="badge badge-${{item.status === 'pending' ? 'amber' : (item.status === 'approved' ? 'green' : 'red')}}">${{escapeHtml(item.status)}}</span>
              <span style="font-size:0.72rem; color:var(--text-muted);">${{item.match_score || 0}}/100</span>
            </div>
          </div>
        `).join('');

        // If no active review or selected was removed, select first
        if (!currentReviewId || !reviewQueue.some(r => r.id === currentReviewId)) {{
          selectReview(reviewQueue[0].id);
        }}
      }} catch (err) {{
        showToast('Queue error: ' + err.message, true);
      }}
    }}

    async function selectReview(id) {{
      currentReviewId = id;
      document.querySelectorAll('.queue-item').forEach(el => el.classList.remove('active'));

      try {{
        const res = await fetch(`/api/v1/review/${{id}}`);
        if (!res.ok) throw new Error('Failed to load review details');
        currentReview = await res.json();

        document.getElementById('empty-detail-card').style.display = 'none';
        document.getElementById('active-review-content').style.display = 'block';

        // Header
        const pill = document.getElementById('rev-status-pill');
        pill.textContent = currentReview.status;
        pill.className = 'badge badge-' + (currentReview.status === 'pending' ? 'amber' : (currentReview.status === 'approved' ? 'green' : 'red'));
        document.getElementById('rev-campaign-name').textContent = 'Campaign: ' + (currentReview.campaign?.name || '-');

        // Company
        document.getElementById('d-comp-name').textContent = currentReview.company?.company_name || '-';
        document.getElementById('d-comp-domain').textContent = currentReview.company?.domain || '-';
        document.getElementById('d-comp-industry').textContent = `${{currentReview.company?.industry || 'Tech'}} &bull; ${{currentReview.company?.stage || 'Early-Stage'}} &bull; ${{currentReview.company?.location || 'Remote'}}`;
        document.getElementById('d-comp-score').textContent = `Match ${{currentReview.company?.match_score || 0}}/100`;

        const signals = (currentReview.company?.technical_signals || []).concat(currentReview.company?.why_match || []).slice(0, 4);
        document.getElementById('d-comp-signals').innerHTML = signals.map(s => `<span class="tag-pill">${{escapeHtml(s)}}</span>`).join('');

        // Person & Contact
        const p = currentReview.person;
        const c = currentReview.contact;
        document.getElementById('d-person-name').textContent = p ? p.full_name : 'No verified leader';
        document.getElementById('d-person-role').textContent = p ? p.role : '-';
        document.getElementById('d-contact-email').textContent = c?.email || 'No email resolved';

        const conf = p?.person_confidence || 0;
        document.getElementById('d-person-confidence').textContent = `Person confidence: ${{(conf * 100).toFixed(0)}}% (gate: &ge; 70%)`;

        const contactBadge = document.getElementById('d-contact-badge');
        contactBadge.textContent = c?.verification_status || 'unverified';
        contactBadge.className = 'badge ' + (c?.verification_status === 'valid' ? 'badge-green' : 'badge-amber');

        // Draft
        const draft = currentReview.draft || {{}};
        document.getElementById('draft-subject').value = currentReview.edited_subject || draft.subject || '';
        document.getElementById('draft-body').value = currentReview.edited_body || draft.body || '';
        document.getElementById('d-draft-persona').textContent = draft.persona || 'standard';

        // Decision actions vs Waiting for Delivery banner
        const isApproved = currentReview.status === 'approved';
        const deliveryBanner = document.getElementById('delivery-trigger-banner');
        deliveryBanner.style.display = isApproved ? 'flex' : 'none';

        // Events trail
        const trailContainer = document.getElementById('audit-trail-container');
        const events = currentReview.events || [];
        if (events.length === 0) {{
          trailContainer.innerHTML = '<p style="color:var(--text-muted);font-size:0.8rem">No events logged.</p>';
        }} else {{
          trailContainer.innerHTML = events.map(ev => `
            <div style="font-size:0.78rem; padding:0.35rem 0; border-bottom:1px solid #1a2333;">
              <span style="color:#60a5fa; font-weight:600;">${{escapeHtml(ev.event_type)}}</span>
              <span style="color:var(--text-muted); margin-left:0.5rem;">${{new Date(ev.created_at).toLocaleTimeString()}}</span>
              <div style="color:#d1d5db; margin-top:0.15rem;">${{escapeHtml(ev.message)}}</div>
            </div>
          `).join('');
        }}
      }} catch (err) {{
        showToast('Error: ' + err.message, true);
      }}
    }}

    async function saveDraftEdits() {{
      if (!currentReviewId) return;
      const subject = document.getElementById('draft-subject').value.trim();
      const body = document.getElementById('draft-body').value.trim();

      try {{
        const res = await fetch(`/api/v1/review/${{currentReviewId}}`, {{
          method: 'PATCH',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ subject, body }})
        }});

        if (res.ok) {{
          showToast('Draft edits saved authoritatively!');
          await selectReview(currentReviewId);
        }} else {{
          const err = await res.json();
          showToast(err.detail || 'Failed to save draft edits', true);
        }}
      }} catch (e) {{
        showToast('Error saving edits: ' + e.message, true);
      }}
    }}

    async function approveCurrentReview() {{
      if (!currentReviewId) return;

      const subject = document.getElementById('draft-subject').value.trim();
      const body = document.getElementById('draft-body').value.trim();

      try {{
        const res = await fetch(`/api/v1/review/${{currentReviewId}}/approve`, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ edited_subject: subject, edited_body: body }})
        }});

        if (res.ok) {{
          showToast('Approved — Run is now Waiting for Delivery (0 emails sent)');
          await loadQueue();
          await selectReview(currentReviewId);
        }} else {{
          const err = await res.json();
          showToast(err.detail || 'Approval rejected', true);
        }}
      }} catch (e) {{
        showToast('Network error during approval', true);
      }}
    }}

    function openRejectModal() {{
      document.getElementById('reject-modal').style.display = 'flex';
      document.getElementById('reject-reason').focus();
    }}

    function closeRejectModal() {{
      document.getElementById('reject-modal').style.display = 'none';
      document.getElementById('reject-reason').value = '';
    }}

    async function confirmReject() {{
      const reason = document.getElementById('reject-reason').value.trim();
      closeRejectModal();

      try {{
        const res = await fetch(`/api/v1/review/${{currentReviewId}}/reject`, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ reason }})
        }});

        if (res.ok) {{
          showToast('Draft rejected. Pipeline run marked skipped.');
          await loadQueue();
        }} else {{
          const err = await res.json();
          showToast(err.detail || 'Rejection failed', true);
        }}
      }} catch (e) {{
        showToast('Error rejecting review', true);
      }}
    }}

    async function executeDeliveryForCurrentRun() {{
      if (!currentReview?.pipeline_run_id) return;
      const runId = currentReview.pipeline_run_id;

      if (!confirm('Explicitly trigger outbound delivery?\\n\\nThis calls the Phase 8 authoritative delivery boundary. All 11 safety gates will be validated.')) {{
        return;
      }}

      try {{
        const res = await fetch(`/api/v1/deliveries/${{runId}}`, {{ method: 'POST' }});
        const data = await res.json();
        if (res.ok) {{
          showToast(`Delivery completed: ${{data.delivery_status}} (Mode: ${{data.delivery_mode}})`);
          await selectReview(currentReviewId);
        }} else {{
          showToast(data.detail || 'Delivery safety gate blocked dispatch', true);
        }}
      }} catch (e) {{
        showToast('Delivery error: ' + e.message, true);
      }}
    }}

    function toggleAuditTimeline() {{
      const el = document.getElementById('audit-trail-container');
      el.style.display = el.style.display === 'none' ? 'block' : 'none';
    }}

    document.addEventListener('DOMContentLoaded', loadQueue);
  </script>
</body>
</html>"""


# =====================================================================
# 6. /deliveries
# =====================================================================
def get_deliveries_html() -> str:
    navbar = NAVBAR_TEMPLATE.format(
        active_dashboard="",
        active_campaigns="",
        active_review="",
        active_deliveries="active",
        active_profile="",
        active_settings="",
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Deliveries - Outbound Pipeline Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    {SHARED_CSS}
  </style>
</head>
<body>
  {navbar}

  <main class="main-content">
    <div class="page-header">
      <div>
        <h1 class="page-title"><span>📦</span> Outbound Delivery History</h1>
        <p class="page-subtitle">Inspect authoritative dispatch audit records, staging artifacts, and gate evaluations</p>
      </div>
      <div style="display: flex; gap: 0.5rem; align-items: center;">
        <select id="delivery-filter-status" onchange="loadDeliveries()" style="width: auto; padding: 0.45rem 0.8rem;">
          <option value="all" selected>All Deliveries</option>
          <option value="sent">Sent (Live)</option>
          <option value="staged">Staged (Dry-Run)</option>
          <option value="failed">Failed</option>
          <option value="blocked_safety">Blocked by Safety Gate</option>
        </select>
      </div>
    </div>

    <div class="card">
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Company</th>
              <th>Recipient</th>
              <th>Campaign</th>
              <th>Status</th>
              <th>Mode / Provider</th>
              <th>Delivered At</th>
              <th>Artifact / Reason</th>
              <th>Safety Audit</th>
            </tr>
          </thead>
          <tbody id="deliveries-tbody">
            <tr><td colspan="8" class="empty-state">Loading delivery records...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </main>

  <!-- Safety Audit Modal -->
  <div class="modal-backdrop" id="audit-modal">
    <div class="modal" style="max-width: 600px;">
      <h2 class="modal-title">Authoritative 11-Gate Safety Audit</h2>
      <p class="modal-subtitle" id="audit-sub">Evaluated before email staging or live dispatch</p>
      <div id="audit-gates-list" style="max-height:350px; overflow-y:auto;"></div>
      <div class="modal-actions">
        <button class="btn btn-secondary" onclick="closeAuditModal()">Close</button>
      </div>
    </div>
  </div>

  <div id="global-toast" class="toast"></div>

  <script>
    {SHARED_JS}

    let deliveriesList = [];

    async function loadDeliveries() {{
      const user = await checkAuth();
      if (!user) return;

      const status = document.getElementById('delivery-filter-status').value;
      try {{
        const res = await fetch(`/api/v1/deliveries?status=${{status}}`);
        if (!res.ok) throw new Error('Failed to load deliveries');
        deliveriesList = await res.json();
        const tbody = document.getElementById('deliveries-tbody');

        if (deliveriesList.length === 0) {{
          tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No delivery records found matching filter.</td></tr>';
          return;
        }}

        tbody.innerHTML = deliveriesList.map((d, idx) => {{
          let badgeClass = 'badge-gray';
          if (d.delivery_status === 'sent') badgeClass = 'badge-green';
          else if (d.delivery_status === 'staged') badgeClass = 'badge-cyan';
          else if (d.delivery_status === 'failed') badgeClass = 'badge-red';
          else if (d.delivery_status === 'blocked_safety') badgeClass = 'badge-amber';

          const artifactOrErr = d.staged_file_path || d.error_message || '-';

          return `
            <tr>
              <td>
                <strong>${{escapeHtml(d.company_name)}}</strong><br>
                <span style="font-size:0.75rem; color:var(--text-muted)">${{escapeHtml(d.domain)}}</span>
              </td>
              <td>
                <div>${{escapeHtml(d.recipient_name || '-')}}</div>
                <div style="font-size:0.75rem; color:#60a5fa; font-family:'JetBrains Mono',monospace;">${{escapeHtml(d.recipient_email || 'No email')}}</div>
              </td>
              <td style="font-size:0.8rem;">${{escapeHtml(d.campaign_name)}}</td>
              <td><span class="badge ${{badgeClass}}">${{escapeHtml(d.delivery_status)}}</span></td>
              <td>
                <span class="badge badge-purple">${{escapeHtml(d.delivery_mode)}}</span>
                <span style="font-size:0.75rem; color:var(--text-muted); display:block; margin-top:0.2rem;">${{escapeHtml(d.provider)}}</span>
              </td>
              <td style="font-size:0.78rem; color:var(--text-muted);">${{d.delivered_at ? new Date(d.delivered_at).toLocaleString() : '-'}}</td>
              <td style="font-size:0.78rem; max-width:200px; word-break:break-all;" title="${{escapeHtml(artifactOrErr)}}">
                ${{escapeHtml(artifactOrErr.slice(0, 35))}}${{artifactOrErr.length > 35 ? '...' : ''}}
              </td>
              <td>
                <button onclick="inspectAuditRecord(${{idx}})" class="btn btn-secondary btn-sm" style="padding:0.25rem 0.6rem; font-size:0.75rem;">Inspect Audit</button>
              </td>
            </tr>
          `;
        }}).join('');
      }} catch (err) {{
        showToast('Error: ' + err.message, true);
      }}
    }}

    function inspectAuditRecord(idx) {{
      const d = deliveriesList[idx];
      if (!d) return;

      document.getElementById('audit-sub').textContent = `${{d.company_name}} (${{d.domain}}) &bull; Status: ${{d.delivery_status}}`;
      const listEl = document.getElementById('audit-gates-list');

      const audit = d.safety_audit || {{}};
      const gates = [
        {{ key: 'tenant_isolated', name: 'Gate 1: Strict Tenant Isolation' }},
        {{ key: 'waiting_for_delivery', name: 'Gate 2: Run in waiting_for_delivery state' }},
        {{ key: 'review_approved', name: 'Gate 3: Human Review Approved' }},
        {{ key: 'draft_integrity', name: 'Gate 4: Immutable Draft Integrity' }},
        {{ key: 'email_syntax', name: 'Gate 5: RFC Email Syntax Validated' }},
        {{ key: 'not_blacklisted', name: 'Gate 6: Canonical Blacklist / Anti-Fabrication' }},
        {{ key: 'email_verified', name: 'Gate 7: Database Verification Status (valid / accept_all)' }},
        {{ key: 'person_confidence', name: 'Gate 8: Person Confidence Threshold (&ge; 0.70)' }},
        {{ key: 'deduplication', name: 'Gate 9: Deduplication Union (JSONL + DB + Company)' }},
        {{ key: 'volume_caps', name: 'Gate 10: Unified Volume Caps (10/day, 50/week)' }},
        {{ key: 'live_gate', name: 'Gate 11: Server Live Send Configuration Gate' }},
      ];

      listEl.innerHTML = gates.map(g => {{
        const isPassed = audit[g.key] !== false;
        return `
          <div style="display:flex; justify-content:space-between; align-items:center; padding:0.6rem; border-bottom:1px solid #1f2937;">
            <span style="font-size:0.85rem; color:#e5e7eb;">${{g.name}}</span>
            <span class="badge badge-${{isPassed ? 'green' : 'red'}}">${{isPassed ? 'Passed' : 'Blocked'}}</span>
          </div>
        `;
      }}).join('');

      document.getElementById('audit-modal').style.display = 'flex';
    }}

    function closeAuditModal() {{
      document.getElementById('audit-modal').style.display = 'none';
    }}

    document.addEventListener('DOMContentLoaded', loadDeliveries);
  </script>
</body>
</html>"""


# =====================================================================
# 7. /profile
# =====================================================================
def get_profile_html() -> str:
    navbar = NAVBAR_TEMPLATE.format(
        active_dashboard="",
        active_campaigns="",
        active_review="",
        active_deliveries="",
        active_profile="active",
        active_settings="",
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Profile & Resumes - Outbound Pipeline Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    {SHARED_CSS}
  </style>
</head>
<body>
  {navbar}

  <main class="main-content">
    <div class="page-header">
      <div>
        <h1 class="page-title"><span>👤</span> Operator Outreach Profile & Resumes</h1>
        <p class="page-subtitle">Manage sender identity, candidate highlights, and parsed outreach personas</p>
      </div>
    </div>

    <!-- Candidate Profile Section -->
    <div class="card">
      <div class="card-title">Outreach Sender Identity</div>
      <form id="profile-form">
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
          <div class="form-group">
            <label for="p-fullname">Full Name *</label>
            <input type="text" id="p-fullname" required placeholder="Raghav Pathak">
          </div>
          <div class="form-group">
            <label for="p-title">Professional Title *</label>
            <input type="text" id="p-title" required placeholder="Founding Cybersecurity Engineer">
          </div>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 1rem;">
          <div class="form-group">
            <label for="p-email">Contact Email</label>
            <input type="email" id="p-email" placeholder="raghav@example.com">
          </div>
          <div class="form-group">
            <label for="p-location">Location</label>
            <input type="text" id="p-location" placeholder="Bengaluru, India">
          </div>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem;">
          <div class="form-group">
            <label for="p-portfolio">Portfolio URL</label>
            <input type="text" id="p-portfolio" placeholder="https://work.raghavpathak.me">
          </div>
          <div class="form-group">
            <label for="p-github">GitHub URL</label>
            <input type="text" id="p-github" placeholder="https://github.com/...">
          </div>
          <div class="form-group">
            <label for="p-linkedin">LinkedIn URL</label>
            <input type="text" id="p-linkedin" placeholder="https://linkedin.com/in/...">
          </div>
        </div>
        <div class="form-group">
          <label for="p-instructions">Custom Drafting Instructions</label>
          <textarea id="p-instructions" rows="3" placeholder="Highlight hands-on vulnerability research, LangGraph pipelines, and defensive tooling..."></textarea>
        </div>
        <button type="submit" class="btn btn-primary" id="save-profile-btn">Save Profile Changes</button>
      </form>
    </div>

    <!-- Resume Management Section -->
    <div class="card" style="margin-top: 2rem;">
      <div class="card-title">
        <span>Uploaded Resume Intelligence</span>
        <button class="btn btn-secondary btn-sm" onclick="openUploadResumeModal()">+ Upload Resume</button>
      </div>

      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>Filename</th>
              <th>Status</th>
              <th>Active Identity</th>
              <th>Uploaded Date</th>
              <th>Parsed Personas</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="resumes-tbody">
            <tr><td colspan="6" class="empty-state">Loading uploaded resumes...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </main>

  <!-- Upload Resume Modal -->
  <div class="modal-backdrop" id="upload-resume-modal">
    <div class="modal" style="max-width: 480px;">
      <h2 class="modal-title">Upload Candidate Resume</h2>
      <p class="modal-subtitle">Upload a PDF or JSON resume to extract structured outreach personas</p>
      <form id="upload-resume-form">
        <div class="form-group">
          <label for="resume-file">Resume File (.pdf or .json)</label>
          <input type="file" id="resume-file" required accept=".pdf,.json">
        </div>
        <div class="modal-actions">
          <button type="button" class="btn btn-secondary" onclick="closeUploadResumeModal()">Cancel</button>
          <button type="submit" class="btn btn-primary" id="upload-btn">Upload & Parse</button>
        </div>
      </form>
    </div>
  </div>

  <div id="global-toast" class="toast"></div>

  <script>
    {SHARED_JS}

    async function loadProfile() {{
      const user = await checkAuth();
      if (!user) return;

      try {{
        const res = await fetch('/api/v1/profile');
        if (!res.ok) return;
        const p = await res.json();

        document.getElementById('p-fullname').value = p.full_name || '';
        document.getElementById('p-title').value = p.title || '';
        document.getElementById('p-email').value = p.email || '';
        document.getElementById('p-location').value = p.location || '';
        document.getElementById('p-portfolio').value = p.portfolio_url || '';
        document.getElementById('p-github').value = p.github_url || '';
        document.getElementById('p-linkedin').value = p.linkedin_url || '';
        document.getElementById('p-instructions').value = p.custom_instructions || '';
      }} catch (e) {{}}
    }}

    async function loadResumes() {{
      try {{
        const res = await fetch('/api/v1/resumes');
        if (!res.ok) return;
        const list = await res.json();
        const tbody = document.getElementById('resumes-tbody');

        if (list.length === 0) {{
          tbody.innerHTML = '<tr><td colspan="6" class="empty-state">No resumes uploaded yet. Click Upload Resume to begin.</td></tr>';
          return;
        }}

        tbody.innerHTML = list.map(r => `
          <tr>
            <td><strong>${{escapeHtml(r.filename)}}</strong></td>
            <td><span class="badge badge-${{r.parsing_status === 'completed' ? 'green' : (r.parsing_status === 'failed' ? 'red' : 'amber')}}">${{escapeHtml(r.parsing_status)}}</span></td>
            <td>
              ${{r.is_active ? '<span class="badge badge-blue">&bull; Active for Campaigns</span>' : '<span style="color:var(--text-muted);font-size:0.75rem">Inactive</span>'}}
            </td>
            <td style="font-size:0.8rem; color:var(--text-muted);">${{new Date(r.uploaded_at).toLocaleDateString()}}</td>
            <td>
              <span class="tag-pill">Security / Infra</span>
              <span class="tag-pill">AI / ML</span>
              <span class="tag-pill">HR / Talent</span>
            </td>
            <td>
              ${{!r.is_active ? `<button onclick="activateResume('${{r.id}}')" class="btn btn-secondary btn-sm">Set as Active</button>` : '<span style="color:#34d399; font-size:0.8rem;">Current Active</span>'}}
            </td>
          </tr>
        `).join('');
      }} catch (e) {{}}
    }}

    async function activateResume(id) {{
      try {{
        const res = await fetch(`/api/v1/resumes/${{id}}/activate`, {{ method: 'POST' }});
        if (res.ok) {{
          showToast('Resume set as active outreach profile!');
          await loadResumes();
        }} else {{
          showToast('Failed to activate resume', true);
        }}
      }} catch (e) {{
        showToast('Error: ' + e.message, true);
      }}
    }}

    document.getElementById('profile-form').addEventListener('submit', async (e) => {{
      e.preventDefault();
      const btn = document.getElementById('save-profile-btn');
      btn.disabled = true;
      btn.textContent = 'Saving...';

      const payload = {{
        full_name: document.getElementById('p-fullname').value.trim(),
        title: document.getElementById('p-title').value.trim(),
        email: document.getElementById('p-email').value.trim(),
        location: document.getElementById('p-location').value.trim(),
        portfolio_url: document.getElementById('p-portfolio').value.trim(),
        github_url: document.getElementById('p-github').value.trim(),
        linkedin_url: document.getElementById('p-linkedin').value.trim(),
        custom_instructions: document.getElementById('p-instructions').value.trim(),
      }};

      try {{
        const res = await fetch('/api/v1/profile', {{
          method: 'PUT',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(payload)
        }});

        if (res.ok) {{
          showToast('Profile updated successfully!');
        }} else {{
          const err = await res.json();
          showToast(err.detail || 'Failed to update profile', true);
        }}
      }} catch (err) {{
        showToast('Error saving profile', true);
      }} finally {{
        btn.disabled = false;
        btn.textContent = 'Save Profile Changes';
      }}
    }});

    function openUploadResumeModal() {{
      document.getElementById('upload-resume-modal').style.display = 'flex';
    }}

    function closeUploadResumeModal() {{
      document.getElementById('upload-resume-modal').style.display = 'none';
      document.getElementById('upload-resume-form').reset();
    }}

    document.getElementById('upload-resume-form').addEventListener('submit', async (e) => {{
      e.preventDefault();
      const fileInput = document.getElementById('resume-file');
      if (!fileInput.files[0]) return;

      const uploadBtn = document.getElementById('upload-btn');
      uploadBtn.disabled = true;
      uploadBtn.textContent = 'Parsing...';

      const formData = new FormData();
      formData.append('file', fileInput.files[0]);

      try {{
        const res = await fetch('/api/v1/resumes/upload', {{
          method: 'POST',
          body: formData
        }});

        if (res.ok) {{
          showToast('Resume uploaded and parsed into outreach personas!');
          closeUploadResumeModal();
          await loadResumes();
        }} else {{
          const err = await res.json();
          showToast(err.detail || 'Upload failed', true);
        }}
      }} catch (err) {{
        showToast('Error uploading resume: ' + err.message, true);
      }} finally {{
        uploadBtn.disabled = false;
        uploadBtn.textContent = 'Upload & Parse';
      }}
    }});

    document.addEventListener('DOMContentLoaded', () => {{
      loadProfile();
      loadResumes();
    }});
  </script>
</body>
</html>"""


# =====================================================================
# 8. /settings
# =====================================================================
def get_settings_html() -> str:
    navbar = NAVBAR_TEMPLATE.format(
        active_dashboard="",
        active_campaigns="",
        active_review="",
        active_deliveries="",
        active_profile="",
        active_settings="active",
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Settings - Outbound Pipeline Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    {SHARED_CSS}
    .settings-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.85rem 0;
      border-bottom: 1px solid var(--card-border);
    }}
    .settings-row:last-child {{ border-bottom: none; }}
  </style>
</head>
<body>
  {navbar}

  <main class="main-content">
    <div class="page-header">
      <div>
        <h1 class="page-title"><span>⚙️</span> Operational Configuration & Safety Policy</h1>
        <p class="page-subtitle">Server-enforced dispatch gates, volume invariants, and infrastructure health</p>
      </div>
    </div>

    <!-- Security Warning Banner -->
    <div class="card" style="border-color: rgba(59, 130, 246, 0.4); background: linear-gradient(180deg, rgba(59, 130, 246, 0.08) 0%, var(--card-bg) 100%);">
      <div style="display:flex; gap:0.75rem; align-items:flex-start;">
        <span style="font-size:1.3rem;">🔒</span>
        <div>
          <strong style="color:#60a5fa; font-size:0.95rem;">Authoritative Server Boundary Policy</strong>
          <p style="font-size:0.85rem; color:var(--text-muted); margin-top:0.35rem; line-height:1.5;">
            Outbound email dispatch gates (<code>DELIVERY_MODE</code>, <code>DRY_RUN</code>, <code>CONFIRM_LIVE</code>) are strictly controlled via server-side environment configuration. The web console cannot override dispatch safety gates. All credentials and secrets are withheld from client presentation.
          </p>
        </div>
      </div>
    </div>

    <!-- Live Health & Safety Mode -->
    <div class="card">
      <div class="card-title">System Status & Environment Invariants</div>
      <div class="settings-row">
        <div>
          <strong>System Health</strong>
          <div style="font-size:0.78rem; color:var(--text-muted);">Core API health and database connection</div>
        </div>
        <span class="badge badge-green" id="health-status">Healthy (1.0.0)</span>
      </div>

      <div class="settings-row">
        <div>
          <strong>Delivery Mode</strong>
          <div style="font-size:0.78rem; color:var(--text-muted);">Outbound execution mode (stub, staged, live)</div>
        </div>
        <span class="badge badge-purple" id="set-delivery-mode">staged</span>
      </div>

      <div class="settings-row">
        <div>
          <strong>Dry Run Staging Enforced</strong>
          <div style="font-size:0.78rem; color:var(--text-muted);">Prevents external provider dispatch side-effects</div>
        </div>
        <span class="badge badge-cyan" id="set-dry-run">True (Staging Active)</span>
      </div>

      <div class="settings-row">
        <div>
          <strong>Confirm Live Flag</strong>
          <div style="font-size:0.78rem; color:var(--text-muted);">Required environment flag for live sending</div>
        </div>
        <span class="badge badge-gray" id="set-confirm-live">False (Blocked)</span>
      </div>
    </div>

    <!-- Volume Caps & Hard Gates -->
    <div class="card">
      <div class="card-title">Volume Caps & Hard Safety Thresholds</div>
      <div class="settings-row">
        <div>
          <strong>Daily Volume Cap</strong>
          <div style="font-size:0.78rem; color:var(--text-muted);">Hard limit across CLI and Web dispatches</div>
        </div>
        <span style="font-family:'JetBrains Mono',monospace; font-weight:700;">10 sends / 24h</span>
      </div>

      <div class="settings-row">
        <div>
          <strong>Weekly Volume Cap</strong>
          <div style="font-size:0.78rem; color:var(--text-muted);">Rolling 7-day volume cap</div>
        </div>
        <span style="font-family:'JetBrains Mono',monospace; font-weight:700;">50 sends / 7d</span>
      </div>

      <div class="settings-row">
        <div>
          <strong>Minimum Person Confidence</strong>
          <div style="font-size:0.78rem; color:var(--text-muted);">Threshold for leader verification acceptance</div>
        </div>
        <span class="badge badge-blue">&ge; 0.70 (70%)</span>
      </div>

      <div class="settings-row">
        <div>
          <strong>Login Rate Limiter</strong>
          <div style="font-size:0.78rem; color:var(--text-muted);">Brute-force protection on /api/v1/auth/login</div>
        </div>
        <span style="font-size:0.85rem; color:var(--text-muted);">5 attempts per 15 minutes</span>
      </div>
    </div>
  </main>

  <script>
    {SHARED_JS}

    async function loadSettings() {{
      const user = await checkAuth();
      if (!user) return;

      try {{
        const res = await fetch('/api/v1/health');
        if (res.ok) {{
          const data = await res.json();
          document.getElementById('health-status').textContent = `${{data.status}} (v${{data.version}})`;
          document.getElementById('set-delivery-mode').textContent = data.delivery_mode || 'staged';
          document.getElementById('set-dry-run').textContent = data.dry_run ? 'True (Staging Active)' : 'False (Live Dispatch Allowed)';
          document.getElementById('set-dry-run').className = 'badge ' + (data.dry_run ? 'badge-cyan' : 'badge-amber');
        }}
      }} catch (e) {{}}
    }}

    document.addEventListener('DOMContentLoaded', loadSettings);
  </script>
</body>
</html>"""
