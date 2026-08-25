/* Dashboard: poll /api/status (owner) or /api/public every 4s.
 * Renders URL cards, events, and (owner only) playlists + Switch / Choose URL.
 * Same script on `/` and `/owner` — isOwnerView() picks the API.
 */

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
const watchLink = document.getElementById("watch-link");

function isOwnerView() {
  // Caddy only protects /owner; this path check is what shows playlists in JS.
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

function poolBadge(item) {
  const label = item.pool_label || (item.pool === "magnum" ? "Magnum" : "Strong 8K");
  const cls = item.pool === "magnum" ? "pill magnum" : "pill strong8k";
  return `<span class="${cls}">${esc(label)}</span>`;
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
          ${poolBadge(item)}
          ${nsBadge(item)}
          ${frequent}
          <span class="pill ${state}">${state}</span>
        </div>
      </div>
      <div class="flags">
        ${flag("dns", item.dns_ok)}
        ${flag("tcp", item.tcp_ok)}
        ${flag("mpeg-ts", item.stream_ok)}
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
  const magnum = items.filter((item) => item.pool === "magnum");
  const rest = items.filter((item) => item.pool !== "magnum");
  const buckets = {
    proxy: rest.filter((item) => item.cloudflare_proxied),
    ns: rest.filter((item) => item.cloudflare && !item.cloudflare_proxied),
    other: rest.filter((item) => !item.cloudflare),
  };
  const listClass = grid ? "cards cards-grid" : "cards";
  const magnumBlock = magnum.length
    ? `
      <div class="url-group">
        <div class="url-group-head">
          <h3>Magnum</h3>
          <span class="count">${magnum.filter((item) => item.healthy).length}/${magnum.length} up</span>
        </div>
        <div class="${listClass}">${magnum.map(card).join("")}</div>
      </div>
    `
    : "";
  el.innerHTML =
    magnumBlock +
    CF_GROUPS.map((group) => {
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

const switching = new Set();
// Keep Choose URL open across 4s re-renders.
let pickOpen = null;
let pickValue = "";

function hostOf(url) {
  try {
    return new URL(url).hostname || url;
  } catch {
    return url;
  }
}

function apiError(data, fallback) {
  if (!data) {
    return fallback;
  }
  if (typeof data.detail === "string") {
    return data.detail;
  }
  if (Array.isArray(data.detail) && data.detail.length) {
    return data.detail.map((item) => item.msg || item).join("; ");
  }
  return fallback;
}

function poolChoices(playlist) {
  const current = String(playlist.current_dns || "");
  const pool = playlist.pool || "strong8k";
  return (latest?.available || [])
    .filter((item) => item.url && item.url !== current && (item.pool || "strong8k") === pool)
    .slice()
    .sort((a, b) => {
      if (Boolean(a.healthy) !== Boolean(b.healthy)) {
        return a.healthy ? -1 : 1;
      }
      return hostOf(a.url).localeCompare(hostOf(b.url));
    });
}

function pickerMarkup(item, id, dryRun, busy) {
  if (pickOpen !== id) {
    return "";
  }
  const choices = poolChoices(item);
  if (!choices.length) {
    return `<div class="switch-picker"><span class="muted">No other URLs in the pool.</span></div>`;
  }
  const options = choices
    .map((row) => {
      const selected = pickValue === row.url ? " selected" : "";
      const disabled = row.healthy ? "" : " disabled";
      const kind = row.cloudflare_proxied
        ? "CF proxy"
        : row.cloudflare
          ? "CF NS"
          : "origin";
      const state = row.healthy ? "up" : "down";
      const frequent = row.frequent_failure ? " · frequent" : "";
      return `<option value="${esc(row.url)}"${selected}${disabled}>${esc(hostOf(row.url))} · ${state} · ${kind}${frequent}</option>`;
    })
    .join("");
  const selectedHealthy = choices.some((row) => row.url === pickValue && row.healthy);
  const canGo = selectedHealthy && !dryRun && !busy;
  return `
    <div class="switch-picker">
      <select data-pick-url="${esc(id)}" ${busy ? "disabled" : ""}>
        <option value="">Select a URL…</option>
        ${options}
      </select>
      <button
        type="button"
        class="switch-btn${busy ? " busy" : ""}"
        data-pick-go="${esc(id)}"
        ${canGo ? "" : "disabled"}
      >${busy ? "Switching…" : "Switch to this"}</button>
    </div>
  `;
}

function renderPlaylists(items) {
  // Re-render replaces innerHTML; restore Choose URL dropdown focus if it was open.
  const keepPickerFocus = Boolean(
    document.activeElement && document.activeElement.matches("[data-pick-url]")
  );
  const playlistCount = document.getElementById("playlist-count");
  if (playlistCount) {
    playlistCount.textContent = items.length ? `${items.length} loaded` : "none";
  }
  if (!items.length) {
    playlistBody.innerHTML = `<tr><td colspan="7">No playlists loaded. Add entries in config/playlists.yaml — they appear within one check cycle.</td></tr>`;
    return;
  }
  const dryRun = Boolean(latest && latest.dry_run);
  playlistBody.innerHTML = items
    .map((item) => {
      const cls = item.healthy ? "status-up" : "status-down";
      const label = item.healthy ? "up" : "down";
      const ns = nsLabel(item) || "—";
      const nsCls = item.cloudflare ? "status-warn" : "";
      const id = String(item.playlist_id ?? "");
      const busy = switching.has(id);
      const autoOff = item.failover === false;
      const target = item.next_standby;
      const canSwitch = Boolean(target) && !dryRun;
      const title = target
        ? `Switch to ${hostOf(target)}`
        : "No healthy standby right now";
      const btnLabel = busy ? "Switching…" : "Switch";
      const revertTo = item.revert_dns;
      const canRevert = Boolean(revertTo) && !dryRun;
      const revertTitle = revertTo
        ? `Switch back to ${hostOf(revertTo)} (health-checked first)`
        : "";
      const revertLabel = busy ? "Checking…" : "Switch back";
      const chooseOpen = pickOpen === id;
      const chooseLabel = chooseOpen ? "Close" : "Choose URL";
      return `
        <tr>
          <td>${esc(item.name)}${
            item.pool_label
              ? ` <span class="pill ${item.pool === "magnum" ? "magnum" : "strong8k"}">${esc(item.pool_label)}</span>`
              : ""
          }</td>
          <td>${esc(item.playlist_id)}</td>
          <td>${esc(item.username)}</td>
          <td>${esc(item.current_dns)}</td>
          <td class="${nsCls}">${esc(ns)}</td>
          <td class="${cls}">${label}</td>
          <td>
            <div class="switch-actions">
              ${
                autoOff
                  ? `<span class="monitor-only" title="No automatic EPGenius swap. Switch stays inside the Magnum URL pool.">Manual only</span>`
                  : ""
              }
              <button
                type="button"
                class="switch-btn${busy ? " busy" : ""}"
                data-switch="${esc(id)}"
                title="${esc(title)}"
                ${canSwitch && !busy ? "" : "disabled"}
              >${btnLabel}</button>
              <button
                type="button"
                class="switch-btn choose${chooseOpen ? " is-here" : ""}"
                data-choose="${esc(id)}"
                title="Pick a specific URL from this playlist's pool"
                ${dryRun || busy ? "disabled" : ""}
              >${chooseLabel}</button>
              ${
                revertTo
                  ? `<button
                type="button"
                class="switch-btn revert${busy ? " busy" : ""}"
                data-revert="${esc(id)}"
                title="${esc(revertTitle)}"
                ${canRevert && !busy ? "" : "disabled"}
              >${revertLabel}</button>`
                  : ""
              }
            </div>
            ${pickerMarkup(item, id, dryRun, busy)}
          </td>
        </tr>
      `;
    })
    .join("");
  if (keepPickerFocus) {
    const next = playlistBody.querySelector("[data-pick-url]");
    if (next) {
      next.focus();
    }
  }
}

async function postSwitch(path, playlistId, failPrefix, extra = {}) {
  if (!playlistId || switching.has(playlistId)) {
    return;
  }
  switching.add(playlistId);
  if (latest) {
    renderPlaylists(latest.playlists || []);
  }
  try {
    const response = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ playlist_id: playlistId, ...extra }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(apiError(data, `HTTP ${response.status}`));
    }
    pickOpen = null;
    pickValue = "";
    await refresh();
  } catch (error) {
    renderAlerts([`${failPrefix}: ${error.message}`]);
  } finally {
    switching.delete(playlistId);
    if (latest) {
      renderPlaylists(latest.playlists || []);
    }
  }
}

function switchPlaylist(playlistId, targetUrl) {
  const extra = targetUrl ? { target_url: targetUrl } : {};
  return postSwitch("/api/switch", playlistId, "Switch failed", extra);
}

function switchBackPlaylist(playlistId) {
  return postSwitch("/api/switch-back", playlistId, "Switch back failed");
}

if (playlistBody) {
  playlistBody.addEventListener("click", (event) => {
    const revert = event.target.closest("[data-revert]");
    if (revert && !revert.disabled) {
      switchBackPlaylist(revert.getAttribute("data-revert"));
      return;
    }
    const choose = event.target.closest("[data-choose]");
    if (choose && !choose.disabled) {
      const id = choose.getAttribute("data-choose");
      pickOpen = pickOpen === id ? null : id;
      pickValue = "";
      if (latest) {
        renderPlaylists(latest.playlists || []);
      }
      return;
    }
    const go = event.target.closest("[data-pick-go]");
    if (go && !go.disabled) {
      const id = go.getAttribute("data-pick-go");
      if (!pickValue) {
        return;
      }
      switchPlaylist(id, pickValue);
      return;
    }
    const button = event.target.closest("[data-switch]");
    if (!button || button.disabled) {
      return;
    }
    switchPlaylist(button.getAttribute("data-switch"));
  });
  playlistBody.addEventListener("change", (event) => {
    const select = event.target.closest("[data-pick-url]");
    if (!select) {
      return;
    }
    pickOpen = select.getAttribute("data-pick-url");
    pickValue = select.value;
    if (latest) {
      const keepFocus = true;
      renderPlaylists(latest.playlists || []);
      if (keepFocus) {
        const next = playlistBody.querySelector("[data-pick-url]");
        if (next) {
          next.focus();
        }
      }
    }
  });
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
  // Owner path talks to /api/status (Caddy auth). Public path uses /api/public.
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
    if (watchLink) {
      watchLink.hidden = !signedIn;
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
