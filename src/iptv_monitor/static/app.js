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
const watchersSection = document.getElementById("watchers-section");
const watchersBody = document.getElementById("watchers-body");
const watchStatWrap = document.getElementById("stat-watch-wrap");
const statWatch = document.getElementById("stat-watch");
const liveGroupsSection = document.getElementById("live-groups-section");
const liveGroupsList = document.getElementById("live-groups-list");
const liveGroupsCount = document.getElementById("live-groups-count");
const liveGroupsFilter = document.getElementById("live-groups-filter");
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

function fmtAge(seconds) {
  const n = Math.max(0, Number(seconds) || 0);
  if (n < 60) {
    return `${n}s`;
  }
  if (n < 3600) {
    const m = Math.floor(n / 60);
    const s = n % 60;
    return s ? `${m}m ${s}s` : `${m}m`;
  }
  const h = Math.floor(n / 3600);
  const m = Math.floor((n % 3600) / 60);
  return m ? `${h}h ${m}m` : `${h}h`;
}

function watchKindLabel(kind) {
  if (kind === "live") {
    return "Live";
  }
  if (kind === "movie") {
    return "Movie";
  }
  if (kind === "series") {
    return "Series";
  }
  return "";
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
let switchNotice = "";
let switchNoticeUntil = 0;
// Keep Choose URL open across 4s re-renders.
let pickOpen = null;
let pickValue = "";
let liveGroups = [];
let liveGroupsView = "all";
let liveGroupsLoaded = false;
const togglingGroups = new Set();

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
      const magnum = item.pool === "magnum";
      const title = target
        ? magnum
          ? `Switch to ${hostOf(target)} (Magnum pool only). Fresh MPEG-TS check first. Watch follows this DNS.`
          : `Switch to ${hostOf(target)} (fresh MPEG-TS check first)`
        : magnum
          ? "No healthy Magnum standby right now"
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
                  ? `<span class="monitor-only" title="No automatic swap. Switch still calls EPGenius within this playlist's pool.">Manual only</span>`
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

function fmtRes(width, height) {
  const w = Number(width) || 0;
  const h = Number(height) || 0;
  if (!w || !h) {
    return "";
  }
  let tag = "";
  if (w >= 3800 || h >= 2100) {
    tag = "4K";
  } else if (w >= 2500 || h >= 1400) {
    tag = "1440p";
  } else if (w >= 1800 || h >= 800) {
    tag = "1080p";
  } else if (w >= 1200 || h >= 700) {
    tag = "720p";
  }
  return tag ? `${w}×${h} ${tag}` : `${w}×${h}`;
}

function fmtMbps(kbps) {
  const n = Number(kbps) || 0;
  if (n <= 0) {
    return "";
  }
  if (n >= 1000) {
    return `${(n / 1000).toFixed(1)} Mb/s`;
  }
  return `${Math.round(n)} kb/s`;
}

function qualityClass(level) {
  if (level === "good") {
    return "status-play";
  }
  if (level === "ok") {
    return "status-warn";
  }
  if (level === "poor") {
    return "status-down";
  }
  return "";
}

function renderWatchers(watch) {
  if (!watchersSection || !watchersBody) {
    return;
  }
  const sessions = watch?.sessions || [];
  const slots = watch?.slots || {};
  const countEl = document.getElementById("watchers-count");
  const playing = watch?.playing || 0;
  const online = watch?.online || sessions.length;
  const slotBit =
    slots.max != null ? ` · slots ${slots.used ?? 0}/${slots.max}` : "";
  if (countEl) {
    countEl.textContent = sessions.length
      ? `${online} online · ${playing} playing${slotBit}`
      : "none";
  }
  if (!sessions.length) {
    watchersBody.innerHTML = `<tr><td colspan="7">Nobody is signed in to /watch right now.</td></tr>`;
    return;
  }
  watchersBody.innerHTML = sessions
    .map((row) => {
      const playingNow = Boolean(row.playing);
      const kind = watchKindLabel(row.kind);
      const title = row.title || "";
      const detail = row.detail || "";
      const watching = playingNow
        ? `${kind ? `${kind} · ` : ""}${title || "Playing…"}`
        : "Browsing";
      const extra = [];
      if (playingNow && detail && detail !== title) {
        extra.push(`<span class="muted">${esc(detail)}</span>`);
      }
      if (playingNow && row.watching_seconds) {
        extra.push(`<span class="muted">on this ${esc(fmtAge(row.watching_seconds))}</span>`);
      }
      const bits = [];
      if (row.quality) {
        bits.push(row.quality);
      }
      const rate = fmtMbps(row.kbps);
      if (rate) {
        bits.push(rate);
      }
      if (row.width && row.height) {
        bits.push(fmtRes(row.width, row.height));
      }
      if (row.audio) {
        bits.push(row.audio);
      }
      const qualMain = bits.length ? bits.join(" · ") : playingNow ? "measuring…" : "—";
      const qualExtra = [];
      if (playingNow && row.buffer_s) {
        qualExtra.push(`${row.buffer_s}s buffer`);
      }
      if (playingNow && row.stalls_60s) {
        qualExtra.push(`${row.stalls_60s} stall${row.stalls_60s === 1 ? "" : "s"}/min`);
      }
      if (playingNow && row.drop_pct) {
        qualExtra.push(`${row.drop_pct}% drops`);
      }
      const who = String(row.username || "");
      const kicking = switching.has(`kick:${who}`);
      return `
        <tr>
          <td>${esc(who)}</td>
          <td>${esc(fmtAge(row.logged_in_seconds))}</td>
          <td>${esc(row.ip || "—")}</td>
          <td class="${playingNow ? "status-play" : ""}">${playingNow ? "playing" : "idle"}</td>
          <td class="quality-cell ${qualityClass(row.quality)}">${esc(qualMain)}${
            qualExtra.length ? `<span class="muted">${esc(qualExtra.join(" · "))}</span>` : ""
          }</td>
          <td class="watching-cell">${esc(watching)}${extra.join("")}</td>
          <td>
            <button type="button" class="switch-btn kick${kicking ? " busy" : ""}" data-kick="${esc(who)}" ${
              kicking ? "disabled" : ""
            } title="Sign ${esc(who)} out of /watch on every tab and device">Log out</button>
          </td>
        </tr>
      `;
    })
    .join("");
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
    if (data.watch) {
      switchNotice = `Swapped to ${hostOf(data.to)}. Watch will refresh the list shortly.`;
      switchNoticeUntil = Date.now() + 20000;
    }
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

async function kickWatchUser(username) {
  const who = String(username || "").trim();
  const key = `kick:${who}`;
  if (!who || switching.has(key)) {
    return;
  }
  if (!window.confirm(`Sign ${who} out of Watch on every tab and device?`)) {
    return;
  }
  switching.add(key);
  if (latest) {
    renderWatchers(latest.watch);
  }
  try {
    const response = await fetch("/api/status", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: who, kick: true }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(apiError(data, `HTTP ${response.status}`));
    }
    await refresh();
  } catch (error) {
    renderAlerts([`Could not sign ${who} out: ${error.message}`]);
  } finally {
    switching.delete(key);
    if (latest) {
      renderWatchers(latest.watch);
    }
  }
}

function liveGroupMatches(row) {
  if (liveGroupsView === "on" && !row.enabled) {
    return false;
  }
  if (liveGroupsView === "off" && row.enabled) {
    return false;
  }
  const query = (liveGroupsFilter?.value || "").trim().toLowerCase();
  if (!query) {
    return true;
  }
  return String(row.name || "").toLowerCase().includes(query);
}

function renderLiveGroups() {
  if (!liveGroupsList) {
    return;
  }
  const on = liveGroups.filter((row) => row.enabled).length;
  const total = liveGroups.length;
  if (liveGroupsCount) {
    liveGroupsCount.textContent = total ? `${on} on · ${total - on} off` : "";
  }
  document.querySelectorAll("[data-groups-view]").forEach((button) => {
    button.classList.toggle("is-here", button.getAttribute("data-groups-view") === liveGroupsView);
  });
  if (!total) {
    liveGroupsList.innerHTML = `<div class="empty-events">No live groups in the Watch playlist yet. Wait for a Magnum refresh.</div>`;
    return;
  }
  const rows = liveGroups.filter(liveGroupMatches);
  if (!rows.length) {
    liveGroupsList.innerHTML = `<div class="empty-events">No groups match that filter.</div>`;
    return;
  }
  liveGroupsList.innerHTML = rows
    .map((row) => {
      const enabled = !!row.enabled;
      const busy = togglingGroups.has(String(row.category_id || ""));
      const count = Number(row.channels) || 0;
      const label = count === 1 ? "1 channel" : `${count} channels`;
      return `<div class="live-group-row ${enabled ? "is-on" : "is-off"}">
        <span class="live-group-copy">
          <span class="live-group-name">${esc(row.name)}</span>
          <span class="live-group-meta">${esc(label)}</span>
        </span>
        <button type="button" class="live-group-toggle${busy ? " busy" : ""}" role="switch" aria-checked="${enabled ? "true" : "false"}" data-group-id="${esc(row.category_id)}" ${busy ? "disabled" : ""}>${enabled ? "On" : "Off"}</button>
      </div>`;
    })
    .join("");
}

async function loadLiveGroups() {
  if (!isOwnerView() || !liveGroupsSection) {
    return;
  }
  try {
    const response = await fetch("/api/live-groups", { credentials: "same-origin" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(apiError(data, `HTTP ${response.status}`));
    }
    liveGroups = data.groups || [];
    liveGroupsLoaded = true;
    renderLiveGroups();
  } catch (error) {
    liveGroupsLoaded = false;
    if (liveGroupsList) {
      liveGroupsList.innerHTML = `<div class="empty-events">Could not load live groups: ${esc(error.message)}</div>`;
    }
  }
}

async function toggleLiveGroup(categoryId, enabled) {
  const id = String(categoryId || "").trim();
  if (!id || togglingGroups.has(id)) {
    return;
  }
  togglingGroups.add(id);
  const previous = liveGroups;
  const current = liveGroups.find((row) => String(row.category_id || "") === id);
  liveGroups = liveGroups.map((row) =>
    String(row.category_id || "") === id ? { ...row, enabled } : row
  );
  renderLiveGroups();
  try {
    const response = await fetch("/api/live-groups", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        category_id: id,
        name: current?.name || "",
        enabled,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(apiError(data, `HTTP ${response.status}`));
    }
    liveGroups = data.groups || [];
  } catch (error) {
    liveGroups = previous;
    switchNotice = `Could not update live group: ${error.message}`;
    switchNoticeUntil = Date.now() + 8000;
    renderAlerts([switchNotice]);
  } finally {
    togglingGroups.delete(id);
    renderLiveGroups();
  }
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

if (watchersBody) {
  watchersBody.addEventListener("click", (event) => {
    const button = event.target.closest("[data-kick]");
    if (!button || button.disabled) {
      return;
    }
    kickWatchUser(button.getAttribute("data-kick"));
  });
}

if (liveGroupsList) {
  liveGroupsList.addEventListener("click", (event) => {
    const row = event.target.closest(".live-group-row");
    if (!row) {
      return;
    }
    const button = row.querySelector("[data-group-id]");
    if (!button || button.disabled) {
      return;
    }
    const next = button.getAttribute("aria-checked") !== "true";
    toggleLiveGroup(button.getAttribute("data-group-id"), next);
  });
}

if (liveGroupsFilter) {
  liveGroupsFilter.addEventListener("input", () => {
    renderLiveGroups();
  });
}

document.querySelectorAll("[data-groups-view]").forEach((button) => {
  button.addEventListener("click", () => {
    liveGroupsView = button.getAttribute("data-groups-view") || "all";
    renderLiveGroups();
  });
});

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
  if (lower.startsWith("watch dns")) {
    return "alert ok";
  }
  return "alert";
}

function renderAlerts(items, fallbackError) {
  const messages = [...(items || [])];
  if (switchNotice && Date.now() < switchNoticeUntil) {
    messages.unshift(switchNotice);
  } else {
    switchNotice = "";
  }
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
    if (watchStatWrap) {
      watchStatWrap.hidden = !signedIn;
    }
    if (signedIn) {
      statLive.textContent = `${counts.live_up ?? "—"}/${counts.live_total ?? "—"} up`;
      statPlaylists.textContent = String(counts.playlists ?? (data.playlists || []).length);
      if (statWatch) {
        const online = counts.watch_online ?? (data.watch?.online ?? 0);
        const playing = counts.watch_playing ?? (data.watch?.playing ?? 0);
        statWatch.textContent = `${playing} playing · ${online} online`;
      }
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
    if (watchersSection) {
      watchersSection.hidden = !signedIn;
    }
    if (liveGroupsSection) {
      liveGroupsSection.hidden = !signedIn;
      if (signedIn && isOwnerView() && !liveGroupsLoaded) {
        loadLiveGroups();
      }
    }
    modePill.hidden = !data.dry_run;
    tickCountdown();
    renderAlerts(data.alerts, data.error);
    renderGrouped(availList, availCount, data.available || [], "No standby URLs in urls.yaml.", true);
    if (signedIn) {
      renderGrouped(liveList, liveCount, data.live || [], "No live portal URLs yet.", false);
      renderPlaylists(data.playlists || []);
      renderWatchers(data.watch);
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
