/* History tab: poll /api/history and rank URLs by separate outages. */

const bodyEl = document.getElementById("history-body");
const filterEl = document.getElementById("history-filter");
const statWindow = document.getElementById("stat-window");
const statUrls = document.getElementById("stat-urls");
const statDowns = document.getElementById("stat-downs");
const statUpdated = document.getElementById("stat-updated");
const historyCount = document.getElementById("history-count");

let rows = [];
let sortKey = "downs_90d";

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function typeLabel(row) {
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

function spark(byDay) {
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

function render() {
  const query = (filterEl.value || "").trim().toLowerCase();
  const sorted = [...rows].sort((a, b) => {
    const delta = (Number(b[sortKey]) || 0) - (Number(a[sortKey]) || 0);
    if (delta !== 0) {
      return delta;
    }
    return String(a.host || a.url).localeCompare(String(b.host || b.url));
  });
  const visible = sorted.filter((row) => {
    if (!query) {
      return true;
    }
    const hay = `${row.host || ""} ${row.url || ""} ${typeLabel(row)}`.toLowerCase();
    return hay.includes(query);
  });
  historyCount.textContent = `${visible.length} shown`;
  if (!visible.length) {
    bodyEl.innerHTML = `<tr><td colspan="8" class="empty-events">No URLs match.</td></tr>`;
    return;
  }
  bodyEl.innerHTML = visible
    .map((row) => {
      const downs = Number(row.downs_90d) || 0;
      const cls = row.healthy === false ? "row-down" : "";
      const last = row.last_down_at
        ? `${esc(fmtWhen(row.last_down_at))}${row.last_reason ? `<div class="hist-reason">${esc(row.last_reason)}</div>` : ""}`
        : "never";
      return `<tr class="${cls}">
        <td>
          <div class="hist-host">${esc(row.host || row.url)}</div>
          <div class="hist-url">${esc(row.url)}</div>
        </td>
        <td>${esc(typeLabel(row))}</td>
        <td>${nowLabel(row)}</td>
        <td>${Number(row.downs_24h) || 0}</td>
        <td>${Number(row.downs_7d) || 0}</td>
        <td class="${downs ? "status-down" : "status-up"}">${downs}</td>
        <td>${last}</td>
        <td>${spark(row.by_day)}</td>
      </tr>`;
    })
    .join("");
}

async function poll() {
  try {
    const response = await fetch("/api/history", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    rows = data.urls || [];
    statWindow.textContent = `${data.window_days || 90}d`;
    statUrls.textContent = String(data.url_count ?? rows.length);
    statDowns.textContent = String(data.total_downs ?? 0);
    statUpdated.textContent = data.generated_at
      ? new Date(data.generated_at).toLocaleTimeString()
      : "waiting…";
    render();
  } catch (error) {
    statUpdated.textContent = "error";
    bodyEl.innerHTML = `<tr><td colspan="8" class="empty-events">Could not load history.</td></tr>`;
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

poll();
setInterval(poll, 15000);
