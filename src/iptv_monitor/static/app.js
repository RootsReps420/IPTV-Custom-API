/* Dashboard: poll /api/status every 4s and render playlists, URL cards, events. */

const liveList = document.getElementById("live-list");
const availList = document.getElementById("avail-list");
const liveCount = document.getElementById("live-count");
const availCount = document.getElementById("avail-count");
const playlistBody = document.getElementById("playlist-body");
const lastCycle = document.getElementById("last-cycle");
const nextCheck = document.getElementById("next-check");
const alertsEl = document.getElementById("alerts");
const modePill = document.getElementById("mode-pill");
const eventList = document.getElementById("event-list");
const statLive = document.getElementById("stat-live");
const statAvail = document.getElementById("stat-avail");
const statPlaylists = document.getElementById("stat-playlists");

const playlistSection = document.getElementById("playlists-section");
const playlistStatWrap = document.getElementById("stat-playlists-wrap");
const liveSection = document.getElementById("live-section");
const liveStatWrap = document.getElementById("stat-live-wrap");
const ownerLink = document.getElementById("owner-link");
const publicLink = document.getElementById("public-link");

function isOwnerView() {
  return location.pathname === "/owner" || location.pathname.startsWith("/owner/");
}

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
  return new Date(iso).toLocaleTimeString();
}

function secondsUntilNext(iso, interval) {
  if (!iso || !interval) {
    return null;
  }
  const due = new Date(iso).getTime() + interval * 1000;
  return Math.max(0, Math.ceil((due - Date.now()) / 1000));
}

function flag(label, ok) {
  // stream_ok is null when the MPEG-TS check was skipped (no creds, or an earlier check failed).
  if (ok === null || ok === undefined) {
    return `<span class="flag">${label} skip</span>`;
  }
  const cls = ok ? "ok" : "bad";
  const value = ok ? "ok" : "fail";
  return `<span class="flag ${cls}">${label} ${value}</span>`;
}

function nsLabel(item) {
  if (item.cloudflare_proxied) {
    return "Cloudflare proxy";
  }
  if (item.cloudflare) {
    return "Cloudflare NS";
  }
  if (item.nameserver) {
    return `ns ${item.nameserver}`;
  }
  return "";
}

function nsBadge(item) {
  const label = nsLabel(item);
  if (!label) {
    return "";
  }
  // Full NS hostnames (e.g. eric.ns.cloudflare.com) live in the hover tooltip.
  const title = (item.nameserver_hosts || []).join(", ");
  const cls = item.cloudflare ? "pill cf" : "pill ns";
  return `<span class="${cls}" title="${esc(title)}">${esc(label)}</span>`;
}

function card(item) {
  const state = item.healthy ? "up" : "down";
  const reason = item.fail_reason ? `<span>reason ${esc(item.fail_reason)}</span>` : "";
  const ips = item.resolved_ips?.length ? `<span>ip ${esc(item.resolved_ips.join(", "))}</span>` : "";
  const playlists = item.playlists?.length ? `<span>playlists ${esc(item.playlists.join(", "))}</span>` : "";
  const check = item.healthy
    ? `check-pass completed: ${item.consecutive_successes || 0}`
    : `fails ${item.consecutive_failures}`;
  const downs = `Service 'Down' count (24hr): ${item.down_events_24h || 0}`;
  const frequent = item.frequent_failure
    ? `<span class="pill frequent" title="${item.down_events_24h || 0} separate downs in 24h">Frequent failure</span>`
    : "";
  return `
    <article class="card ${state}${item.cloudflare ? " cf" : ""}${item.frequent_failure ? " frequent" : ""}">
      <div class="card-top">
        <div class="url">${esc(item.url)}</div>
        <div class="pills">
          ${nsBadge(item)}
          ${frequent}
          <span class="pill ${state}">${state}</span>
        </div>
      </div>
      <div class="flags">
        ${flag("dns", item.dns_ok)}
        ${flag("tcp", item.tcp_ok)}
        ${flag("ts", item.stream_ok)}
        ${reason}
        ${ips}
        ${playlists}
      </div>
      <div class="check-line">${esc(check)} <span class="sep">|</span> ${esc(downs)}</div>
    </article>
  `;
}

const CF_GROUPS = [
  { id: "proxy", title: "Cloudflare Proxy" },
  { id: "ns", title: "Cloudflare NS" },
  { id: "other", title: "Other" },
];

function renderGrouped(el, countEl, items, emptyText, grid) {
  const up = items.filter((item) => item.healthy).length;
  countEl.textContent = items.length ? `${up}/${items.length} up` : "none";
  if (!items.length) {
    el.innerHTML = `<div class="empty">${emptyText}</div>`;
    return;
  }
  const buckets = {
    proxy: items.filter((item) => item.cloudflare_proxied),
    ns: items.filter((item) => item.cloudflare && !item.cloudflare_proxied),
    other: items.filter((item) => !item.cloudflare),
  };
  const listClass = grid ? "cards cards-grid" : "cards";
  el.innerHTML = CF_GROUPS.map((group) => {
    const rows = buckets[group.id];
    if (!rows.length) {
      return "";
    }
    const groupUp = rows.filter((item) => item.healthy).length;
    return `
      <div class="url-group">
        <div class="url-group-head">
          <h3>${esc(group.title)}</h3>
          <span class="count">${groupUp}/${rows.length} up</span>
        </div>
        <div class="${listClass}">${rows.map(card).join("")}</div>
      </div>
    `;
  }).join("");
}

function renderPlaylists(items) {
  const playlistCount = document.getElementById("playlist-count");
  if (playlistCount) {
    playlistCount.textContent = items.length ? `${items.length} loaded` : "none";
  }
  if (!items.length) {
    playlistBody.innerHTML = `<tr><td colspan="6">No playlists loaded. Add entries in config/playlists.yaml — they appear within one check cycle.</td></tr>`;
    return;
  }
  playlistBody.innerHTML = items
    .map((item) => {
      const cls = item.healthy ? "status-up" : "status-down";
      const label = item.healthy ? "up" : "down";
      const ns = nsLabel(item) || "—";
      const nsCls = item.cloudflare ? "status-warn" : "";
      return `
        <tr>
          <td>${esc(item.name)}</td>
          <td>${esc(item.playlist_id)}</td>
          <td>${esc(item.username)}</td>
          <td>${esc(item.current_dns)}</td>
          <td class="${nsCls}">${esc(ns)}</td>
          <td class="${cls}">${label}</td>
        </tr>
      `;
    })
    .join("");
}

function renderEvents(items) {
  if (!items || !items.length) {
    eventList.innerHTML = `<li class="empty-events">No events yet this process. Downs, recoveries, and swaps show up here.</li>`;
    return;
  }
  eventList.innerHTML = items
    .map((item) => {
      const kind = esc(item.kind || "info");
      return `
        <li>
          <span class="event-time">${esc(fmtTime(item.ts))}</span>
          <span class="event-kind ${kind}">${kind}</span>
          <span>${esc(item.message)}</span>
        </li>
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

function tickCountdown() {
  if (!latest) {
    return;
  }
  const left = secondsUntilNext(latest.last_cycle_at, latest.check_interval_seconds);
  nextCheck.textContent = left === null ? "—" : `${left}s`;
}

async function refresh() {
  try {
    const owner = isOwnerView();
    const response = await fetch(owner ? "/api/status" : "/api/public");
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    latest = data;
    const counts = data.counts || {};
    const signedIn = Boolean(data.owner);
    lastCycle.textContent = fmtTime(data.last_cycle_at);
    statAvail.textContent = `${counts.available_up ?? "—"}/${counts.available_total ?? "—"} up`;
    if (playlistStatWrap) {
      playlistStatWrap.hidden = !signedIn;
    }
    if (liveStatWrap) {
      liveStatWrap.hidden = !signedIn;
    }
    if (signedIn) {
      statLive.textContent = `${counts.live_up ?? "—"}/${counts.live_total ?? "—"} up`;
      statPlaylists.textContent = String(counts.playlists ?? (data.playlists || []).length);
    }
    if (ownerLink) {
      ownerLink.hidden = signedIn;
    }
    if (publicLink) {
      publicLink.hidden = !signedIn;
    }
    if (playlistSection) {
      playlistSection.hidden = !signedIn;
    }
    if (liveSection) {
      liveSection.hidden = !signedIn;
    }
    modePill.hidden = !data.dry_run;
    tickCountdown();
    renderAlerts(data.alerts, data.error);
    renderGrouped(availList, availCount, data.available || [], "No standby URLs in urls.yaml.", true);
    if (signedIn) {
      renderGrouped(liveList, liveCount, data.live || [], "No live portal URLs yet.", false);
      renderPlaylists(data.playlists || []);
    }
    renderEvents(data.events || []);
  } catch (error) {
    modePill.hidden = true;
    latest = null;
    nextCheck.textContent = "—";
    renderAlerts([`Dashboard cannot reach the monitor: ${error.message}`]);
  }
}

refresh();
setInterval(refresh, 4000);
setInterval(tickCountdown, 1000);
