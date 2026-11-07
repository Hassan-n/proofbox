# Proofbox Central Design System

Version: 1.0  
Date: 2026-11-06  
Brand Line: *Open nothing unsafely. Believe nothing unproven. Fight with receipts.*  
Product Placeholder: `Proofbox` (centralized in `PROOFBOX_NAME` constant)

Proofbox uses a **trustworthy forensic notebook** aesthetic: calm, warm paper-like surfaces (`--paper: #F7F5F0`, `--surface: #FFFFFF`) paired with deep teal actions (`--brand: #0F6B64`) and an unmistakable dark instrument zone for the containment sandbox (`--chamber-*`).

---

## 1. Tokens Reference (`css/tokens.css`)

### Surfaces & Lines
- `--paper: #F7F5F0`: Page background, warm forensic notebook tone.
- `--surface: #FFFFFF`: Card & modal surfaces.
- `--surface-sunken: #EFECE4`: Inset areas, table striping, chat backgrounds.
- `--ink: #14202B`: Primary text (contrast: 14.9:1 on paper, passes WCAG AAA).
- `--ink-muted: #4B5966`: Secondary text (contrast: 6.5:1 on paper, passes WCAG AA).
- `--line: #D9D4C7`: Subtle borders.
- `--line-strong: #A8A193`: Focused or emphasized borders.

### Brand
- `--brand: #0F6B64`: Primary deep teal action color (contrast: 6.4:1 on white).
- `--brand-strong: #0A4F4A`: Hover/active state for primary buttons.
- `--brand-tint: #E2F1EF`: Highlighting, selected rows, router bubbles.

### Containment Panel (Dark Chamber)
- `--chamber-bg: #0B1620`: Sealed dark instrument background.
- `--chamber-surface: #12212E`: Container card & header background.
- `--chamber-line: #24384A`: Chamber divider lines.
- `--chamber-text: #D7E3EC`: Primary chamber text (contrast 12.1:1 on chamber surface).
- `--chamber-muted: #8FA5B6`: Secondary event details & timestamps (6.5:1 contrast).

### Status System (Always Word + Icon)
- `--danger: #B42318`, `--danger-tint: #FDECEA`: Dangerous links, overcharges, failed checks.
- `--warn: #A15C07`, `--warn-tint: #FFF3DC`: Suspicious links, estimated readings, unreadable fields.
- `--info: #1F5F99`, `--info-tint: #E6F0FA`: "No issue found" (never styled as green).
- `--ok: #1B6B3A`, `--ok-tint: #E4F4EA`: Completed process milestones only.
- `--neutral: #5A6672`, `--neutral-tint: #ECEEF0`: Could not check, expired, unknown.

### Typography & Spacing
- `--font-sans`: `system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", sans-serif`
- `--font-mono`: `ui-monospace, "SF Mono", Menlo, Consolas, monospace`
- `--font-serif`: `Georgia, Cambria, "Times New Roman", serif`
- Scale: `--text-xs: 0.8125rem`, `--text-sm: 0.9375rem`, `--text-md: 1.0625rem`, `--text-lg: 1.25rem`, `--text-xl: 1.625rem`, `--text-2xl: 2.125rem`
- Spacing: `--s1: 0.25rem` (4px), `--s2: 0.5rem` (8px), `--s3: 0.75rem` (12px), `--s4: 1rem` (16px), `--s5: 1.5rem` (24px), `--s6: 2rem` (32px), `--s7: 3rem` (48px)
- Radii: `--radius-sm: 8px`, `--radius-md: 14px`, `--radius-lg: 20px`, `--radius-pill: 999px`
- Touch: `--tap: 48px` minimum touch target height.

---

## 2. Reusable Components (`css/components.css`)

### App Shell
```html
<header class="topbar">
  <div class="topbar-banner">
    <svg class="topbar-banner-icon" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm0 3a.75.75 0 0 1 .75.75v3.5a.75.75 0 0 1-1.5 0v-3.5A.75.75 0 0 1 8 4zm0 7a1 1 0 1 1 0-2 1 1 0 0 1 0 2z"/>
    </svg>
    <span>Synthetic data only. Please do not upload real documents.</span>
  </div>
  <div class="topbar-inner">
    <a class="brand" href="/" aria-label="Proofbox Home">
      <span class="brand-mark" aria-hidden="true">P</span>
      <span>Proofbox</span>
    </a>
    <nav class="topbar-nav" aria-label="Primary Navigation">
      <a href="/" aria-current="page">Link Lens</a>
      <a href="/bill/">Bill Lens</a>
      <a href="/letter/">Letter Lens</a>
      <a href="/case/">Case File</a>
      <a href="/vultr.html">How it runs on Vultr</a>
    </nav>
    <div class="lang-picker">
      <label for="shell-lang" class="sr-only">Language</label>
      <select id="shell-lang" class="lang-select">
        <option value="en">English</option>
        <option value="zu">isiZulu</option>
        <option value="af">Afrikaans</option>
        <option value="st">Sesotho</option>
      </select>
    </div>
  </div>
</header>
```

### Buttons
```html
<!-- Primary -->
<button type="button" class="btn btn-primary">Check link</button>

<!-- Secondary -->
<button type="button" class="btn btn-secondary">Download receipt</button>

<!-- Ghost / Quiet -->
<button type="button" class="btn btn-quiet">Open trace</button>

<!-- Danger -->
<button type="button" class="btn btn-danger">Delete case file</button>

<!-- Loading State -->
<button type="button" class="btn btn-primary is-loading" disabled>
  <span>Inspecting...</span>
</button>

<!-- Red-Team Demo Action -->
<button type="button" class="btn btn-redteam">Try to break it</button>
```

### Status Chips (Always Word + Icon)
```html
<!-- Dangerous -->
<span class="status-chip status-chip--dangerous">
  <span aria-hidden="true">▲</span> Dangerous
</span>

<!-- Suspicious -->
<span class="status-chip status-chip--suspicious">
  <span aria-hidden="true">●</span> Suspicious
</span>

<!-- No Issue Found (Always Info Blue, Never Green) -->
<span class="status-chip status-chip--no_issue_found">
  <span aria-hidden="true">ℹ</span> No Issue Found
</span>

<!-- Verified Milestone -->
<span class="status-chip status-chip--verified">
  <span aria-hidden="true">✓</span> Verified
</span>
```

### Hero Containment Panel
```html
<section class="containment-panel" aria-labelledby="containment-title">
  <div class="containment-header">
    <div class="containment-title-group">
      <span class="containment-badge">Sandbox</span>
      <h2 id="containment-title" class="sr-only">Sandbox Activity</h2>
      <span class="font-mono text-xs">job-8f2a1b9c</span>
    </div>
    <div class="flex-row">
      <span class="containment-live-pill">
        <span class="containment-live-dot" aria-hidden="true"></span>
        <span id="live-state">RUNNING</span>
      </span>
      <span class="containment-timer" id="wall-clock">28s remaining</span>
    </div>
  </div>

  <div class="containment-summary">
    <div class="containment-summary-item">
      <span>Blocked:</span> <span class="containment-summary-count">2</span>
    </div>
    <div class="containment-summary-item">
      <span>Quarantined:</span> <span class="containment-summary-count">1</span>
    </div>
    <div class="containment-summary-item">
      <span>Ignored:</span> <span class="containment-summary-count">1</span>
    </div>
  </div>

  <ol class="containment-events" id="containment-events-list" aria-live="polite">
    <li class="containment-event-row" style="border-left-color: #F87171;">
      <span class="containment-event-time">14:02:18</span>
      <div class="containment-event-body">
        <span class="containment-event-tag tag-blocked">BLOCKED</span>
        <span>Blocked: tried to reach internal IP 10.0.0.5</span>
      </div>
    </li>
  </ol>
</section>
```

### Verdict Card
```html
<article class="verdict-card" aria-labelledby="verdict-status-title">
  <span class="status-chip status-chip--dangerous">
    <span aria-hidden="true">▲</span> Dangerous
  </span>
  <h2 id="verdict-status-title" class="verdict-heading">Do not enter personal details on this link.</h2>
  
  <div class="verdict-confidence-box">
    <span>Confidence: High</span>
    <div class="confidence-bar" role="progressbar" aria-valuenow="92" aria-valuemin="0" aria-valuemax="100">
      <div class="confidence-bar-fill" style="width: 92%;"></div>
    </div>
  </div>

  <div class="verdict-advice-box">
    <p class="verdict-advice-text">Go directly to your official municipality portal or call the number on your original paper statement.</p>
  </div>

  <ul class="verdict-reasons-list">
    <li>The link domain does not belong to Karoo Bay Metro.</li>
    <li>The page attempted to transmit user credentials to an unauthorized server.</li>
  </ul>

  <div class="verdict-caveat-box">
    <strong>What this does not mean:</strong> An automated check inspects observable network behavior; it is not a legal finding.
  </div>
</article>
```

### Discrepancy Table (Bill Lens)
```html
<div class="discrepancy-table-wrap">
  <table class="discrepancy-table">
    <thead>
      <tr>
        <th scope="col">Charge Description</th>
        <th scope="col">Billed</th>
        <th scope="col">Recomputed</th>
        <th scope="col">Difference</th>
        <th scope="col">Receipt</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <th scope="row">Water Consumption (Step 3)</th>
        <td data-label="Billed">R 840.50</td>
        <td data-label="Recomputed">R 620.00</td>
        <td data-label="Difference">
          <span class="discrepancy-diff">
            <span aria-hidden="true">▲</span> +R 220.50
          </span>
        </td>
        <td data-label="Receipt">
          <button type="button" class="receipt-chip">[E3] R620.00</button>
        </td>
      </tr>
    </tbody>
  </table>
</div>
```

### Timeline & Next Action Card (Case File)
```html
<div class="next-action-card">
  <div class="next-action-title">
    <span aria-hidden="true">★</span> Next Required Action
  </div>
  <p class="next-action-body">Submit your formal water bill dispute letter to Karoo Bay Metro before the response clock expires.</p>
</div>

<div class="timeline">
  <article class="timeline-node">
    <div class="timeline-dot" aria-hidden="true">1</div>
    <div class="timeline-card">
      <div class="flex-between">
        <strong>Water Bill Inspection</strong>
        <span class="status-chip status-chip--verified">✓ Verified</span>
      </div>
      <p class="text-sm text-muted">Billed totals recomputed against municipal tariff gazette.</p>
      <div class="flex-row">
        <button type="button" class="receipt-chip">[E1] Tariff Engine</button>
      </div>
    </div>
  </article>
</div>
```

