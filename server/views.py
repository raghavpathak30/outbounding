"""
HTML & CSS frontend views for the Outbound Lead Pipeline web interface.
Provides:
- /login: Modern operator login page posting to /api/v1/auth/login.
- /dashboard: Real-time operator dashboard with volume cap gauges and user profile state.
"""

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


def get_dashboard_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dashboard - Outbound Pipeline Console</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg-base: #0a0f1d;
      --card-bg: #111827;
      --card-border: #1f2937;
      --accent: #3b82f6;
      --accent-glow: rgba(59, 130, 246, 0.2);
      --text-main: #f9fafb;
      --text-muted: #9ca3af;
      --success: #10b981;
      --warning: #f59e0b;
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
    .navbar {
      background: rgba(17, 24, 39, 0.85);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--card-border);
      padding: 1rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .brand { display: flex; align-items: center; gap: 0.75rem; font-weight: 700; font-size: 1.15rem; }
    .brand-icon { font-size: 1.4rem; }
    .user-section { display: flex; align-items: center; gap: 1.25rem; }
    .user-badge { font-size: 0.88rem; color: var(--text-muted); }
    .user-email { color: #60a5fa; font-weight: 600; }
    .btn-logout {
      background: transparent;
      border: 1px solid #374151;
      color: var(--text-muted);
      border-radius: 6px;
      padding: 0.45rem 0.9rem;
      font-size: 0.82rem;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
    }
    .btn-logout:hover { color: #f87171; border-color: #ef4444; }
    .main-content {
      flex: 1;
      max-width: 1200px;
      width: 100%;
      margin: 0 auto;
      padding: 2.5rem 2rem;
    }
    .section-title { font-size: 1.35rem; font-weight: 700; margin-bottom: 1.5rem; letter-spacing: -0.02em; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.5rem; margin-bottom: 2.5rem; }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 1.75rem;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
    }
    .card-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 1rem; }
    .card-title { font-size: 0.85rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); }
    .gauge-value { font-size: 1.8rem; font-weight: 700; }
    .gauge-bar-bg {
      background: #1f2937;
      height: 10px;
      border-radius: 9999px;
      overflow: hidden;
      margin: 1rem 0 0.5rem 0;
    }
    .gauge-fill { height: 100%; border-radius: 9999px; transition: width 0.5s ease; }
    .gauge-fill-green { background: linear-gradient(90deg, #10b981, #34d399); }
    .gauge-fill-blue { background: linear-gradient(90deg, #2563eb, #60a5fa); }
    .gauge-caption { font-size: 0.8rem; color: var(--text-muted); }
    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.3rem 0.75rem;
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: #34d399;
      border-radius: 9999px;
      font-size: 0.8rem;
      font-weight: 600;
    }
    .status-dot { width: 8px; height: 8px; background: #34d399; border-radius: 50%; }
    .profile-summary { margin-top: 1rem; font-size: 0.9rem; line-height: 1.6; color: #d1d5db; }
  </style>
</head>
<body>
  <header class="navbar">
    <div class="brand">
      <span class="brand-icon">🚀</span>
      <span>Outbound Pipeline Console</span>
    </div>
    <div class="user-section">
      <span class="user-badge" id="user-status-display">Logged in as <span class="user-email" id="user-email-placeholder">Loading...</span></span>
      <button class="btn-logout" id="logout-btn">Sign Out</button>
    </div>
  </header>

  <main class="main-content">
    <h2 class="section-title">Safety Gauges & Volume Caps</h2>
    <div class="grid">
      <!-- Daily Cap Gauge Placeholder -->
      <div class="card">
        <div class="card-header">
          <span class="card-title">Daily Volume Cap</span>
          <span class="status-pill"><span class="status-dot"></span>Safe</span>
        </div>
        <div class="gauge-value" id="daily-cap-value">0 / 20</div>
        <div class="gauge-bar-bg">
          <div class="gauge-fill gauge-fill-green" style="width: 5%;"></div>
        </div>
        <p class="gauge-caption">20 max sends per day (Hard Safety Invariant)</p>
      </div>

      <!-- Weekly Cap Gauge Placeholder -->
      <div class="card">
        <div class="card-header">
          <span class="card-title">Weekly Volume Cap</span>
          <span class="status-pill"><span class="status-dot"></span>Safe</span>
        </div>
        <div class="gauge-value" id="weekly-cap-value">0 / 50</div>
        <div class="gauge-bar-bg">
          <div class="gauge-fill gauge-fill-blue" style="width: 10%;"></div>
        </div>
        <p class="gauge-caption">50 max sends per 7-day rolling window</p>
      </div>

      <!-- Pipeline Mode Status -->
      <div class="card">
        <div class="card-header">
          <span class="card-title">Safety Mode</span>
          <span class="status-pill" style="color: #60a5fa; border-color: rgba(96, 165, 250, 0.3); background: rgba(37, 99, 235, 0.15);">Dry-Run Staging</span>
        </div>
        <div class="gauge-value" style="font-size: 1.3rem; margin-top: 0.5rem;">Zero Live Dispatch</div>
        <p class="gauge-caption" style="margin-top: 1rem;">Payloads staged strictly to <code>staged_deliveries/</code> with human approval gates.</p>
      </div>
    </div>

    <h2 class="section-title">Operator Profile State</h2>
    <div class="card">
      <div class="card-header">
        <span class="card-title">Active Outreach Identity</span>
      </div>
      <div class="profile-summary" id="profile-details">
        <p>Loading operator profile context...</p>
      </div>
    </div>
  </main>

  <script>
    // Fetch authenticated user info
    async function loadUser() {
      try {
        const res = await fetch('/api/v1/auth/me');
        if (!res.ok) {
          window.location.href = '/login';
          return;
        }
        const data = await res.json();
        document.getElementById('user-email-placeholder').textContent = data.email;

        const profileDiv = document.getElementById('profile-details');
        if (data.profile) {
          profileDiv.innerHTML = `
            <p><strong>Name:</strong> ${data.profile.full_name || 'Not set'}</p>
            <p><strong>Title:</strong> ${data.profile.title || 'Not set'}</p>
            <p><strong>Email:</strong> ${data.profile.email || data.email}</p>
            <p><strong>Portfolio:</strong> <a href="${data.profile.portfolio_url || '#'}" target="_blank" style="color:#60a5fa">${data.profile.portfolio_url || 'None'}</a></p>
          `;
        } else {
          profileDiv.innerHTML = `<p>Profile record initialized for ${data.email}. Configure via /api/v1/profile.</p>`;
        }
      } catch (err) {
        window.location.href = '/login';
      }
    }

    document.getElementById('logout-btn').addEventListener('click', async () => {
      try {
        await fetch('/api/v1/auth/logout', { method: 'POST' });
      } finally {
        window.location.href = '/login';
      }
    });

    loadUser();
  </script>
</body>
</html>"""
