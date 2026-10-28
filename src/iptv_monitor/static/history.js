/* History tab: poll /api/history every 15s and rank URLs by separate outages.
 * Counts are up→down edges, not downtime. by_day[0] is the oldest UTC day, the last entry is today.
 * The host filter scopes both the "Outages per day" chart and the table; tiles stay global.
 * Tooltips come from shell.js via data-tip-title / data-tip-body.
 */

const bodyEl = document.getElementById("history-body");
const filterEl = document.getElementById("history-filter");
const statUrls = document.getElementById("stat-urls");
const statDowns = document.getElementById("stat-downs");
const statUpdated = document.getElementById("stat-updated");
const historyCount = document.getElementById("history-count");
const chartEl = document.getElementById("daily-chart");
const dailyTableEl = document.getElementById("daily-table");

let rows = [];
let windowDays = 90;
let sortKey = "downs_90d";
let visibleRows = [];

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = text;
  }
}

function typeLabel(row) {
  if (row.vpn) {
    return "VPN DNS";
  }
  if (row.cloudflare_proxied) {
    return "CF proxy";
  }
  if (row.cloudflare) {
    return "CF NS";
  }
  return "origin";
}

function nowLabel(row) {
  if (row.healthy === true) {
    return '<span class="status-up">up</span>';
  }
  if (row.healthy === false) {
    return '<span class="status-down">down</span>';
  }
  return '<span class="muted">—</span>';
}

function fmtWhen(iso) {
  if (!iso) {
    return "never";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "never";
  }
  return date.toLocaleString();
}

function compact(n) {
  if (n >= 10000) {
    return `${Math.round(n / 1000)}K`;
  }
  if (n >= 1000) {
    return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}K`;
  }
  return String(n);
}

// UTC date for by_day index i (0 = oldest).
function dayDate(index) {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() - (windowDays - 1 - index)));
}

function dayLabel(index, withWeekday = true) {
  if (index === windowDays - 1) {
    return "Today";
  }
  return dayDate(index).toLocaleDateString([], {
    weekday: withWeekday ? "short" : undefined,
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

function dailyTotals(list) {
  const totals = new Array(windowDays).fill(0);
  for (const row of list) {
    (row.by_day || []).forEach((n, i) => {
      if (i < windowDays) {
        totals[i] += Number(n) || 0;
      }
    });
  }
  return totals;
}

// Clean axis maximum: 1 / 2 / 4 / 6 / 8 / 10 × 10^n, so the half-way tick is also round.
function niceCeil(value) {
  if (value <= 0) {
    return 1;
  }
  const mag = 10 ** Math.floor(Math.log10(value));
  for (const f of [1, 2, 4, 6, 8, 10]) {
    if (value <= f * mag) {
      return f * mag;
    }
  }
  return 10 * mag;
}

function renderDaily(list) {
  if (!chartEl) {
    return;
  }
  const totals = dailyTotals(list);
  const width = chartEl.clientWidth || 800;
  const height = chartEl.clientHeight || 240;
  const pad = { l: 44, r: 10, t: 22, b: 26 };
  const pw = width - pad.l - pad.r;
  const ph = height - pad.t - pad.b;
  const max = Math.max(0, ...totals);
  const top = niceCeil(max);
  const step = pw / windowDays;
  const bw = Math.max(1, Math.min(24, step - 2));
  const base = pad.t + ph;
  const y = (v) => base - (v / top) * ph;

  const grid = [0, top / 2, top]
    .map((tick) => {
      const ty = y(tick);
      const cls = tick === 0 ? "baseline" : "grid-line";
      return `<line class="${cls}" x1="${pad.l}" x2="${width - pad.r}" y1="${ty}" y2="${ty}"></line>
        <text class="axis-label" x="${pad.l - 10}" y="${ty + 4}" text-anchor="end">${compact(tick)}</text>`;
    })
    .join("");

  const peak = totals.indexOf(max);
  const cols = totals
    .map((n, i) => {
      const x = pad.l + i * step;
      const bx = x + (step - bw) / 2;
      let bar = "";
      if (n > 0) {
        const by = y(n);
        const h = base - by;
        const r = Math.min(4, bw / 2, h);
        // Rounded data-end, square at the baseline.
        bar = `<path class="bar" d="M${bx},${base} V${by + r} Q${bx},${by} ${bx + r},${by} H${bx + bw - r} Q${bx + bw},${by} ${bx + bw},${by + r} V${base} Z"></path>`;
      }
      const label = `${dayLabel(i)} · UTC`;
      return `<g class="col" data-tip-title="${n.toLocaleString()} outage${n === 1 ? "" : "s"}" data-tip-body="${esc(label)}">
        <rect class="hit" x="${x}" y="${pad.t}" width="${step}" height="${ph}"></rect>${bar}</g>`;
    })
    .join("");

  const peakLabel =
    max > 0
      ? `<text class="peak-label" x="${pad.l + peak * step + step / 2}" y="${y(max) - 7}" text-anchor="middle">${compact(max)}</text>`
      : "";

  // X labels every 15 days, anchored on today at the right edge.
  const xLabels = [];
  for (let i = windowDays - 1; i >= 0; i -= 15) {
    const x = pad.l + i * step + step / 2;
    const anchor = i === windowDays - 1 ? "end" : "middle";
    const tx = i === windowDays - 1 ? width - pad.r : x;
    xLabels.push(`<text class="axis-label" x="${tx}" y="${height - 6}" text-anchor="${anchor}">${esc(dayLabel(i, false))}</text>`);
  }

  chartEl.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Outages per day over the last ${windowDays} days">${grid}${cols}${peakLabel}${xLabels.join("")}</svg>`;

  if (dailyTableEl) {
    dailyTableEl.innerHTML = totals
      .map((n, i) => ({ n, i }))
      .reverse()
      .map(({ n, i }) => `<div><span>${esc(dayLabel(i))}</span><b>${n.toLocaleString()}</b></div>`)
      .join("");
  }
}

function spark(byDay) {
  // One bar per day. Height is relative to the busiest day in this row.
  const values = Array.isArray(byDay) ? byDay : [];
  const max = Math.max(0, ...values);
  const bars = values
    .map((count) => {
      const n = Number(count) || 0;
      const pct = n <= 0 ? 8 : Math.max(18, Math.round((n / Math.max(max, 1)) * 100));
      const cls = n > 0 ? "on" : "";
      return `<i class="${cls}" style="height:${pct}%" title="${n} down${n === 1 ? "" : "s"}"></i>`;
    })
    .join("");
  return `<div class="spark" aria-hidden="true">${bars}</div>`;
}

// Reliability grade (shell.js): share of the last 30 days with an outage → A–F,
// ignoring VPS-wide incident days (recomputed from every poll's rows).
const gradeCache = new WeakMap();
let incidentSkip = new Set();

function gradeOf(row) {
  if (!gradeCache.has(row)) {
    gradeCache.set(row, window.consoleShell.reliability(row, incidentSkip));
  }
  return gradeCache.get(row);
}

function gradeCell(row) {
  const rel = gradeOf(row);
  return `<span class="hist-grade"><span class="grade g-${rel.grade}" role="img" aria-label="Grade ${rel.grade}: ${esc(rel.text)}" data-tip-title="Grade ${rel.grade} · ${esc(rel.text)}" data-tip-body="${esc(window.consoleShell.gradeTip(rel))}">${rel.grade}</span><small>${rel.clean}/${rel.span} clean</small></span>`;
}

function renderTiles() {
  const totals = dailyTotals(rows);
  const week = totals.slice(-7).reduce((a, b) => a + b, 0);
  const prior = totals.slice(-14, -7).reduce((a, b) => a + b, 0);
  setText("stat-week", week.toLocaleString());
  setText(
    "stat-week-cap",
    prior ? `${week >= prior ? "+" : "−"}${Math.abs(Math.round(((week - prior) / prior) * 100))}% vs the week before` : "in the last 7 days"
  );
  const worst = Math.max(0, ...totals);
  setText("stat-worst", worst.toLocaleString());
  setText("stat-worst-cap", worst ? `on ${dayLabel(totals.indexOf(worst))} (UTC)` : "no outages recorded");
}

function render() {
  const query = (filterEl.value || "").trim().toLowerCase();
  visibleRows = rows.filter((row) => {
    if (!query) {
      return true;
    }
    const hay = `${row.host || ""} ${row.url || ""} ${typeLabel(row)} ${row.pool_label || ""}`.toLowerCase();
    return hay.includes(query);
  });
  renderDaily(visibleRows);
  const sorted = [...visibleRows].sort((a, b) => {
    // "Worst grade" ranks by outage days in the last 30, then outages this week.
    const delta =
      sortKey === "grade"
        ? gradeOf(b).bad - gradeOf(a).bad || gradeOf(b).downs7 - gradeOf(a).downs7
        : (Number(b[sortKey]) || 0) - (Number(a[sortKey]) || 0);
    if (delta !== 0) {
      return delta;
    }
    return String(a.host || a.url).localeCompare(String(b.host || b.url));
  });
  historyCount.textContent = query ? `${sorted.length} of ${rows.length} URLs` : `${rows.length} URLs`;
  if (!sorted.length) {
    bodyEl.innerHTML = `<tr><td colspan="9" class="empty-events">No URLs match.</td></tr>`;
    return;
  }
  bodyEl.innerHTML = sorted
    .map((row) => {
      const downs = Number(row.downs_90d) || 0;
      const cls = row.healthy === false ? "row-down" : "";
      const last = row.last_down_at
        ? `${esc(fmtWhen(row.last_down_at))}${row.last_reason ? `<div class="hist-reason">${esc(row.last_reason)}</div>` : ""}`
        : '<span class="muted">never</span>';
      return `<tr class="${cls}">
        <td>
          <div class="hist-host">${esc(row.host || row.url)}</div>
          <div class="hist-url">${esc(row.url)}</div>
        </td>
        <td>${esc(typeLabel(row))}</td>
        <td>${nowLabel(row)}</td>
        <td>${gradeCell(row)}</td>
        <td>${Number(row.downs_24h) || 0}</td>
        <td>${Number(row.downs_7d) || 0}</td>
        <td><strong>${downs.toLocaleString()}</strong></td>
        <td>${last}</td>
        <td>${spark(row.by_day)}</td>
      </tr>`;
    })
    .join("");
}

async function poll() {
  try {
    const response = await fetch("/api/history", { cache: "no-store" });
    if (response.status === 401) {
      window.consoleShell.toSignIn();
      return;
    }
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    rows = data.urls || [];
    windowDays = data.window_days || 90;
    incidentSkip = window.consoleShell.incidentDays(rows);
    statUrls.textContent = String(data.url_count ?? rows.length);
    statDowns.textContent = Number(data.total_downs ?? 0).toLocaleString();
    statUpdated.textContent = data.generated_at
      ? `updated ${new Date(data.generated_at).toLocaleTimeString([], { hour12: false })}`
      : "waiting…";
    renderTiles();
    render();
  } catch (error) {
    statUpdated.textContent = "could not load";
    bodyEl.innerHTML = `<tr><td colspan="9" class="empty-events">Could not load history.</td></tr>`;
  }
}

filterEl.addEventListener("input", render);

document.querySelectorAll(".sort-btn").forEach((button) => {
  button.addEventListener("click", () => {
    sortKey = button.dataset.sort || "downs_90d";
    document.querySelectorAll(".sort-btn").forEach((item) => {
      item.classList.toggle("is-here", item === button);
    });
    render();
  });
});

if (chartEl && "ResizeObserver" in window) {
  let lastWidth = 0;
  new ResizeObserver(() => {
    if (chartEl.clientWidth !== lastWidth && rows.length) {
      lastWidth = chartEl.clientWidth;
      renderDaily(visibleRows);
    }
  }).observe(chartEl);
}

poll();
setInterval(poll, 15000);
