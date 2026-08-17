const liveList = document.getElementById("live-list");
const availList = document.getElementById("avail-list");
const liveCount = document.getElementById("live-count");
const availCount = document.getElementById("avail-count");
const playlistBody = document.getElementById("playlist-body");
const lastCycle = document.getElementById("last-cycle");
const intervalEl = document.getElementById("interval");
const alertsEl = document.getElementById("alerts");
const modePill = document.getElementById("mode-pill");

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmtTime(iso) {
  if (!iso) {
    return "waiting…";
  }
  return new Date(iso).toLocaleString();
}

function flag(label, ok) {
  const cls = ok ? "ok" : "bad";
  const value = ok ? "ok" : "fail";
  return `<span class="flag ${cls}">${label} ${value}</span>`;
}

function card(item) {
  const state = item.healthy ? "up" : "down";
  const reason = item.fail_reason ? `<span>reason ${esc(item.fail_reason)}</span>` : "";
  const ips = item.resolved_ips?.length ? `<span>ip ${esc(item.resolved_ips.join(", "))}</span>` : "";
  const playlists = item.playlists?.length ? `<span>playlists ${esc(item.playlists.join(", "))}</span>` : "";
  return `
    <article class="card ${state}">
      <div class="card-top">
        <div class="url">${esc(item.url)}</div>
        <span class="pill ${state}">${state}</span>
      </div>
      <div class="flags">
        ${flag("dns", item.dns_ok)}
        ${flag("tcp", item.tcp_ok)}
        <span>fails ${item.consecutive_failures}</span>
        ${reason}
        ${ips}
        ${playlists}
      </div>
    </article>
  `;
}

function renderList(el, countEl, items, emptyText) {
  const up = items.filter((item) => item.healthy).length;
  countEl.textContent = items.length ? `${up}/${items.length} up` : "none";
  if (!items.length) {
    el.innerHTML = `<div class="empty">${emptyText}</div>`;
    return;
  }
  el.innerHTML = items.map(card).join("");
}

function renderPlaylists(items) {
  if (!items.length) {
    playlistBody.innerHTML = `<tr><td colspan="5">No playlists loaded. Copy config/playlists.example.yaml to config/playlists.yaml.</td></tr>`;
    return;
  }
  playlistBody.innerHTML = items
    .map((item) => {
      const cls = item.healthy ? "status-up" : "status-down";
      const label = item.healthy ? "up" : "down";
      return `
        <tr>
          <td>${esc(item.name)}</td>
          <td>${esc(item.playlist_id)}</td>
          <td>${esc(item.username)}</td>
          <td>${esc(item.current_dns)}</td>
          <td class="${cls}">${label}</td>
        </tr>
      `;
    })
    .join("");
}

function alertClass(text) {
  const lower = text.toLowerCase();
  if (lower.startsWith("dry run") || lower.includes("disabled")) {
    return "alert warn";
  }
  if (lower.startsWith("all portal urls are up")) {
    return "alert ok";
  }
  return "alert";
}

function renderAlerts(items, fallbackError) {
  const messages = [...(items || [])];
  if (fallbackError && !messages.includes(fallbackError)) {
    messages.unshift(fallbackError);
  }
  if (!messages.length) {
    alertsEl.hidden = true;
    alertsEl.innerHTML = "";
    return;
  }
  alertsEl.hidden = false;
  alertsEl.innerHTML = messages
    .map((text) => `<div class="${alertClass(text)}">${esc(text)}</div>`)
    .join("");
}

async function refresh() {
  try {
    const response = await fetch("/api/status");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    lastCycle.textContent = fmtTime(data.last_cycle_at);
    intervalEl.textContent = `${data.check_interval_seconds}s`;
    modePill.hidden = !data.dry_run;
    renderAlerts(data.alerts, data.error);
    renderList(liveList, liveCount, data.live || [], "No live portal URLs yet.");
    renderList(availList, availCount, data.available || [], "No standby URLs in urls.yaml.");
    renderPlaylists(data.playlists || []);
  } catch (error) {
    modePill.hidden = true;
    renderAlerts([`Dashboard cannot reach the monitor: ${error.message}`]);
  }
}

refresh();
setInterval(refresh, 4000);
