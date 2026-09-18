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
      /* Surfaces — dark gray, never pure black */
      --bg-base:      #0F1419;   /* page background */
      --bg-surface:   #171C22;   /* panels */
      --bg-elevated:  #1E252D;   /* cards, modals */
      --border:       #2A323C;   /* decorative dividers only */
      --border-strong:#484F58;   /* perceivable control outlines (3:1) */

      /* Text */
      --text-primary: #E6EDF3;   /* 14.5:1 on surface */
      --text-muted:   #9AA7B4;   /* 7.0:1 on surface */

      /* Semantic status — as text/icons on dark surfaces */
      --info:    #4C8DF5;   /* 5.3:1 */
      --success: #3FB950;   /* 6.7:1 */
      --warning: #D29922;   /* 6.8:1 */
      --danger:  #F85149;   /* 5.1:1 */
      --accent:  #2DB7A3;   /* 6.9:1 */

      /* Accessible semantic colors for existing UI tags & badges */
      --purple:  #BC8CFF;   /* 8.5:1 on surface */
      --cyan:    #39C5CF;   /* 8.8:1 on surface */

      /* Backward compatibility aliases */
      --card-bg:      var(--bg-surface);
      --card-border:  var(--border);
      --card-hover:   var(--bg-elevated);
      --text-main:    var(--text-primary);
      --text-dim:     var(--text-muted);
      --accent-glow:  rgba(45, 183, 163, 0.25);
      --success-glow: rgba(63, 185, 80, 0.2);
      --warning-glow: rgba(210, 153, 34, 0.2);
      --purple-glow:  rgba(188, 140, 255, 0.2);
      --danger-glow:  rgba(248, 81, 73, 0.2);

      /* Button FILLS — darker than the text colors above, for white text at 4.6:1.
         Do not use --info or --danger as button backgrounds with white text;
         that combination fails contrast at 3.3:1. */
      --btn-primary-bg: #1F6FEB;  /* white text = 4.6:1 */
      --btn-danger-bg:  #DA3633;  /* white text = 4.6:1 */
      --btn-success-bg: #238636;  /* white text = 4.6:1 */
      --btn-warning-bg: #9E6A03;  /* white text = 4.5:1 */
      --btn-purple-bg:  #6E40C9;  /* white text = 5.2:1 */
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: var(--bg-base);
      color: var(--text-primary);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    a { color: var(--info); text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* Sticky container for navbar + persistent sending mode banner */
    .navbar-container {
      position: sticky;
      top: 0;
      z-index: 100;
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border);
    }
    .navbar {
      background: var(--bg-surface);
      padding: 0.85rem 2rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .brand { display: flex; align-items: center; gap: 1.5rem; }
    .brand-logo { display: flex; align-items: center; gap: 0.6rem; font-weight: 700; font-size: 1.15rem; color: var(--text-primary); text-decoration: none; }
    .brand-icon { font-size: 1.3rem; }
    .nav-links { display: flex; gap: 1.25rem; }
    .nav-link { color: var(--text-muted); text-decoration: none; font-size: 0.88rem; font-weight: 500; transition: color 0.2s; padding: 0.35rem 0.6rem; border-radius: 6px; }
    .nav-link:hover { color: var(--text-primary); text-decoration: none; }
    .nav-link.active { color: var(--info); background: rgba(76, 141, 245, 0.12); font-weight: 600; }
    .user-section { display: flex; align-items: center; gap: 1rem; }
    .user-badge { font-size: 0.82rem; color: var(--text-muted); display: flex; align-items: center; gap: 0.4rem; }
    .user-email { color: var(--info); font-weight: 600; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--success); display: inline-block; }
    .btn-logout {
      background: transparent;
      border: 1px solid var(--border-strong);
      color: var(--text-muted);
      border-radius: 6px;
      padding: 0.4rem 0.8rem;
      font-size: 0.85rem;
      min-height: 32px;
      cursor: pointer;
      transition: all 0.2s;
    }
    .btn-logout:hover { color: var(--danger); border-color: var(--btn-danger-bg); }

    /* Persistent Sending Mode Banner */
    .sending-mode-banner {
      padding: 0.5rem 2rem;
      font-size: 0.85rem;
      font-weight: 500;
      background: var(--bg-elevated);
      border-left: 3px solid var(--info);
      color: var(--text-primary);
      border-top: 1px solid var(--border);
    }
    .sending-mode-banner.mode-live {
      background: #3D2E0A;
      border-left: 3px solid var(--warning);
      color: var(--text-primary);
    }
    .sending-mode-banner .banner-inner {
      max-width: 1360px;
      width: 100%;
      margin: 0 auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 1rem;
      flex-wrap: wrap;
    }

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
    .page-title { font-size: 1.5rem; font-weight: 700; letter-spacing: -0.02em; display: flex; align-items: center; gap: 0.75rem; color: var(--text-primary); }
    .page-subtitle { color: var(--text-muted); font-size: 0.88rem; margin-top: 0.25rem; }

    /* Button sizing and focus states */
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      min-height: 44px;          /* WCAG 2.5.5 enhanced target */
      padding: 0.65rem 1.25rem;
      font-size: 1rem;
      font-weight: 600;
      border-radius: 8px;
      border: none;
      cursor: pointer;
      transition: all 0.2s;
      text-decoration: none;
    }
    .btn:hover { opacity: 0.92; text-decoration: none; }
    .btn-sm {
      min-height: 32px;          /* never below 24px (WCAG 2.5.8 minimum) */
      padding: 0.4rem 0.8rem;
      font-size: 0.9rem;
    }

    /* Visible focus on EVERY interactive element — required for keyboard use */
    .btn:focus-visible,
    button:focus-visible,
    a:focus-visible,
    input:focus-visible,
    select:focus-visible,
    textarea:focus-visible,
    summary:focus-visible,
    [tabindex]:focus-visible {
      outline: 2px solid var(--info);
      outline-offset: 2px;
    }

    .btn-primary { background: var(--btn-primary-bg); color: #ffffff; }
    .btn-success { background: var(--btn-success-bg); color: #ffffff; }
    .btn-warning { background: var(--btn-warning-bg); color: #ffffff; }
    .btn-danger { background: var(--btn-danger-bg); color: #ffffff; }
    .btn-purple { background: var(--btn-purple-bg); color: #ffffff; }
    .btn-secondary { background: var(--bg-elevated); color: var(--text-primary); border: 1px solid var(--border-strong); }
    .btn-secondary:hover { background: var(--bg-surface); }

    .card {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.25);
      margin-bottom: 1.5rem;
    }
    .card-title { font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 0.75rem; display: flex; justify-content: space-between; align-items: center; }
    .table-container { overflow-x: auto; border-radius: 8px; border: 1px solid var(--border); background: var(--bg-surface); }
    table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.88rem; }
    th { background: var(--bg-elevated); padding: 0.85rem 1rem; font-weight: 600; color: var(--text-muted); text-transform: uppercase; font-size: 0.75rem; letter-spacing: 0.05em; border-bottom: 1px solid var(--border); }
    td { padding: 0.85rem 1rem; border-bottom: 1px solid var(--border); color: var(--text-primary); vertical-align: middle; }
    tr:hover td { background: var(--bg-elevated); }

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
    .badge-blue { background: rgba(76, 141, 245, 0.15); color: var(--info); border: 1px solid rgba(76, 141, 245, 0.3); }
    .badge-green { background: rgba(63, 185, 80, 0.15); color: var(--success); border: 1px solid rgba(63, 185, 80, 0.3); }
    .badge-amber { background: rgba(210, 153, 34, 0.15); color: var(--warning); border: 1px solid rgba(210, 153, 34, 0.3); }
    .badge-purple { background: rgba(188, 140, 255, 0.15); color: var(--purple); border: 1px solid rgba(188, 140, 255, 0.3); }
    .badge-cyan { background: rgba(57, 197, 207, 0.15); color: var(--cyan); border: 1px solid rgba(57, 197, 207, 0.3); }
    .badge-red { background: rgba(248, 81, 73, 0.15); color: var(--danger); border: 1px solid rgba(248, 81, 73, 0.3); }
    .badge-gray { background: rgba(154, 167, 180, 0.15); color: var(--text-muted); border: 1px solid var(--border); }

    /* Match score visual bar */
    .score { display: inline-flex; align-items: center; gap: 0.5rem; }
    .score-track { width: 64px; height: 6px; border-radius: 3px; background: var(--border); overflow: hidden; }
    .score-fill  { height: 100%; border-radius: 3px; }
    .score-num   { font-size: 0.85rem; color: var(--text-muted); font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', monospace; font-weight: 600; }

    /* Signal chips and collapsible details */
    .chip {
      display: inline-block;
      padding: 0.2rem 0.55rem;
      margin: 0.15rem 0.2rem 0.15rem 0;
      font-size: 0.78rem;
      border-radius: 999px;
      background: var(--bg-elevated);
      border: 1px solid var(--border);
      color: var(--text-muted);
    }
    .chip-more {
      background: var(--bg-surface);
      border-color: var(--border-strong);
      color: var(--info);
      cursor: pointer;
      font-weight: 600;
      user-select: none;
    }
    details.chips-details {
      display: inline-block;
      vertical-align: middle;
    }
    details.chips-details summary::-webkit-details-marker {
      display: none;
    }
    details.chips-details summary {
      list-style: none;
    }

    /* Compact Score Pill */
    .score-pill {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0.15rem 0.5rem;
      border-radius: 999px;
      font-size: 0.76rem;
      font-weight: 700;
      font-family: 'JetBrains Mono', monospace;
      letter-spacing: -0.02em;
    }
    .score-pill.score-green { background: rgba(63, 185, 80, 0.18); color: var(--success); border: 1px solid rgba(63, 185, 80, 0.35); }
    .score-pill.score-amber { background: rgba(210, 153, 34, 0.18); color: var(--warning); border: 1px solid rgba(210, 153, 34, 0.35); }
    .score-pill.score-red   { background: rgba(248, 81, 73, 0.18); color: var(--danger); border: 1px solid rgba(248, 81, 73, 0.35); }

    /* Metadata Chip */
    .meta-chip {
      display: inline-flex;
      align-items: center;
      gap: 0.25rem;
      background: var(--bg-base);
      border: 1px solid var(--border);
      color: var(--text-muted);
      border-radius: 6px;
      padding: 0.18rem 0.5rem;
      font-size: 0.76rem;
    }

    /* Workflow Stepper */
    .workflow-stepper {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 0.85rem 1.5rem;
      margin-bottom: 2rem;
      overflow-x: auto;
    }
    .stepper-step {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      white-space: nowrap;
    }
    .stepper-num {
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: var(--bg-elevated);
      border: 1px solid var(--border-strong);
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--text-primary);
    }
    .stepper-step.active .stepper-num {
      background: var(--info);
      color: #FFFFFF;
      border-color: var(--info);
    }
    .stepper-label {
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--text-muted);
    }
    .stepper-step.active .stepper-label {
      color: var(--text-primary);
    }
    .stepper-divider {
      flex: 1;
      height: 2px;
      background: var(--border);
      min-width: 24px;
    }

    /* Stage Panel */
    .stage-panel {
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      margin-bottom: 2rem;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.25);
    }
    .stage-panel-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-bottom: 1rem;
      margin-bottom: 1.25rem;
      border-bottom: 1px solid var(--border);
      flex-wrap: wrap;
      gap: 0.75rem;
    }
    .stage-panel-title {
      font-size: 1.1rem;
      font-weight: 700;
      color: var(--text-primary);
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }
    .stage-panel-desc {
      font-size: 0.82rem;
      color: var(--text-muted);
      margin-top: 0.2rem;
    }

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
    .toast-success { background: #0F3319; border: 1px solid var(--success); color: var(--text-primary); }
    .toast-error { background: #3C1210; border: 1px solid var(--danger); color: var(--text-primary); }
    .modal-backdrop {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(15, 20, 25, 0.82);
      backdrop-filter: blur(4px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 200;
      padding: 1.5rem;
    }
    .modal {
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      border-radius: 14px;
      width: 100%;
      max-width: 620px;
      max-height: 90vh;
      overflow-y: auto;
      padding: 2rem;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
      animation: zoomIn 0.2s ease;
    }
    .modal-title { font-size: 1.25rem; font-weight: 700; margin-bottom: 0.5rem; color: var(--text-primary); }
    .modal-subtitle { font-size: 0.85rem; color: var(--text-muted); margin-bottom: 1.5rem; }
    .form-group { margin-bottom: 1.25rem; }
    label { display: block; font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 0.4rem; }
    input[type="text"], input[type="email"], input[type="password"], input[type="number"], select, textarea {
      width: 100%;
      background: var(--bg-base);
      border: 1px solid var(--border-strong);
      border-radius: 8px;
      padding: 0.65rem 0.9rem;
      color: var(--text-primary);
      font-size: 0.9rem;
      font-family: inherit;
    }
    input:focus, select:focus, textarea:focus {
      outline: none;
      border-color: var(--info);
      box-shadow: 0 0 0 3px rgba(76, 141, 245, 0.25);
    }
    .modal-actions { display: flex; justify-content: flex-end; gap: 0.75rem; margin-top: 1.75rem; }
    @keyframes slideUp { from { transform: translateY(20px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
    @keyframes zoomIn { from { transform: scale(0.95); opacity: 0; } to { transform: scale(1); opacity: 1; } }
"""

NAVBAR_TEMPLATE = """
  <div class="navbar-container">
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
        <button class="btn-logout btn-sm" id="logout-btn">Sign Out</button>
      </div>
    </header>
    <div id="sending-mode-banner" class="sending-mode-banner mode-test" role="status" aria-live="polite">
      <div class="banner-inner">
        <span id="sending-mode-label">🧪 &nbsp;TEST MODE — no real emails are sent.</span>
        <span id="sending-mode-caps">0 of 10 sends used today</span>
      </div>
    </div>
  </div>
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

  function renderScoreBar(rawScore) {
    const score = Math.max(0, Math.min(100, Math.round(Number(rawScore) || 0)));
    let fill = 'var(--danger)';
    if (score >= 70) fill = 'var(--success)';
    else if (score >= 50) fill = 'var(--warning)';

    return `<div class="score" role="img" aria-label="Match score ${score} out of 100">` +
      `<div class="score-track"><div class="score-fill" style="width:${score}%; background:${fill};"></div></div>` +
      `<span class="score-num">${score}</span>` +
    `</div>`;
  }

  function renderStatusBadge(status) {
    const s = String(status || '').toLowerCase().trim();
    switch (s) {
      case 'pending':
      case 'waiting_for_review':
        return '<span class="badge badge-amber"><span aria-hidden="true">◷</span> Needs review</span>';
      case 'approved':
        return '<span class="badge badge-green"><span aria-hidden="true">✓</span> Approved</span>';
      case 'sent':
        return '<span class="badge badge-green"><span aria-hidden="true">✓</span> Sent</span>';
      case 'rejected':
        return '<span class="badge badge-red"><span aria-hidden="true">✕</span> Rejected</span>';
      case 'failed':
      case 'error':
        return '<span class="badge badge-red"><span aria-hidden="true">⚠</span> Error</span>';
      case 'researching':
      case 'running':
      case 'queued':
      case 'in_progress':
      case 'processing':
        return '<span class="badge badge-blue"><span aria-hidden="true">◌</span> In progress</span>';
      case 'waiting_for_delivery':
        return '<span class="badge badge-purple"><span aria-hidden="true">✓</span> Ready for Delivery</span>';
      case 'staged':
        return '<span class="badge badge-cyan"><span aria-hidden="true">🛡</span> Staged</span>';
      case 'selected':
        return '<span class="badge badge-blue"><span aria-hidden="true">✓</span> Selected</span>';
      case 'discovered':
        return '<span class="badge badge-gray"><span aria-hidden="true">◌</span> Discovered</span>';
      case 'contacted':
        return '<span class="badge badge-green"><span aria-hidden="true">✓</span> Contacted</span>';
      case 'blocked_safety':
        return '<span class="badge badge-red"><span aria-hidden="true">⚠</span> Blocked Safety</span>';
      case 'valid':
        return '<span class="badge badge-green"><span aria-hidden="true">✓</span> Valid</span>';
      case 'invalid':
        return '<span class="badge badge-red"><span aria-hidden="true">✕</span> Invalid</span>';
      case 'active':
        return '<span class="badge badge-green"><span aria-hidden="true">●</span> Active</span>';
      case 'draft':
        return '<span class="badge badge-blue"><span aria-hidden="true">◌</span> Draft</span>';
      case 'completed':
        return '<span class="badge badge-green"><span aria-hidden="true">✓</span> Completed</span>';
      case 'passed':
        return '<span class="badge badge-green"><span aria-hidden="true">✓</span> Passed</span>';
      case 'blocked':
        return '<span class="badge badge-red"><span aria-hidden="true">✕</span> Blocked</span>';
      case 'test':
        return '<span class="badge badge-purple"><span aria-hidden="true">🧪</span> Test</span>';
      case 'live':
        return '<span class="badge badge-amber"><span aria-hidden="true">⚡</span> Live</span>';
      case 'healthy':
        return '<span class="badge badge-green"><span aria-hidden="true">●</span> Healthy</span>';
      case 'skipped':
        return '<span class="badge badge-gray"><span aria-hidden="true">↷</span> Skipped</span>';
      default:
        return `<span class="badge badge-gray">${escapeHtml(status || '-')}</span>`;
    }
  }

  function renderSignalChips(signals) {
    if (!signals || !Array.isArray(signals) || signals.length === 0) {
      return '<span style="color:var(--text-muted);font-size:0.75rem;">-</span>';
    }
    const visible = signals.slice(0, 4);
    const extra = signals.slice(4);
    let html = visible.map(s => `<span class="chip">${escapeHtml(s)}</span>`).join('');
    if (extra.length > 0) {
      const extraHtml = extra.map(s => `<span class="chip">${escapeHtml(s)}</span>`).join('');
      html += `<details class="chips-details">` +
        `<summary class="chip chip-more">+${extra.length} more</summary>` +
        `<span>${extraHtml}</span>` +
      `</details>`;
    }
    return html;
  }

  async function updateSendingModeBanner(cachedStats = null) {
    const bannerEl = document.getElementById('sending-mode-banner');
    if (!bannerEl) return;
    try {
      let healthData = null;
      let statsData = cachedStats;
      const promises = [
        fetch('/api/v1/health').then(r => r.ok ? r.json() : null).catch(() => null)
      ];
      if (!statsData) {
        promises.push(fetch('/api/v1/dashboard/stats').then(r => r.ok ? r.json() : null).catch(() => null));
      }
      const results = await Promise.all(promises);
      healthData = results[0];
      if (!statsData && results.length > 1) {
        statsData = results[1];
      }

      const deliveryMode = (healthData && healthData.delivery_mode) ? healthData.delivery_mode.toLowerCase() : 'stage';
      const isDryRun = healthData ? Boolean(healthData.dry_run) : true;
      const isLive = (deliveryMode === 'live' && !isDryRun);

      let dayUsed = 0;
      let dayMax = 10;
      if (statsData && statsData.volume_caps) {
        dayUsed = statsData.volume_caps.sends_today ?? 0;
        dayMax = statsData.volume_caps.max_day ?? 10;
      }

      const modeLabelEl = document.getElementById('sending-mode-label');
      const capsEl = document.getElementById('sending-mode-caps');

      if (isLive) {
        bannerEl.className = 'sending-mode-banner mode-live';
        if (modeLabelEl) modeLabelEl.textContent = '⚡  LIVE MODE — emails go to real people.';
      } else {
        bannerEl.className = 'sending-mode-banner mode-test';
        if (modeLabelEl) modeLabelEl.textContent = '🧪  TEST MODE — no real emails are sent.';
      }
      if (capsEl) {
        capsEl.textContent = `${dayUsed} of ${dayMax} sends used today`;
      }
    } catch (e) {
      console.warn('Sending mode banner update skipped:', e);
    }
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
    updateSendingModeBanner();
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
      --bg-base:      #0F1419;
      --bg-surface:   #171C22;
      --bg-elevated:  #1E252D;
      --border:       #2A323C;
      --border-strong:#484F58;
      --text-primary: #E6EDF3;
      --text-muted:   #9AA7B4;
      --info:         #4C8DF5;
      --danger:       #F85149;
      --btn-primary-bg: #1F6FEB;
      --btn-danger-bg:  #DA3633;
      --card-bg:      var(--bg-surface);
      --card-border:  var(--border);
      --text-main:    var(--text-primary);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
      background: radial-gradient(circle at 50% 20%, var(--bg-surface) 0%, var(--bg-base) 70%);
      color: var(--text-primary);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1.5rem;
    }
    .login-container {
      width: 100%;
      max-width: 420px;
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 2.5rem;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6), 0 0 40px rgba(31, 111, 235, 0.2);
    }
    .header { text-align: center; margin-bottom: 2rem; }
    .header h1 { font-size: 1.6rem; font-weight: 700; margin-bottom: 0.5rem; letter-spacing: -0.02em; color: var(--text-primary); }
    .header p { color: var(--text-muted); font-size: 0.88rem; }
    .form-group { margin-bottom: 1.25rem; }
    label { display: block; font-size: 0.82rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 0.5rem; }
    input[type="email"], input[type="password"] {
      width: 100%;
      min-height: 44px;
      background: var(--bg-base);
      border: 1px solid var(--border-strong);
      border-radius: 8px;
      padding: 0.75rem 1rem;
      color: var(--text-primary);
      font-size: 0.95rem;
      transition: all 0.2s ease;
    }
    input[type="email"]:focus-visible, input[type="password"]:focus-visible, .btn-submit:focus-visible {
      outline: 2px solid var(--info);
      outline-offset: 2px;
    }
    .btn-submit {
      width: 100%;
      min-height: 44px;
      background: var(--btn-primary-bg);
      color: #ffffff;
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
      background: #3C1210;
      border: 1px solid var(--danger);
      color: var(--text-primary);
      padding: 0.75rem 1rem;
      border-radius: 8px;
      font-size: 0.85rem;
      margin-bottom: 1.25rem;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.25rem 0.6rem;
      background: rgba(76, 141, 245, 0.15);
      color: var(--info);
      border: 1px solid rgba(76, 141, 245, 0.3);
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      margin-bottom: 0.75rem;
    }
    code {
      background: var(--bg-elevated);
      color: var(--info);
      border: 1px solid var(--border);
      padding: 0.15rem 0.35rem;
      border-radius: 4px;
      font-size: 0.76rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
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
    <div class="bootstrap-hint" style="margin-top: 1.5rem; text-align: center; font-size: 0.8rem; color: var(--text-muted); border-top: 1px solid var(--border); padding-top: 1rem; line-height: 1.45;">
      First deployment? Set <code>BOOTSTRAP_ADMIN_EMAIL</code> and <code>BOOTSTRAP_ADMIN_PASSWORD</code> in <code>.env</code> to initialize operator access.
    </div>
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
    .primary-metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 1.25rem;
      margin-bottom: 1.25rem;
    }}
    .metric-card {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.35rem;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: all 0.2s ease;
    }}
    .metric-card.primary-card {{
      min-height: 140px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }}
    .metric-card.primary-card:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35);
    }}
    .metric-label {{ font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); font-weight: 700; }}
    .metric-value {{ font-size: 2.2rem; font-weight: 700; margin: 0.5rem 0 0.25rem 0; font-family: 'JetBrains Mono', monospace; }}
    .metric-footer {{ display: flex; justify-content: space-between; align-items: center; font-size: 0.78rem; color: var(--text-muted); margin-top: 0.5rem; }}
    .metric-card.attention-amber {{ border-color: rgba(210, 153, 34, 0.5); background: linear-gradient(180deg, rgba(210, 153, 34, 0.1) 0%, var(--bg-surface) 100%); }}
    .metric-card.attention-purple {{ border-color: rgba(188, 140, 255, 0.5); background: linear-gradient(180deg, rgba(188, 140, 255, 0.1) 0%, var(--bg-surface) 100%); }}
    .metric-card.attention-green {{ border-color: rgba(63, 185, 80, 0.5); background: linear-gradient(180deg, rgba(63, 185, 80, 0.1) 0%, var(--bg-surface) 100%); }}
    .metric-card.attention-red {{ border-color: rgba(248, 81, 73, 0.5); background: linear-gradient(180deg, rgba(248, 81, 73, 0.1) 0%, var(--bg-surface) 100%); }}

    /* Progressive Disclosure */
    .disclosure-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 2rem;
      padding: 0.25rem 0.25rem;
    }}
    .toggle-metrics-btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.5rem;
      background: var(--bg-surface);
      border: 1px solid var(--border-strong);
      color: var(--text-primary);
      padding: 0.45rem 0.9rem;
      border-radius: 8px;
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }}
    .toggle-metrics-btn:hover {{
      background: var(--bg-elevated);
      border-color: var(--info);
    }}
    .secondary-metrics-panel {{
      margin-bottom: 2rem;
      animation: slideDown 0.25s ease;
    }}
    .secondary-metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 1rem;
    }}
    .secondary-card {{
      padding: 1rem 1.25rem;
      border-radius: 10px;
    }}
    .secondary-card .metric-value {{
      font-size: 1.65rem;
      margin: 0.35rem 0 0.15rem 0;
    }}
    @keyframes slideDown {{
      from {{ opacity: 0; transform: translateY(-8px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    .gauges-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 1.5rem;
      margin-bottom: 2rem;
    }}
    .gauge-bar-bg {{ background: var(--border); height: 8px; border-radius: 9999px; overflow: hidden; margin: 0.75rem 0; }}
    .gauge-fill {{ height: 100%; border-radius: 9999px; transition: width 0.5s ease; }}
    .attention-tabs {{ display: flex; gap: 0.5rem; margin-bottom: 1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }}
    .tab-btn {{ background: transparent; border: none; color: var(--text-muted); padding: 0.5rem 1rem; font-size: 0.88rem; font-weight: 600; cursor: pointer; border-radius: 6px; min-height: 36px; }}
    .tab-btn.active {{ color: var(--info); background: rgba(76, 141, 245, 0.12); }}
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

    <!-- Primary Action Hero Metrics (Top 4 Max) -->
    <div class="primary-metrics-grid">
      <div class="metric-card attention-amber primary-card" onclick="window.location.href='/review'" style="cursor:pointer;" title="Open Review Queue">
        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
          <span class="metric-label" style="color:var(--warning)">Needs Review</span>
          <span class="badge badge-amber"><span aria-hidden="true">◷</span> Action</span>
        </div>
        <div class="metric-value" style="color:var(--warning)" id="stat-waiting-review">-</div>
        <div class="metric-footer">
          <span>Human edits required before delivery</span>
          <span style="color:var(--warning); font-weight:600;">Open &rarr;</span>
        </div>
      </div>

      <div class="metric-card attention-purple primary-card" onclick="window.location.href='/deliveries'" style="cursor:pointer;" title="Inspect Deliveries">
        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
          <span class="metric-label" style="color:var(--purple)">Ready to Send</span>
          <span class="badge badge-purple"><span aria-hidden="true">✓</span> Approved</span>
        </div>
        <div class="metric-value" style="color:var(--purple)" id="stat-waiting-delivery">-</div>
        <div class="metric-footer">
          <span>Approved drafts waiting for dispatch</span>
          <span style="color:var(--purple); font-weight:600;">Inspect &rarr;</span>
        </div>
      </div>

      <div class="metric-card attention-green primary-card">
        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
          <span class="metric-label" style="color:var(--success)">Sent Today</span>
          <span class="badge badge-green" id="primary-sent-status"><span aria-hidden="true">✓</span> Active</span>
        </div>
        <div class="metric-value" style="color:var(--success)" id="stat-sent-today">-</div>
        <div class="metric-footer">
          <span id="stat-sent-today-sub">Rolling 24h unified cap</span>
        </div>
      </div>

      <div class="metric-card attention-red primary-card" onclick="switchAttentionTab('failed')" style="cursor:pointer;" title="Triage Failed Runs">
        <div style="display:flex; justify-content:space-between; align-items:flex-start;">
          <span class="metric-label" style="color:var(--danger)">Errors</span>
          <span class="badge badge-red"><span aria-hidden="true">⚠</span> Audit</span>
        </div>
        <div class="metric-value" style="color:var(--danger)" id="stat-failed">-</div>
        <div class="metric-footer">
          <span>Failed pipeline runs needing audit</span>
          <span style="color:var(--danger); font-weight:600;">Triage &darr;</span>
        </div>
      </div>
    </div>

    <!-- Progressive Disclosure Trigger -->
    <div class="disclosure-bar">
      <button type="button" class="toggle-metrics-btn" id="toggle-metrics-btn" onclick="toggleSecondaryMetrics()">
        <span id="toggle-metrics-icon">▾</span> <span id="toggle-metrics-text">Show All Pipeline Metrics (5)</span>
      </button>
      <span style="font-size:0.78rem; color:var(--text-muted)">Secondary metrics & pipeline funnel</span>
    </div>

    <!-- Collapsible Secondary Metrics Drawer (Revealed on 1 Click) -->
    <div id="secondary-metrics-panel" class="secondary-metrics-panel" style="display: none;">
      <div class="secondary-metrics-grid">
        <div class="metric-card secondary-card">
          <span class="metric-label">Active Campaigns</span>
          <div class="metric-value" id="stat-campaigns">-</div>
          <span style="font-size:0.75rem; color:var(--text-muted)">Target outreach tracks</span>
        </div>
        <div class="metric-card secondary-card">
          <span class="metric-label">Discovered Pool</span>
          <div class="metric-value" id="stat-discovered">-</div>
          <span style="font-size:0.75rem; color:var(--text-muted)">Total candidate accounts</span>
        </div>
        <div class="metric-card secondary-card">
          <span class="metric-label">Selected</span>
          <div class="metric-value" id="stat-selected">-</div>
          <span style="font-size:0.75rem; color:var(--text-muted)">Enqueued / Approved pool</span>
        </div>
        <div class="metric-card secondary-card">
          <span class="metric-label">In-Flight Processing</span>
          <div class="metric-value" id="stat-processing">-</div>
          <span style="font-size:0.75rem; color:var(--text-muted)">Active enrichment jobs</span>
        </div>
        <div class="metric-card secondary-card">
          <span class="metric-label">Staged (Dry-Run)</span>
          <div class="metric-value" style="color:var(--cyan)" id="stat-staged">-</div>
          <span style="font-size:0.75rem; color:var(--text-muted)">Saved to disk safely</span>
        </div>
        <div class="metric-card secondary-card">
          <span class="metric-label">All-Time Sent</span>
          <div class="metric-value" style="color:var(--success)" id="stat-sent">-</div>
          <span style="font-size:0.75rem; color:var(--text-muted)">Historical live dispatches</span>
        </div>
      </div>
    </div>

    <!-- Volume Caps and Safety Invariant Gauges -->
    <div class="gauges-grid">
      <div class="card" style="margin-bottom:0">
        <div class="card-title">
          <span>Daily Volume Cap (Unified)</span>
          <span class="badge badge-green" id="daily-cap-status"><span aria-hidden="true">✓</span> Safe</span>
        </div>
        <div style="font-size: 1.6rem; font-weight: 700; font-family: 'JetBrains Mono', monospace;" id="daily-cap-text">0 / 10</div>
        <div class="gauge-bar-bg">
          <div class="gauge-fill" id="daily-cap-bar" style="width: 0%; background: var(--success);"></div>
        </div>
        <p style="font-size: 0.8rem; color: var(--text-muted);">Max 10 dispatches per rolling 24h window (CLI + Web unified dedupe).</p>
      </div>

      <div class="card" style="margin-bottom:0">
        <div class="card-title">
          <span>Weekly Volume Cap (Unified)</span>
          <span class="badge badge-blue" id="weekly-cap-status"><span aria-hidden="true">✓</span> Safe</span>
        </div>
        <div style="font-size: 1.6rem; font-weight: 700; font-family: 'JetBrains Mono', monospace;" id="weekly-cap-text">0 / 50</div>
        <div class="gauge-bar-bg">
          <div class="gauge-fill" id="weekly-cap-bar" style="width: 0%; background: var(--info);"></div>
        </div>
        <p style="font-size: 0.8rem; color: var(--text-muted);">Max 50 dispatches per rolling 7-day window across all channels.</p>
      </div>

      <div class="card" style="margin-bottom:0">
        <div class="card-title">
          <span>Server Dispatch Mode</span>
          <span class="badge badge-cyan" id="mode-badge"><span aria-hidden="true">🛡</span> Dry-Run Staging</span>
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
        <span class="badge badge-amber" id="attention-total-badge"><span aria-hidden="true">◷</span> 0 items</span>
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
        updateSendingModeBanner(statsData);

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

        document.getElementById('stat-sent-today').textContent = `${{dayUsed}} / ${{dayMax}}`;
        document.getElementById('stat-sent-today-sub').textContent = `${{dayUsed}} of ${{dayMax}} max daily cap used`;

        document.getElementById('daily-cap-text').textContent = `${{dayUsed}} / ${{dayMax}}`;
        const dayPct = Math.min(100, Math.round((dayUsed / dayMax) * 100));
        const dayBar = document.getElementById('daily-cap-bar');
        dayBar.style.width = dayPct + '%';
        if (dayPct >= 100) {{
          dayBar.style.background = 'var(--danger)';
          document.getElementById('daily-cap-status').innerHTML = '<span aria-hidden="true">⚠</span> Cap Reached';
          document.getElementById('daily-cap-status').className = 'badge badge-red';
        }} else if (dayPct >= 80) {{
          dayBar.style.background = 'var(--warning)';
          document.getElementById('daily-cap-status').innerHTML = '<span aria-hidden="true">◷</span> Approaching Cap';
          document.getElementById('daily-cap-status').className = 'badge badge-amber';
        }} else {{
          dayBar.style.background = 'var(--success)';
          document.getElementById('daily-cap-status').innerHTML = '<span aria-hidden="true">✓</span> Safe';
          document.getElementById('daily-cap-status').className = 'badge badge-green';
        }}

        document.getElementById('weekly-cap-text').textContent = `${{weekUsed}} / ${{weekMax}}`;
        const weekPct = Math.min(100, Math.round((weekUsed / weekMax) * 100));
        const weekBar = document.getElementById('weekly-cap-bar');
        weekBar.style.width = weekPct + '%';
        if (weekPct >= 100) {{
          weekBar.style.background = 'var(--danger)';
          document.getElementById('weekly-cap-status').innerHTML = '<span aria-hidden="true">⚠</span> Cap Reached';
          document.getElementById('weekly-cap-status').className = 'badge badge-red';
        }} else {{
          weekBar.style.background = 'var(--info)';
          document.getElementById('weekly-cap-status').innerHTML = '<span aria-hidden="true">✓</span> Safe';
          document.getElementById('weekly-cap-status').className = 'badge badge-blue';
        }}

        // Attention Counts
        const revItems = statsData.needs_attention?.waiting_for_review || [];
        const delItems = statsData.needs_attention?.waiting_for_delivery || [];
        const failItems = statsData.needs_attention?.failed_runs || [];

        document.getElementById('count-att-review').textContent = revItems.length;
        document.getElementById('count-att-delivery').textContent = delItems.length;
        document.getElementById('count-att-failed').textContent = failItems.length;
        document.getElementById('attention-total-badge').innerHTML = `<span aria-hidden="true">◷</span> ${{revItems.length + delItems.length + failItems.length}} items`;

        // Render Waiting for Review Table
        const revTbody = document.getElementById('attention-review-tbody');
        if (revItems.length === 0) {{
          revTbody.innerHTML = '<tr><td colspan="5" class="empty-state">No drafts currently waiting for human review.</td></tr>';
        }} else {{
          revTbody.innerHTML = revItems.map(item => {{
            let detailHtml = `<span class="badge badge-blue">${{escapeHtml(item.detail)}}</span>`;
            const m = (item.detail || '').match(/Match Score:[ \\t]*([0-9]+)\\/100/i);
            if (m) {{
              detailHtml = renderScoreBar(m[1]);
            }}
            return `
              <tr>
                <td><strong>${{escapeHtml(item.company_name)}}</strong><br><span style="color:var(--text-muted);font-size:0.75rem">${{escapeHtml(item.domain)}}</span></td>
                <td>${{escapeHtml(item.campaign_name)}}</td>
                <td>${{detailHtml}}</td>
                <td style="color:var(--text-muted);font-size:0.8rem">${{item.timestamp ? new Date(item.timestamp).toLocaleTimeString() : '-'}}</td>
                <td><a href="/review" class="btn btn-warning btn-sm">Review Draft</a></td>
              </tr>
            `;
          }}).join('');
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
              <td>${{renderStatusBadge('waiting_for_delivery')}}</td>
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
              <td><span class="badge badge-red" title="${{escapeHtml(item.detail)}}"><span aria-hidden="true">⚠</span> ${{escapeHtml((item.detail || '').slice(0, 45))}}...</span></td>
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

    function toggleSecondaryMetrics() {{
      const panel = document.getElementById('secondary-metrics-panel');
      const icon = document.getElementById('toggle-metrics-icon');
      const text = document.getElementById('toggle-metrics-text');
      if (panel.style.display === 'none' || panel.style.display === '') {{
        panel.style.display = 'block';
        icon.textContent = '▴';
        text.textContent = 'Hide Secondary Pipeline Metrics';
      }} else {{
        panel.style.display = 'none';
        icon.textContent = '▾';
        text.textContent = 'Show All Pipeline Metrics (5)';
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
                <button class="btn btn-primary" onclick="openCreateModal()">Create Your First Campaign</button>
              </td>
            </tr>
          `;
          return;
        }}

        tbody.innerHTML = campaigns.map(c => `
          <tr>
            <td>
              <a href="/campaigns/${{c.id}}" style="font-weight:700; font-size:0.95rem; color:var(--text-primary);">${{escapeHtml(c.name)}}</a>
              <div style="font-size:0.75rem; color:var(--text-muted); margin-top:0.2rem;">${{escapeHtml((c.objective || '').slice(0, 50))}}...</div>
            </td>
            <td>${{renderStatusBadge(c.status)}}</td>
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
                <span class="badge badge-gray" title="Discovered Companies"><span aria-hidden="true">◌</span> ${{c.total_companies || 0}} comps</span>
                <span class="badge badge-blue" title="Selected Companies"><span aria-hidden="true">✓</span> ${{c.selected_companies || 0}} sel</span>
                <span class="badge badge-amber" title="Waiting Review"><span aria-hidden="true">◷</span> ${{c.waiting_for_review_count || 0}} rev</span>
                <span class="badge badge-purple" title="Waiting Delivery"><span aria-hidden="true">✓</span> ${{c.waiting_for_delivery_count || 0}} del</span>
                <span class="badge badge-green" title="Delivered Sent"><span aria-hidden="true">✓</span> ${{c.sent_count || 0}} sent</span>
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
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 1.25rem;
    }}
    .targeting-item-label {{ font-size: 0.72rem; text-transform: uppercase; color: var(--text-muted); font-weight: 700; letter-spacing: 0.05em; }}
    .targeting-item-val {{ font-size: 0.92rem; color: var(--text-primary); font-weight: 600; margin-top: 0.35rem; }}

    /* Discovery Action Box in Stage 2 */
    .discovery-action-box {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.25rem 1.5rem;
      flex-wrap: wrap;
      gap: 1rem;
    }}

    /* Candidate Cards in Stage 3 */
    .candidate-cards-list {{
      display: flex;
      flex-direction: column;
      gap: 0.85rem;
      margin-top: 1rem;
    }}
    .candidate-card {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.15rem 1.35rem;
      display: grid;
      grid-template-columns: auto auto 1fr auto;
      gap: 1.25rem;
      align-items: center;
      transition: all 0.2s ease;
      position: relative;
    }}
    .candidate-card:hover {{
      background: var(--bg-elevated);
      border-color: var(--border-strong);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }}
    .candidate-card.selected {{
      border-color: var(--info);
      background: rgba(76, 141, 245, 0.07);
      box-shadow: 0 0 0 1px rgba(76, 141, 245, 0.35);
    }}
    .candidate-card.contacted {{
      opacity: 0.55;
    }}
    .candidate-card-checkbox {{
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .candidate-card-checkbox input[type="checkbox"] {{
      width: 20px;
      height: 20px;
      cursor: pointer;
      accent-color: var(--info);
    }}
    .candidate-card-score {{
      display: flex;
      flex-direction: column;
      align-items: center;
      min-width: 76px;
      padding: 0.4rem 0.6rem;
      background: var(--bg-base);
      border: 1px solid var(--border);
      border-radius: 8px;
    }}
    .candidate-card-main {{
      display: flex;
      flex-direction: column;
      gap: 0.45rem;
      min-width: 0;
    }}
    .candidate-card-title-row {{
      display: flex;
      align-items: baseline;
      gap: 0.75rem;
      flex-wrap: wrap;
    }}
    .candidate-company-name {{
      font-size: 1.05rem;
      font-weight: 700;
      color: var(--text-primary);
    }}
    .candidate-domain-link {{
      font-size: 0.8rem;
      color: var(--info);
      text-decoration: none;
    }}
    .candidate-domain-link:hover {{
      text-decoration: underline;
    }}
    .candidate-card-meta-row {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      flex-wrap: wrap;
      font-size: 0.78rem;
      color: var(--text-muted);
    }}
    .candidate-card-signals-row {{
      display: flex;
      align-items: center;
      gap: 0.35rem;
      flex-wrap: wrap;
      margin-top: 0.15rem;
    }}
    .candidate-card-status {{
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 0.5rem;
      min-width: 100px;
    }}

    .toolbar {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 0.75rem; }}
    .filters-group {{ display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }}
    .selection-banner {{
      background: rgba(76, 141, 245, 0.1);
      border: 1px solid rgba(76, 141, 245, 0.25);
      border-radius: 8px;
      padding: 0.85rem 1.25rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1rem;
    }}
    .tag-pill {{
      display: inline-block;
      background: var(--bg-elevated);
      color: var(--text-muted);
      border: 1px solid var(--border);
      border-radius: 4px;
      padding: 0.15rem 0.4rem;
      font-size: 0.7rem;
      margin: 0.1rem;
    }}
    .timeline-item {{
      position: relative;
      padding-left: 1.5rem;
      padding-bottom: 1.25rem;
      border-left: 2px solid var(--border-strong);
    }}
    .timeline-item:last-child {{ border-left: 2px solid transparent; padding-bottom: 0; }}
    .timeline-dot {{
      position: absolute;
      left: -6px;
      top: 2px;
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background: var(--info);
    }}
  </style>
</head>
<body>
  {navbar}

  <main class="main-content">
    <div style="margin-bottom: 1rem;">
      <a href="/campaigns" style="color:var(--text-muted); font-size:0.85rem;">&larr; Back to Campaigns</a>
    </div>

    <div class="page-header" style="margin-bottom: 1.5rem;">
      <div>
        <div style="display:flex; align-items:center; gap: 0.75rem;">
          <h1 class="page-title" id="campaign-title">Loading Campaign...</h1>
          <span id="campaign-status-container"><span class="badge badge-blue" id="campaign-status-badge"><span aria-hidden="true">◌</span> Draft</span></span>
        </div>
        <p class="page-subtitle" id="campaign-desc">-</p>
      </div>
    </div>

    <!-- 3-Stage Workflow Stepper -->
    <div class="workflow-stepper">
      <div class="stepper-step active">
        <span class="stepper-num">1</span>
        <span class="stepper-label">Set Criteria</span>
      </div>
      <div class="stepper-divider"></div>
      <div class="stepper-step active">
        <span class="stepper-num">2</span>
        <span class="stepper-label">Find Companies</span>
      </div>
      <div class="stepper-divider"></div>
      <div class="stepper-step active">
        <span class="stepper-num">3</span>
        <span class="stepper-label">Review & Select</span>
      </div>
    </div>

    <!-- Stage 1 Panel: Targeting Criteria & ICP Spec -->
    <div class="stage-panel">
      <div class="stage-panel-header">
        <div>
          <div class="stage-panel-title"><span>🎯</span> Stage 1: Targeting Criteria & ICP Spec</div>
          <p class="stage-panel-desc">Defined search parameters for lead qualification, scoring, and leadership discovery</p>
        </div>
        <span class="badge badge-blue"><span aria-hidden="true">✓</span> Active Criteria</span>
      </div>

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

      <div style="background:var(--bg-base); border:1px solid var(--border); border-radius:8px; padding:0.85rem 1.25rem; margin-top:1rem; font-size:0.82rem; line-height:1.5; color:var(--text-secondary);">
        <div style="font-weight:600; color:var(--text-primary); margin-bottom:0.35rem;">
          How targeting is applied for this campaign
        </div>
        <div style="display:flex; flex-wrap:wrap; gap:1.25rem;">
          <div><strong style="color:var(--text-primary);">Search filters:</strong> Location, industry, and company size narrow the initial company search.</div>
          <div><strong style="color:var(--text-primary);">Match scoring:</strong> Funding stage and technologies determine relevance and rank candidates in the list below.</div>
          <div><strong style="color:var(--text-primary);">Leadership search:</strong> Target roles guide who we look for when identifying verified technical leaders.</div>
        </div>
      </div>
    </div>

    <!-- Stage 2 Panel: Company Discovery Engine -->
    <div class="stage-panel">
      <div class="stage-panel-header">
        <div>
          <div class="stage-panel-title"><span>🔍</span> Stage 2: Candidate Discovery Engine</div>
          <p class="stage-panel-desc">Query Apollo.io live targeting adapter to pull verified company leads</p>
        </div>
        <span id="comps-count-badge" class="badge badge-gray">0 candidates in pool</span>
      </div>

      <div class="discovery-action-box">
        <div>
          <p style="font-size:0.88rem; color:var(--text-primary); font-weight:600; margin-bottom:0.25rem;">Fetch New Candidate Batch</p>
          <p style="font-size:0.8rem; color:var(--text-muted); margin:0;">Discovered leads are automatically deduplicated against historical dispatches and existing database records.</p>
        </div>
        <div style="display:flex; gap:0.6rem; align-items:center;">
          <select id="discovery-limit" style="width: auto; padding: 0.5rem 0.75rem; min-height: 40px;">
            <option value="5">Discover 5 Companies</option>
            <option value="10" selected>Discover 10 Companies</option>
            <option value="20">Discover 20 Companies</option>
          </select>
          <button class="btn btn-primary" id="run-discover-btn" onclick="triggerDiscovery()" style="min-height: 40px;">⚡ Run Discovery</button>
        </div>
      </div>
    </div>

    <!-- Stage 3 Panel: Candidate Selection & Enqueue -->
    <div class="stage-panel">
      <div class="stage-panel-header">
        <div>
          <div class="stage-panel-title"><span>📋</span> Stage 3: Candidate Review, Scoring & Selection</div>
          <p class="stage-panel-desc">Deterministic 100-point ranking math. Select companies for background enrichment.</p>
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
          <button class="btn btn-secondary" onclick="saveCurrentSelection()">Save Selection</button>
          <button class="btn btn-success" id="enqueue-btn" onclick="enqueueSelectedRuns()">Enqueue Selected Companies &rarr;</button>
        </div>
      </div>

      <!-- Filter Toolbar -->
      <div class="toolbar">
        <div class="filters-group">
          <input type="text" id="filter-search" placeholder="Search domain or company..." style="width: 240px;" oninput="applyFilters()">
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
        <div style="display:flex; gap:0.5rem; align-items:center;">
          <button class="btn btn-secondary btn-sm" onclick="selectAllFiltered(true)">Select All Visible</button>
          <button class="btn btn-secondary btn-sm" onclick="selectAllFiltered(false)">Deselect All</button>
        </div>
      </div>

      <!-- Candidate Discovery Cards List -->
      <div id="candidates-container" class="candidate-cards-list">
        <div class="empty-state" style="padding: 2.5rem; border: 1px dashed var(--border); border-radius: 8px;">
          No candidates discovered yet. Click <strong>Run Discovery</strong> above to find target companies.
        </div>
      </div>
      <table style="display:none;"><tbody id="candidates-tbody"></tbody></table>
    </div>

    <!-- Stage 4 / Pipeline Runs Progress Section -->
    <div class="stage-panel" style="margin-top: 2rem;">
      <div class="stage-panel-header">
        <div>
          <div class="stage-panel-title"><span>⚙️</span> Pipeline Execution Activity</div>
          <p class="stage-panel-desc">Real-time status of enqueued background enrichment, leader discovery, and draft generation</p>
        </div>
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
      <div style="display:grid; grid-template-columns: 1fr 1fr; gap:1rem; background:var(--bg-base); border:1px solid var(--border); padding:1rem; border-radius:8px; margin-bottom:1.5rem;">
        <div>
          <span class="targeting-item-label">Verified Contact</span>
          <div style="font-weight:600; font-size:0.9rem; color:var(--text-primary);" id="m-run-person">Searching...</div>
          <div style="font-size:0.75rem; color:var(--info);" id="m-run-email">-</div>
        </div>
        <div>
          <span class="targeting-item-label">Review / Delivery</span>
          <div style="font-weight:600; font-size:0.9rem; color:var(--text-primary);" id="m-run-review">Pending Review</div>
          <div style="font-size:0.75rem; color:var(--success);" id="m-run-delivery">-</div>
        </div>
      </div>

      <!-- Draft Preview if available -->
      <div id="m-run-draft-section" style="margin-bottom:1.5rem; display:none;">
        <span class="targeting-item-label">Generated Outreach Draft</span>
        <div style="background:var(--bg-base); border:1px solid var(--border); border-radius:8px; padding:1rem; margin-top:0.4rem;">
          <div style="font-weight:600; margin-bottom:0.5rem; font-size:0.85rem;" id="m-draft-subject"></div>
          <div style="font-size:0.8rem; color:var(--text-primary); line-height:1.5; white-space:pre-wrap;" id="m-draft-body"></div>
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
        document.getElementById('campaign-status-container').innerHTML = renderStatusBadge(camp.status);
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
      const container = document.getElementById('candidates-container');
      const tbody = document.getElementById('candidates-tbody');

      if (comps.length === 0) {{
        const emptyHtml = '<div class="empty-state" style="padding: 2.5rem; border: 1px dashed var(--border); border-radius: 8px;">No matching candidate companies. Try adjusting filters or click <strong>Run Discovery</strong> above.</div>';
        if (container) container.innerHTML = emptyHtml;
        if (tbody) tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No matching candidate companies.</td></tr>';
        return;
      }}

      if (container) {{
        container.innerHTML = comps.map(c => {{
          const isContacted = c.selection_status === 'contacted';
          const isChecked = selectedIds.has(c.id);
          const score = Math.max(0, Math.min(100, Math.round(Number(c.match_score) || 0)));
          let scorePillClass = 'score-red';
          if (score >= 70) scorePillClass = 'score-green';
          else if (score >= 50) scorePillClass = 'score-amber';

          const allSignals = (c.technical_signals || []).concat(c.why_match || []);

          return `
            <div class="candidate-card ${{isChecked ? 'selected' : ''}} ${{isContacted ? 'contacted' : ''}}" id="cand-card-${{c.id}}">
              <div class="candidate-card-checkbox">
                <input type="checkbox" value="${{c.id}}"
                  ${{isChecked ? 'checked' : ''}}
                  ${{isContacted ? 'disabled title="Already contacted"' : ''}}
                  onchange="toggleCompanySelect('${{c.id}}', this.checked)">
              </div>
              <div class="candidate-card-score">
                <span class="score-pill ${{scorePillClass}}">${{score}}</span>
                <span style="font-size:0.68rem; color:var(--text-muted); margin-top:0.25rem;">/ 100</span>
              </div>
              <div class="candidate-card-main">
                <div class="candidate-card-title-row">
                  <span class="candidate-company-name">${{escapeHtml(c.company_name)}}</span>
                  <a href="https://${{encodeURIComponent(c.domain)}}" target="_blank" rel="noopener noreferrer" class="candidate-domain-link">${{escapeHtml(c.domain)}} &nearr;</a>
                </div>
                <div class="candidate-card-meta-row">
                  <span class="meta-chip">📍 ${{escapeHtml(c.location || 'Remote')}}</span>
                  <span class="meta-chip">🏢 ${{escapeHtml(c.industry || 'Tech')}}</span>
                  <span class="meta-chip">👥 ${{escapeHtml(c.size || 'Size -')}}</span>
                  <span class="meta-chip">🌱 ${{escapeHtml(c.stage || 'Stage -')}}</span>
                </div>
                ${{allSignals.length > 0 ? `
                <div class="candidate-card-signals-row">
                  <span style="font-size:0.75rem; color:var(--text-muted); font-weight:600; margin-right:0.25rem;">Signals:</span>
                  ${{renderSignalChips(allSignals)}}
                </div>` : ''}}
              </div>
              <div class="candidate-card-status">
                ${{renderStatusBadge(c.selection_status)}}
                ${{isContacted ? '<span style="font-size:0.72rem; color:var(--text-muted);">Previously contacted</span>' : ''}}
              </div>
            </div>
          `;
        }}).join('');
      }}
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
      const card = document.getElementById('cand-card-' + id);
      if (card) {{
        if (checked) card.classList.add('selected');
        else card.classList.remove('selected');
      }}
      updateSelectedBanner();
    }}

    function toggleMasterCheckbox(master) {{
      const checkboxes = document.querySelectorAll('#candidates-container input[type="checkbox"]:not(:disabled)');
      checkboxes.forEach(cb => {{
        cb.checked = master.checked;
        if (master.checked) selectedIds.add(cb.value);
        else selectedIds.delete(cb.value);
        const card = document.getElementById('cand-card-' + cb.value);
        if (card) {{
          if (master.checked) card.classList.add('selected');
          else card.classList.remove('selected');
        }}
      }});
      updateSelectedBanner();
    }}

    function selectAllFiltered(selectVal) {{
      const checkboxes = document.querySelectorAll('#candidates-container input[type="checkbox"]:not(:disabled)');
      checkboxes.forEach(cb => {{
        cb.checked = selectVal;
        if (selectVal) selectedIds.add(cb.value);
        else selectedIds.delete(cb.value);
        const card = document.getElementById('cand-card-' + cb.value);
        if (card) {{
          if (selectVal) card.classList.add('selected');
          else card.classList.remove('selected');
        }}
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
              <td>${{renderStatusBadge(r.status)}}</td>
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
              <div style="font-size:0.75rem; color:var(--info); font-weight:600;">${{escapeHtml(ev.event_type)}} &bull; ${{new Date(ev.created_at).toLocaleTimeString()}}</div>
              <div style="font-size:0.8rem; color:var(--text-primary); margin-top:0.2rem;">${{escapeHtml(ev.message)}}</div>
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
      grid-template-columns: 260px minmax(460px, 1fr) 340px;
      gap: 1.25rem;
      align-items: start;
    }}
    @media (max-width: 1240px) {{
      .cockpit-container {{
        grid-template-columns: 240px 1fr;
      }}
      .inspector-pane {{
        grid-column: 1 / -1;
      }}
    }}
    @media (max-width: 820px) {{
      .cockpit-container {{
        grid-template-columns: 1fr;
      }}
    }}

    /* Left Sidebar: Visually Light Queue */
    .queue-sidebar {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      max-height: calc(100vh - 120px);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    .queue-header {{
      padding: 0.85rem 1rem;
      border-bottom: 1px solid var(--border);
      background: var(--bg-elevated);
    }}
    .queue-search-input {{
      width: 100%;
      margin-top: 0.5rem;
      padding: 0.35rem 0.6rem;
      font-size: 0.8rem;
      border-radius: 6px;
    }}
    .queue-list {{
      overflow-y: auto;
      flex: 1;
    }}
    .queue-item-light {{
      padding: 0.55rem 0.85rem;
      border-bottom: 1px solid var(--border);
      cursor: pointer;
      transition: all 0.15s ease;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 0.5rem;
      min-height: 42px;
    }}
    .queue-item-light:hover {{
      background: var(--bg-elevated);
    }}
    .queue-item-light.active {{
      background: rgba(76, 141, 245, 0.14);
      border-left: 3px solid var(--info);
      padding-left: calc(0.85rem - 3px);
    }}
    .queue-item-name {{
      font-size: 0.84rem;
      font-weight: 600;
      color: var(--text-primary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      flex: 1;
    }}
    .queue-item-light.active .queue-item-name {{
      color: var(--info);
    }}

    /* Center: Dominant Draft Editor Pane */
    .editor-pane {{
      display: flex;
      flex-direction: column;
      gap: 1rem;
      min-width: 0;
    }}
    .editor-hero-card {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.5rem;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    }}
    .editor-hero-card textarea {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.92rem;
      line-height: 1.65;
      min-height: 320px;
      resize: vertical;
      background: var(--bg-base);
      border-color: var(--border-strong);
    }}
    .editor-hero-card textarea:focus {{
      border-color: var(--info);
      box-shadow: 0 0 0 3px rgba(76, 141, 245, 0.25);
    }}

    /* Right: Context & Inspector Pane */
    .inspector-pane {{
      display: flex;
      flex-direction: column;
      gap: 1rem;
      min-width: 0;
    }}
    .inspector-card {{
      background: var(--bg-surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 1.15rem 1.25rem;
    }}

    .review-action-banner {{
      background: rgba(63, 185, 80, 0.1);
      border: 1px solid rgba(63, 185, 80, 0.25);
      border-radius: 8px;
      padding: 1rem 1.25rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 0;
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
      <!-- PANE 1: Left Sidebar Queue (Visually Light) -->
      <div class="queue-sidebar">
        <div class="queue-header">
          <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong style="font-size:0.8rem; text-transform:uppercase; letter-spacing:0.05em; color:var(--text-muted);">Review Queue</strong>
            <span class="badge badge-amber" id="q-count-badge">0</span>
          </div>
          <input type="text" id="queue-search" class="queue-search-input" placeholder="Filter company..." oninput="filterQueueList()">
        </div>
        <div class="queue-list" id="queue-container">
          <div style="padding:1.5rem; text-align:center; color:var(--text-muted); font-size:0.85rem;">Loading queue...</div>
        </div>
      </div>

      <!-- Empty state placeholder when nothing selected -->
      <div class="card" id="empty-detail-card" style="display:block; text-align:center; padding: 4rem; grid-column: 2 / -1;">
        <p style="color:var(--text-muted); font-size: 1rem;">Select a candidate draft from the queue to begin review.</p>
      </div>

      <!-- PANE 2: Center Dominant Draft Editor Pane -->
      <div class="editor-pane" id="editor-center-pane" style="display:none;">
        <!-- Status & Actions Header -->
        <div class="card" style="padding: 1rem 1.25rem; margin-bottom: 0;">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.75rem;">
            <div>
              <span id="rev-status-pill">-</span>
              <span style="font-size: 0.8rem; color: var(--text-muted); margin-left: 0.5rem;" id="rev-campaign-name"></span>
            </div>
            <div style="display:flex; gap:0.5rem; flex-wrap:wrap;" id="decision-actions">
              <button type="button" class="btn btn-secondary btn-sm" onclick="saveDraftEdits()">💾 Save Changes</button>
              <button type="button" class="btn btn-secondary btn-sm" id="revert-draft-btn" onclick="revertDraftToOriginal()">↺ Revert to original</button>
              <button type="button" class="btn btn-danger btn-sm" onclick="openRejectModal()">✕ Reject</button>
              <button type="button" class="btn btn-success btn-sm" onclick="approveCurrentReview()">✓ Approve (Wait for Delivery)</button>
            </div>
          </div>
        </div>

        <!-- Waiting for Delivery Banner (if already approved) -->
        <div class="review-action-banner" id="delivery-trigger-banner" style="display:none;">
          <div>
            <strong style="color: var(--success); font-size: 0.92rem;">✓ Approved — Waiting for Explicit Delivery</strong>
            <p style="font-size: 0.78rem; color: var(--text-muted); margin-top: 0.2rem;">
              Review decision is authoritative. Triggering delivery runs all 11 server safety gates and stages to disk or sends live.
            </p>
          </div>
          <button class="btn btn-purple btn-sm" id="deliver-now-btn" onclick="executeDeliveryForCurrentRun()">⚡ Deliver Outbound Email</button>
        </div>

        <!-- Dominant Draft Editor Card -->
        <div class="editor-hero-card">
          <div class="card-title" style="margin-bottom:1rem;">
            <div style="display:flex; align-items:center; gap:0.5rem;">
              <span style="font-size:1rem; font-weight:700; color:var(--text-primary);">AI Outreach Draft</span>
              <span style="font-size:0.75rem; color:var(--text-muted);">(Human edits strictly authoritative)</span>
            </div>
            <span class="badge badge-purple" id="d-draft-persona">persona</span>
          </div>
          <div class="form-group">
            <label for="draft-subject">Subject Line</label>
            <input type="text" id="draft-subject" style="font-family:'JetBrains Mono',monospace; font-weight:600; font-size:0.95rem;">
          </div>
          <div class="form-group" style="margin-bottom:0;">
            <label for="draft-body">Email Body (Edit before approving)</label>
            <textarea id="draft-body" rows="14"></textarea>
          </div>
        </div>
      </div>

      <!-- PANE 3: Right Inspector Pane (Context & Intelligence) -->
      <div class="inspector-pane" id="inspector-right-pane" style="display:none;">
        <!-- Company Intelligence -->
        <div class="inspector-card">
          <div class="card-title">
            <span>Company Intelligence</span>
            <span id="d-comp-score">-</span>
          </div>
          <h3 style="font-size: 1.05rem; font-weight:700;" id="d-comp-name">-</h3>
          <p style="font-size: 0.8rem; color:var(--info); margin-top:0.2rem;" id="d-comp-domain">-</p>
          <div style="font-size: 0.8rem; color:var(--text-muted); margin: 0.5rem 0;" id="d-comp-industry">-</div>
          <div id="d-comp-signals" style="margin-top:0.5rem;"></div>
        </div>

        <!-- Verified Contact Quality -->
        <div class="inspector-card">
          <div class="card-title">
            <span>Verified Contact</span>
            <span id="d-contact-badge">-</span>
          </div>
          <h3 style="font-size: 1.05rem; font-weight:700;" id="d-person-name">-</h3>
          <p style="font-size: 0.8rem; color:var(--text-muted); margin-top:0.2rem;" id="d-person-role">-</p>
          <div style="font-size: 0.85rem; font-family:'JetBrains Mono',monospace; color:var(--success); margin: 0.5rem 0;" id="d-contact-email">-</div>
          <div style="font-size: 0.76rem; color:var(--text-muted);" id="d-person-confidence"></div>
        </div>

        <!-- Audit Timeline -->
        <div class="inspector-card">
          <div class="card-title">
            <span>Pipeline Audit Trail</span>
            <button class="btn btn-secondary btn-sm" onclick="toggleAuditTimeline()" style="padding:0.2rem 0.5rem; font-size:0.75rem;">Toggle</button>
          </div>
          <div id="audit-trail-container" style="max-height: 200px; overflow-y:auto;"></div>
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
    let activeOriginalDraft = {{ subject: '', body: '' }};

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
          document.getElementById('editor-center-pane').style.display = 'none';
          document.getElementById('inspector-right-pane').style.display = 'none';
          document.getElementById('empty-detail-card').style.display = 'block';
          return;
        }}

        container.innerHTML = reviewQueue.map(item => {{
          const score = Math.max(0, Math.min(100, Math.round(Number(item.match_score) || 0)));
          let scoreClass = 'score-red';
          if (score >= 70) scoreClass = 'score-green';
          else if (score >= 50) scoreClass = 'score-amber';

          return `
            <div class="queue-item-light ${{item.id === currentReviewId ? 'active' : ''}}" data-id="${{item.id}}" onclick="selectReview('${{item.id}}')">
              <span class="queue-item-name" title="${{escapeHtml(item.company_name)}}">${{escapeHtml(item.company_name)}}</span>
              <span class="score-pill ${{scoreClass}}">${{score}}</span>
            </div>
          `;
        }}).join('');

        // If no active review or selected was removed, select first
        if (!currentReviewId || !reviewQueue.some(r => r.id === currentReviewId)) {{
          selectReview(reviewQueue[0].id);
        }}
      }} catch (err) {{
        showToast('Queue error: ' + err.message, true);
      }}
    }}

    function filterQueueList() {{
      const q = (document.getElementById('queue-search')?.value || '').toLowerCase();
      document.querySelectorAll('.queue-item-light').forEach(el => {{
        const nameEl = el.querySelector('.queue-item-name');
        const name = nameEl ? nameEl.textContent.toLowerCase() : '';
        el.style.display = (!q || name.includes(q)) ? 'flex' : 'none';
      }});
    }}

    async function selectReview(id) {{
      currentReviewId = id;
      document.querySelectorAll('.queue-item-light').forEach(el => {{
        if (el.getAttribute('data-id') === id) el.classList.add('active');
        else el.classList.remove('active');
      }});

      try {{
        const res = await fetch(`/api/v1/review/${{id}}`);
        if (!res.ok) throw new Error('Failed to load review details');
        currentReview = await res.json();

        document.getElementById('empty-detail-card').style.display = 'none';
        document.getElementById('editor-center-pane').style.display = 'flex';
        document.getElementById('inspector-right-pane').style.display = 'flex';

        // Header
        const pill = document.getElementById('rev-status-pill');
        pill.innerHTML = renderStatusBadge(currentReview.status);
        document.getElementById('rev-campaign-name').textContent = 'Campaign: ' + (currentReview.campaign?.name || '-');

        // Company
        document.getElementById('d-comp-name').textContent = currentReview.company?.company_name || '-';
        document.getElementById('d-comp-domain').textContent = currentReview.company?.domain || '-';
        document.getElementById('d-comp-industry').textContent = `${{currentReview.company?.industry || 'Tech'}} &bull; ${{currentReview.company?.stage || 'Early-Stage'}} &bull; ${{currentReview.company?.location || 'Remote'}}`;
        document.getElementById('d-comp-score').innerHTML = renderScoreBar(currentReview.company?.match_score || 0);

        const signals = (currentReview.company?.technical_signals || []).concat(currentReview.company?.why_match || []);
        document.getElementById('d-comp-signals').innerHTML = renderSignalChips(signals);

        // Person & Contact
        const p = currentReview.person;
        const c = currentReview.contact;
        document.getElementById('d-person-name').textContent = p ? p.full_name : 'No verified leader';
        document.getElementById('d-person-role').textContent = p ? p.role : '-';
        document.getElementById('d-contact-email').textContent = c?.email || 'No email resolved';

        const conf = p?.person_confidence || 0;
        document.getElementById('d-person-confidence').innerHTML = `Person confidence: ${{(conf * 100).toFixed(0)}}% (gate: &ge; 70%)`;

        const contactBadge = document.getElementById('d-contact-badge');
        contactBadge.innerHTML = renderStatusBadge(c?.verification_status || 'unverified');

        // Draft
        const draft = currentReview.draft || {{}};
        activeOriginalDraft = {{
          subject: draft.subject || '',
          body: draft.body || ''
        }};
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
            <div style="font-size:0.78rem; padding:0.35rem 0; border-bottom:1px solid var(--border);">
              <span style="color:var(--info); font-weight:600;">${{escapeHtml(ev.event_type)}}</span>
              <span style="color:var(--text-muted); margin-left:0.5rem;">${{new Date(ev.created_at).toLocaleTimeString()}}</span>
              <div style="color:var(--text-primary); margin-top:0.15rem;">${{escapeHtml(ev.message)}}</div>
            </div>
          `).join('');
        }}
      }} catch (err) {{
        showToast('Error: ' + err.message, true);
      }}
    }}

    function revertDraftToOriginal() {{
      if (!activeOriginalDraft) {{
        showToast('No original draft available to revert', true);
        return;
      }}
      document.getElementById('draft-subject').value = activeOriginalDraft.subject || '';
      document.getElementById('draft-body').value = activeOriginalDraft.body || '';
      showToast('Reverted draft to original AI generated text');
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
          const artifactOrErr = d.staged_file_path || d.error_message || '-';

          return `
            <tr>
              <td>
                <strong>${{escapeHtml(d.company_name)}}</strong><br>
                <span style="font-size:0.75rem; color:var(--text-muted)">${{escapeHtml(d.domain)}}</span>
              </td>
              <td>
                <div>${{escapeHtml(d.recipient_name || '-')}}</div>
                <div style="font-size:0.75rem; color:var(--info); font-family:'JetBrains Mono',monospace;">${{escapeHtml(d.recipient_email || 'No email')}}</div>
              </td>
              <td style="font-size:0.8rem;">${{escapeHtml(d.campaign_name)}}</td>
              <td>${{renderStatusBadge(d.delivery_status)}}</td>
              <td>
                ${{renderStatusBadge(d.delivery_mode)}}
                <span style="font-size:0.75rem; color:var(--text-muted); display:block; margin-top:0.2rem;">${{escapeHtml(d.provider)}}</span>
              </td>
              <td style="font-size:0.78rem; color:var(--text-muted);">${{d.delivered_at ? new Date(d.delivered_at).toLocaleString() : '-'}}</td>
              <td style="font-size:0.78rem; max-width:200px; word-break:break-all;" title="${{escapeHtml(artifactOrErr)}}">
                ${{escapeHtml(artifactOrErr.slice(0, 35))}}${{artifactOrErr.length > 35 ? '...' : ''}}
              </td>
              <td>
                <button onclick="inspectAuditRecord(${{idx}})" class="btn btn-secondary btn-sm">Inspect Audit</button>
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
          <div style="display:flex; justify-content:space-between; align-items:center; padding:0.6rem; border-bottom:1px solid var(--border);">
            <span style="font-size:0.85rem; color:var(--text-primary);">${{g.name}}</span>
            ${{renderStatusBadge(isPassed ? 'passed' : 'blocked')}}
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
            <td>${{renderStatusBadge(r.parsing_status)}}</td>
            <td>
              ${{r.is_active ? '<span class="badge badge-green"><span aria-hidden="true">●</span> Active for Campaigns</span>' : '<span style="color:var(--text-muted);font-size:0.75rem">Inactive</span>'}}
            </td>
            <td style="font-size:0.8rem; color:var(--text-muted);">${{new Date(r.uploaded_at).toLocaleDateString()}}</td>
            <td>
              <span class="chip">Security / Infra</span>
              <span class="chip">AI / ML</span>
              <span class="chip">HR / Talent</span>
            </td>
            <td>
              ${{!r.is_active ? `<button onclick="activateResume('${{r.id}}')" class="btn btn-secondary btn-sm">Set as Active</button>` : '<span style="color:var(--success); font-size:0.8rem;"><span aria-hidden="true">✓</span> Current Active</span>'}}
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
      border-bottom: 1px solid var(--border);
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
    <div class="card" style="border-color: rgba(76, 141, 245, 0.4); background: linear-gradient(180deg, rgba(76, 141, 245, 0.08) 0%, var(--bg-surface) 100%);">
      <div style="display:flex; gap:0.75rem; align-items:flex-start;">
        <span style="font-size:1.3rem;">🔒</span>
        <div>
          <strong style="color:var(--info); font-size:0.95rem;">Authoritative Server Boundary Policy</strong>
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
        <span class="badge badge-green" id="health-status"><span aria-hidden="true">●</span> Healthy (1.0.0)</span>
      </div>

      <div class="settings-row">
        <div>
          <strong>Delivery Mode</strong>
          <div style="font-size:0.78rem; color:var(--text-muted);">Outbound execution mode (stub, staged, live)</div>
        </div>
        <span class="badge badge-purple" id="set-delivery-mode"><span aria-hidden="true">🧪</span> staged</span>
      </div>

      <div class="settings-row">
        <div>
          <strong>Dry Run Staging Enforced</strong>
          <div style="font-size:0.78rem; color:var(--text-muted);">Prevents external provider dispatch side-effects</div>
        </div>
        <span class="badge badge-cyan" id="set-dry-run"><span aria-hidden="true">🛡</span> True (Staging Active)</span>
      </div>

      <div class="settings-row">
        <div>
          <strong>Confirm Live Flag</strong>
          <div style="font-size:0.78rem; color:var(--text-muted);">Required environment flag for live sending</div>
        </div>
        <span class="badge badge-gray" id="set-confirm-live"><span aria-hidden="true">🔒</span> False (Blocked)</span>
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
        <span class="badge badge-blue"><span aria-hidden="true">🛡</span> &ge; 0.70 (70%)</span>
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
          document.getElementById('health-status').innerHTML = `<span aria-hidden="true">●</span> ${{escapeHtml(data.status)}} (v${{escapeHtml(data.version)}})`;
          document.getElementById('set-delivery-mode').innerHTML = renderStatusBadge(data.delivery_mode || 'staged');
          document.getElementById('set-dry-run').innerHTML = data.dry_run
            ? '<span aria-hidden="true">🛡</span> True (Staging Active)'
            : '<span aria-hidden="true">⚡</span> False (Live Dispatch Allowed)';
          document.getElementById('set-dry-run').className = 'badge ' + (data.dry_run ? 'badge-cyan' : 'badge-amber');
        }}
      }} catch (e) {{}}
    }}

    document.addEventListener('DOMContentLoaded', loadSettings);
  </script>
</body>
</html>"""
