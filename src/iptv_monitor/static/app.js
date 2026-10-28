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
const eventCount = document.getElementById("event-count");
const downNowEl = document.getElementById("down-now");
const statLive = document.getElementById("stat-live");
const statPlaylists = document.getElementById("stat-playlists");
// Last /api/status or /api/public payload (null until the first poll lands or after an error).
let latest = null;
const heroEl = document.getElementById("hero");
const matrixEl = document.getElementById("matrix");
const matrixCount = document.getElementById("matrix-count");

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
const ownerSubnav = document.getElementById("owner-subnav");

// shell.js owns the sidebar status + the overall-state wording (shared with History / Info).
function setSideStatus(level, text) {
  window.consoleShell?.setStatus(level, text);
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = text;
  }
}

function setPageHeading(owner) {
  const title = document.getElementById("page-title");
  const sub = document.getElementById("page-sub");
  if (title) {
    title.textContent = owner ? "Playlists" : "Monitor";
  }
  if (sub) {
    sub.textContent = owner
      ? "Playlists, what's on air, Watch sessions and the standby pool"
      : "Standby pool health, live signal map and recent events";
  }
  document.title = `${owner ? "Playlists" : "Monitor"} · IPTV Portal Monitor`;
}

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

function secondsSince(iso) {
  if (!iso) {
    return null;
  }
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
}

function agoLabel(iso) {
  const n = secondsSince(iso);
  if (n === null) {
    return "";
  }
  return n < 5 ? "just now" : `${fmtAge(n)} ago`;
}

const REASON_LABELS = {
  tcp_timeout: "Connection timed out",
  tcp_refused: "Connection refused",
  tcp_error: "Connection error",
  dns_nxdomain: "Domain does not exist",
  dns_timeout: "DNS lookup timed out",
  dns_no_records: "No DNS records",
  dns_no_nameservers: "No working nameservers",
  dns_error: "DNS error",
  stream_no_api: "Xtream API missing (404)",
  stream_blocked: "Panel blocked the request",
  stream_452: "Panel rejected this host",
  stream_auth: "Account not authorised",
  stream_no_mpegts: "No MPEG-TS on live path",
  stream_timeout: "Stream timed out",
  stream_error: "Stream request failed",
  stream_not_verified: "Pre-swap stream check failed",
  check_error: "Health check crashed",
  not_checked: "Not checked yet",
};

function reasonLabel(reason) {
  return REASON_LABELS[reason] || reason || "Down";
}

function hostLabel(url) {
  try {
    return new URL(url).host || url;
  } catch {
    return String(url).replace(/^https?:\/\//i, "");
  }
}

function hostChips(urls) {
  return (urls || [])
    .map((url) => `<span class="alert-host" title="${esc(url)}">${esc(hostLabel(url))}</span>`)
    .join("");
}

// Keep <details> open across the 4s re-render.
function openDetailKeys(root) {
  return new Set([...root.querySelectorAll("details[open][data-key]")].map((el) => el.dataset.key));
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

function flag(label, ok, item) {
  // stream_ok is null when the check was skipped, or Strong 8K is not visible from the VPS.
  if (ok === null || ok === undefined) {
    const vpsBlind = Boolean(item && item.healthy && label === "xtream");
    return `<span class="flag">${label} ${vpsBlind ? "vps-blind" : "skip"}</span>`;
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

function poolLane(item) {
  if (item.pool === "magnum") {
    return "magnum";
  }
  if (item.vpn) {
    return "strong8k-vpn";
  }
  return "strong8k";
}

function poolBadge(item) {
  const vpn = Boolean(item.vpn) && item.pool !== "magnum";
  const label = item.pool_label || (item.pool === "magnum" ? "Magnum" : vpn ? "Strong 8K VPN" : "Strong 8K");
  const cls = item.pool === "magnum" ? "pill magnum" : vpn ? "pill vpn-dns" : "pill strong8k";
  return `<span class="${cls}">${esc(label)}</span>`;
}

function ipRow(ips) {
  const v4 = (ips || []).filter((ip) => ip && !String(ip).includes(":"));
  if (!v4.length) {
    return "";
  }
  const chips = v4
    .map((ip) => `<span class="ip-chip" title="${esc(ip)}">${esc(ip)}</span>`)
    .join("");
  return `<div class="ip-row"><span class="ip-label">IPs</span><div class="ip-chips">${chips}</div></div>`;
}

// Signal bars: 4 = up, no outages in 24h; 3 = up, recovered from 1-2; 2 = flapping; 0 = down.
function signalLevel(item) {
  if (!item.healthy) {
    return 0;
  }
  if (item.frequent_failure) {
    return 2;
  }
  return (item.down_events_24h || 0) > 0 ? 3 : 4;
}

const SIGNAL_TEXT = {
  4: "Strong signal",
  3: "Good signal",
  2: "Weak signal · flapping",
  0: "No signal · down",
};

function outagesText(item) {
  const n = item.down_events_24h || 0;
  return `${n} outage${n === 1 ? "" : "s"} in 24h`;
}

function laneLabel(item) {
  const lane = item.pool === "magnum" ? "Magnum" : item.vpn ? "Strong 8K VPN" : "Strong 8K";
  const ns = nsLabel(item);
  return ns ? `${lane} · ${ns}` : lane;
}

function signalBars(item) {
  const level = signalLevel(item);
  const label = `${SIGNAL_TEXT[level]} — ${outagesText(item)}`;
  return `<span class="signal s${level}" role="img" aria-label="${esc(label)}" data-tip-title="${esc(SIGNAL_TEXT[level])}" data-tip-body="${esc(outagesText(item))}"><i></i><i></i><i></i><i></i></span>`;
}

// Matrix click → scroll to this URL's card and flash it (survives one 4s re-render).
let flashUrl = "";
let flashUntil = 0;

function card(item, { live = false } = {}) {
  const state = item.healthy ? "up" : "down";
  const reason = item.fail_reason
    ? `<span class="card-reason" title="${esc(item.fail_reason)}${
        item.error_detail ? ` · ${esc(String(item.error_detail).slice(0, 80))}` : ""
      }">${esc(reasonLabel(item.fail_reason))}</span>`
    : "";
  const playlists = item.playlists?.length
    ? `<div class="card-playlists"><span>Used by</span>${item.playlists.map((name) => `<b>${esc(name)}</b>`).join("")}</div>`
    : "";
  const downFor = item.down_since ? ` · down ${fmtAge(secondsSince(item.down_since))}` : "";
  const streak = item.healthy
    ? `${item.consecutive_successes || 0} passes in a row`
    : `${item.consecutive_failures || 0} fails in a row${downFor}`;
  const checked = item.last_checked ? `checked ${agoLabel(item.last_checked)}` : "";
  const frequent = item.frequent_failure
    ? `<span class="pill frequent" title="${item.down_events_24h || 0} separate downs in 24h">Frequent failure</span>`
    : "";
  const tsLabel = item.pool === "magnum" ? "mpeg-ts" : "xtream";
  const onAir = live ? `<span class="onair ${state}">${item.healthy ? "On air" : "Off air"}</span>` : "";
  const flash = item.url === flashUrl && Date.now() < flashUntil ? " flash" : "";
  return `
    <article class="card ${state}${item.frequent_failure ? " frequent" : ""}${live ? " live" : ""}${flash}" data-url="${esc(item.url)}">
      <div class="card-top">
        <div class="card-title">${onAir}<span class="url" title="${esc(item.url)}">${esc(hostLabel(item.url))}</span></div>
        ${signalBars(item)}
      </div>
      <div class="pills">
        <span class="pill ${state}">${state}</span>
        ${poolBadge(item)}
        ${nsBadge(item)}
        ${frequent}
      </div>
      <div class="flags">
        ${flag("dns", item.dns_ok)}
        ${flag("tcp", item.tcp_ok)}
        ${flag(tsLabel, item.stream_ok, item)}
        ${reason}
      </div>
      ${playlists}
      ${ipRow(item.resolved_ips)}
      <div class="card-foot"><span>${esc(streak)}</span><span>${esc(outagesText(item))}</span><span>${esc(checked)}</span></div>
    </article>
  `;
}

const CF_GROUPS = [
  { id: "proxy", title: "Cloudflare Proxy" },
  { id: "ns", title: "Cloudflare NS" },
  { id: "other", title: "Other" },
];

const POOL_TABS = [
  { id: "all", title: "All" },
  { id: "strong8k", title: "Strong 8K" },
  { id: "strong8k-vpn", title: "Strong 8K VPN" },
  { id: "magnum", title: "Magnum" },
];

const poolView = {
  avail: "all",
  live: "all",
};

function poolTabsMarkup(tabKey, items) {
  return `
    <div class="pool-tabs" role="tablist">
      ${POOL_TABS.map((tab) => {
        const rows = tab.id === "all" ? items : items.filter((item) => poolLane(item) === tab.id);
        const up = rows.filter((item) => item.healthy).length;
        const here = poolView[tabKey] === tab.id ? " is-here" : "";
        return `<button type="button" class="sort-btn${here}" data-pool-tab="${tab.id}" data-pool-for="${tabKey}">${esc(tab.title)} <span class="count">${rows.length ? `${up}/${rows.length}` : "0"}</span></button>`;
      }).join("")}
    </div>
  `;
}

function groupBlock(title, rows, listClass, live = false) {
  if (!rows.length) {
    return "";
  }
  const groupUp = rows.filter((item) => item.healthy).length;
  const groupDown = rows.length - groupUp;
  // Down first so problems are at the top of each group; stable otherwise.
  const ordered = [...rows].sort((a, b) => Number(a.healthy) - Number(b.healthy));
  return `
    <div class="url-group">
      <div class="url-group-head">
        <h3>${esc(title)}</h3>
        <span class="count${groupDown ? " has-down" : ""}">${groupUp}/${rows.length} up${groupDown ? ` · ${groupDown} down` : ""}</span>
      </div>
      <div class="${listClass}">${ordered.map((item) => card(item, { live })).join("")}</div>
    </div>
  `;
}

function renderGrouped(el, countEl, items, emptyText, grid, tabKey) {
  const view = poolView[tabKey] || "all";
  const filtered = view === "all" ? items : items.filter((item) => poolLane(item) === view);
  const up = filtered.filter((item) => item.healthy).length;
  countEl.textContent = items.length ? `${up}/${filtered.length} up` : "none";
  const tabs = poolTabsMarkup(tabKey, items);
  if (!items.length) {
    el.innerHTML = `${tabs}<div class="empty">${emptyText}</div>`;
    return;
  }
  if (!filtered.length) {
    const emptyLane =
      view === "strong8k-vpn"
        ? "No Strong 8K VPN DNS in urls.yaml yet. Add hosts under vpn:."
        : emptyText;
    el.innerHTML = `${tabs}<div class="empty">${emptyLane}</div>`;
    return;
  }
  const magnum = filtered.filter((item) => item.pool === "magnum");
  const vpn = filtered.filter((item) => item.vpn && item.pool !== "magnum");
  const rest = filtered.filter((item) => item.pool !== "magnum" && !item.vpn);
  const buckets = {
    proxy: rest.filter((item) => item.cloudflare_proxied),
    ns: rest.filter((item) => item.cloudflare && !item.cloudflare_proxied),
    other: rest.filter((item) => !item.cloudflare),
  };
  const listClass = grid ? "cards cards-grid" : "cards";
  const live = tabKey === "live";
  const vpnBlock = groupBlock("Strong 8K VPN", vpn, listClass, live);
  const magnumBlock = groupBlock("Magnum", magnum, listClass, live);
  const cfBlocks = CF_GROUPS.map((group) => groupBlock(group.title, buckets[group.id], listClass, live)).join("");
  el.innerHTML = tabs + magnumBlock + vpnBlock + cfBlocks;
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

function pickerIsMounted() {
  if (!pickOpen || !playlistBody) {
    return false;
  }
  const select = playlistBody.querySelector("[data-pick-url]");
  return Boolean(select && select.getAttribute("data-pick-url") === pickOpen);
}

function syncPickerGoButton() {
  const go = playlistBody && playlistBody.querySelector("[data-pick-go]");
  const select = playlistBody && playlistBody.querySelector("[data-pick-url]");
  if (!go || !select) {
    return;
  }
  const option = select.selectedOptions && select.selectedOptions[0];
  const healthy = Boolean(select.value) && option && !option.disabled;
  const busy = switching.has(select.getAttribute("data-pick-url"));
  const dryRun = Boolean(latest && latest.dry_run);
  go.disabled = !healthy || busy || dryRun;
}

function pickerMarkup(item, id, dryRun, busy) {
  if (pickOpen !== id) {
    return "";
  }
  const choices = poolChoices(item);
  if (!choices.length) {
    return `<div class="switch-picker"><span class="muted">No other URLs in the pool.</span></div>`;
  }
  const optionLine = (row) => {
    const selected = pickValue === row.url ? " selected" : "";
    const disabled = row.healthy ? "" : " disabled";
    const kind = row.vpn
      ? "VPN"
      : row.cloudflare_proxied
        ? "CF proxy"
        : row.cloudflare
          ? "CF NS"
          : "origin";
    const state = row.healthy ? "up" : "down";
    const frequent = row.frequent_failure ? " · frequent" : "";
    const prefix = row.vpn ? "VPN · " : "";
    return `<option value="${esc(row.url)}"${selected}${disabled}>${prefix}${esc(hostOf(row.url))} · ${state} · ${kind}${frequent}</option>`;
  };
  const publicRows = choices.filter((row) => !row.vpn);
  const vpnRows = choices.filter((row) => row.vpn);
  const options =
    vpnRows.length && publicRows.length
      ? `<optgroup label="Strong 8K">${publicRows.map(optionLine).join("")}</optgroup><optgroup label="Strong 8K VPN">${vpnRows.map(optionLine).join("")}</optgroup>`
      : choices.map(optionLine).join("");
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

function renderPlaylists(items, { force = false } = {}) {
  // Native <select> lists close if we replace innerHTML. Leave the open
  // Choose URL picker alone until Close / Switch.
  if (!force && pickerIsMounted()) {
    return;
  }
  const playlistCount = document.getElementById("playlist-count");
  if (playlistCount) {
    playlistCount.textContent = items.length ? `${items.length} loaded` : "none";
  }
  if (!items.length) {
    playlistBody.innerHTML = `<tr><td colspan="4">No playlists loaded. Add entries in config/playlists.yaml — they appear within one check cycle.</td></tr>`;
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
      const onVpn = Boolean(item.vpn);
      const title = target
        ? magnum
          ? `Switch to ${hostOf(target)} (Magnum pool only). Fresh MPEG-TS check first. Watch follows this DNS.`
          : onVpn
            ? `Switch to ${hostOf(target)} (Strong 8K VPN lane). Fresh check first.`
            : `Switch to ${hostOf(target)} (public Strong 8K). Auto never picks a VPN host.`
        : magnum
          ? "No healthy Magnum standby right now"
          : onVpn
            ? "No healthy Strong 8K VPN standby. Use Choose URL to pick a public host if the player is off VPN."
            : "No healthy public Strong 8K standby. Use Choose URL to pick a VPN host if the player is on a VPN.";
      const btnLabel = busy ? "Switching…" : "Switch";
      const revertTo = item.revert_dns;
      const canRevert = Boolean(revertTo) && !dryRun;
      const revertTitle = revertTo
        ? `Switch back to ${hostOf(revertTo)} (health-checked first)`
        : "";
      const revertLabel = busy ? "Checking…" : "Switch back";
      const chooseOpen = pickOpen === id;
      const chooseLabel = chooseOpen ? "Close" : "Choose URL";
      const poolPill = item.pool_label
        ? `<span class="pill ${item.pool === "magnum" ? "magnum" : item.vpn ? "vpn-dns" : "strong8k"}">${esc(item.pool_label)}</span>`
        : "";
      return `
        <tr>
          <td>
            <div class="pl-name">${esc(item.name)}</div>
            <div class="pl-meta">${poolPill}<span>ID ${esc(item.playlist_id)}</span><span>${esc(item.username)}</span></div>
          </td>
          <td>
            <div class="pl-dns" title="${esc(item.current_dns)}">${esc(hostLabel(item.current_dns))}</div>
            <div class="pl-ns ${nsCls}">${esc(ns)}</div>
          </td>
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
                title="Pick a URL from this playlist's pool. VPN hosts only work if the player is on a VPN."
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
    renderPlaylists(latest.playlists || [], { force: true });
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
    syncPickerGoButton();
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

function onPoolTabClick(event) {
  const button = event.target.closest("[data-pool-tab]");
  if (!button) {
    return;
  }
  const tabKey = button.getAttribute("data-pool-for");
  const tabId = button.getAttribute("data-pool-tab");
  if (!tabKey || !tabId || !latest) {
    return;
  }
  poolView[tabKey] = tabId;
  if (tabKey === "avail") {
    renderGrouped(availList, availCount, latest.available || [], "No standby URLs in urls.yaml.", true, "avail");
  } else if (tabKey === "live") {
    renderGrouped(liveList, liveCount, latest.live || [], "No live portal URLs yet.", false, "live");
  }
}

if (availList) {
  availList.addEventListener("click", onPoolTabClick);
}
if (liveList) {
  liveList.addEventListener("click", onPoolTabClick);
}

const EVENTS_COLLAPSED = 10;
let eventsShowAll = false;

// Returns escaped HTML. Grouped events get a readable headline; old events keep their message.
function eventTitle(item) {
  const hosts = item.hosts || [];
  if (hosts.length > 1) {
    const where = item.subnet ? ` on ${item.subnet}` : "";
    const role = item.role === "available" ? "standby" : item.role || "";
    if (item.kind === "down") {
      return esc(`${hosts.length} ${role} hosts down${where} — ${reasonLabel(item.reason)}`);
    }
    if (item.kind === "up") {
      return esc(`${hosts.length} ${role} hosts recovered${where}`);
    }
  }
  if (hosts.length === 1 && (item.kind === "down" || item.kind === "up")) {
    const role = item.role === "available" ? "standby" : item.role || "";
    const verb = item.kind === "down" ? `down — ${reasonLabel(item.reason)}` : "recovered";
    return `${role} <strong>${esc(hostLabel(hosts[0]))}</strong> ${esc(verb)}`;
  }
  return esc(item.message);
}

function renderEvents(items) {
  const list = items || [];
  if (eventCount) {
    eventCount.textContent = list.length ? String(list.length) : "";
  }
  if (!list.length) {
    eventList.innerHTML = `<li class="empty-events">No events yet this process. Downs, recoveries, and swaps show up here.</li>`;
    return;
  }
  const open = openDetailKeys(eventList);
  const shown = eventsShowAll ? list : list.slice(0, EVENTS_COLLAPSED);
  const rows = shown
    .map((item) => {
      const kind = esc(item.kind || "info");
      const hosts = item.hosts || [];
      const headline = eventTitle(item);
      const key = `${item.ts}|${item.kind}`;
      const body =
        hosts.length > 1
          ? `<details class="event-fold" data-key="${esc(key)}"${open.has(key) ? " open" : ""}>
               <summary><span class="event-msg">${headline}</span><span class="alert-fold-hint">Hosts</span></summary>
               <div class="alert-hosts">${hostChips(hosts)}</div>
             </details>`
          : `<span class="event-msg">${headline}</span>`;
      return `
        <li class="event-row ${kind}">
          <span class="event-time" title="${esc(new Date(item.ts).toLocaleString())}">
            ${esc(fmtTime(item.ts))}<small>${esc(agoLabel(item.ts))}</small>
          </span>
          <span class="event-kind ${kind}">${kind}</span>
          ${body}
        </li>
      `;
    })
    .join("");
  const more =
    list.length > EVENTS_COLLAPSED
      ? `<li class="event-more"><button type="button" class="sort-btn" data-events-toggle>${
          eventsShowAll ? "Show fewer" : `Show all ${list.length}`
        }</button></li>`
      : "";
  eventList.innerHTML = rows + more;
}

eventList.addEventListener("click", (event) => {
  if (event.target.closest("[data-events-toggle]")) {
    eventsShowAll = !eventsShowAll;
    renderEvents(latest?.events || []);
  }
});

function downGroupTitle(group) {
  if (group.likely_block) {
    return `${group.subnet} unreachable from the VPS`;
  }
  const where = group.subnet ? ` on ${group.subnet}` : "";
  return `${reasonLabel(group.reason)}${where}`;
}

function renderDownNow(groups) {
  if (!downNowEl) {
    return;
  }
  const list = groups || [];
  if (!list.length) {
    downNowEl.hidden = true;
    downNowEl.innerHTML = "";
    return;
  }
  const open = openDetailKeys(downNowEl);
  const total = list.reduce((sum, group) => sum + group.count, 0);
  const liveDown = list.some((group) => group.role === "live");
  const rows = list
    .map((group) => {
      const key = `${group.role}|${group.reason}|${group.subnet || ""}`;
      const since = group.since ? `down ${fmtAge(secondsSince(group.since))}` : "";
      const ips = group.ips?.length ? group.ips.join(", ") : "";
      const meta = [group.reason, since, ips].filter(Boolean).map(esc).join(" · ");
      const hint = group.likely_block
        ? `<p class="down-hint">All ${group.count} names on this range time out together — likely a firewall block on the VPS IP, not dead hosts. Check from a home connection.</p>`
        : "";
      return `
        <details class="down-group ${esc(group.role)}" data-key="${esc(key)}"${open.has(key) ? " open" : ""}>
          <summary>
            <span class="down-count">${esc(String(group.count))}</span>
            <span class="down-main">
              <span class="down-title">
                <span class="down-role">${group.role === "live" ? "Live" : "Standby"}</span>
                ${esc(downGroupTitle(group))}
              </span>
              <span class="down-meta">${meta}</span>
            </span>
            <span class="alert-fold-hint">${group.count === 1 ? "Host" : "Hosts"}</span>
          </summary>
          ${hint}
          <div class="alert-hosts">${hostChips(group.hosts)}</div>
        </details>
      `;
    })
    .join("");
  downNowEl.hidden = false;
  downNowEl.classList.toggle("has-live", liveDown);
  downNowEl.innerHTML = `
    <div class="down-now-head">
      <h2><span class="down-dot" aria-hidden="true"></span>Down now</h2>
      <span class="count">${esc(String(total))} host${total === 1 ? "" : "s"} · ${esc(String(list.length))} group${list.length === 1 ? "" : "s"}</span>
    </div>
    ${rows}
  `;
}

// ---------- Signal map: one cell per standby URL, fixed order so colour follows the host ----------

const MATRIX_GROUPS = [
  { title: "Magnum", test: (item) => item.pool === "magnum" },
  { title: "Strong 8K VPN", test: (item) => item.pool !== "magnum" && item.vpn },
  { title: "Cloudflare proxy", test: (item) => item.pool !== "magnum" && !item.vpn && item.cloudflare_proxied },
  {
    title: "Cloudflare NS",
    test: (item) => item.pool !== "magnum" && !item.vpn && item.cloudflare && !item.cloudflare_proxied,
  },
  { title: "Other", test: (item) => item.pool !== "magnum" && !item.vpn && !item.cloudflare },
];
let matrixKey = "";

function cellMarkup(item) {
  const cls = !item.healthy ? "down" : item.frequent_failure ? "frequent" : "up";
  const title = item.healthy ? SIGNAL_TEXT[signalLevel(item)] : `Down · ${reasonLabel(item.fail_reason)}`;
  const host = hostLabel(item.url);
  const body = [host, laneLabel(item), outagesText(item), "Click to jump to its card"].join("\n");
  return `<button type="button" class="cell ${cls}" data-url="${esc(item.url)}" data-tip-title="${esc(title)}" data-tip-body="${esc(body)}" data-tip-key="${cls}" aria-label="${esc(`${host}: ${title}`)}"></button>`;
}

function renderMatrix(items) {
  if (!matrixEl) {
    return;
  }
  // Only rebuild when something changed, so hover + focus survive the 4s poll.
  const key = items
    .map((item) => `${item.url}|${item.healthy}|${item.frequent_failure}|${item.down_events_24h}|${item.fail_reason}`)
    .join(";");
  if (key === matrixKey) {
    return;
  }
  matrixKey = key;
  if (matrixCount) {
    matrixCount.textContent = `${items.length} hosts`;
  }
  if (!items.length) {
    matrixEl.innerHTML = `<div class="empty">No standby URLs in urls.yaml.</div>`;
    return;
  }
  matrixEl.innerHTML = MATRIX_GROUPS.map((group) => {
    const rows = items
      .filter(group.test)
      .sort((a, b) => hostLabel(a.url).localeCompare(hostLabel(b.url)));
    if (!rows.length) {
      return "";
    }
    const up = rows.filter((item) => item.healthy).length;
    return `
      <div class="matrix-group">
        <div class="matrix-label">${esc(group.title)} <span>${up}/${rows.length}</span></div>
        <div class="matrix-cells">${rows.map(cellMarkup).join("")}</div>
      </div>
    `;
  }).join("");
}

if (matrixEl) {
  matrixEl.addEventListener("click", (event) => {
    const cell = event.target.closest("[data-url]");
    if (!cell || !latest) {
      return;
    }
    const url = cell.getAttribute("data-url");
    // The card may be hidden behind a lane tab: show All first.
    if (poolView.avail !== "all") {
      poolView.avail = "all";
    }
    flashUrl = url;
    flashUntil = Date.now() + 1800;
    renderGrouped(availList, availCount, latest.available || [], "No standby URLs in urls.yaml.", true, "avail");
    const target = [...availList.querySelectorAll(".card[data-url]")].find((el) => el.getAttribute("data-url") === url);
    if (target) {
      window.consoleShell?.hideTip();
      target.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  });
}

// ---------- Hero + stat tiles ----------

function renderHero(data, signedIn) {
  if (!heroEl) {
    return;
  }
  const counts = data.counts || {};
  const state = window.consoleShell
    ? window.consoleShell.overallState(signedIn ? counts : { ...counts, live_up: 0, live_total: 0 })
    : { level: "good", short: "", headline: "" };
  heroEl.dataset.level = state.level;
  const tally = document.getElementById("hero-tally");
  if (tally) {
    tally.className = `tally ${state.level}`;
  }
  setText("hero-headline", state.headline);
  const up = counts.available_up ?? 0;
  const total = counts.available_total ?? 0;
  setText(
    "hero-detail",
    signedIn
      ? `Live DNS ${counts.live_up ?? 0}/${counts.live_total ?? 0} healthy · ${up} of ${total} standby hosts responding`
      : `${up} of ${total} standby hosts are responding to checks`
  );
  setText("hero-up", String(up));
  setText("hero-total", String(total));
  const pct = total ? Math.round((up / total) * 100) : 0;
  setText("hero-pct", total ? `${pct}%` : "—");
  const meter = document.getElementById("hero-meter");
  const fill = document.getElementById("hero-meter-fill");
  if (meter && fill) {
    // Meter severity follows its own quantity (standby health), not the overall state.
    meter.className = `meter${pct === 100 ? "" : pct >= 50 ? " warning" : " critical"}`;
    meter.setAttribute("aria-valuemax", String(total));
    meter.setAttribute("aria-valuenow", String(up));
    fill.style.width = `${pct}%`;
  }
  setSideStatus(state.level, state.short);
}

function uniqueByUrl(lists) {
  const seen = new Map();
  for (const item of lists.flat()) {
    if (item?.url && !seen.has(item.url)) {
      seen.set(item.url, item);
    }
  }
  return [...seen.values()];
}

function renderTiles(data, signedIn) {
  const counts = data.counts || {};
  const pool = data.available || [];
  const flapping = pool.filter((item) => item.frequent_failure).length;
  const outages = uniqueByUrl([pool, signedIn ? data.live || [] : []]).reduce(
    (sum, item) => sum + (item.down_events_24h || 0),
    0
  );
  setText("stat-outages", String(outages));
  setText(
    "stat-outages-cap",
    signedIn && flapping ? `${flapping} standby host${flapping === 1 ? "" : "s"} flapping` : "across the standby pool"
  );
  setText("stat-flapping", String(flapping));
  const flapWrap = document.getElementById("stat-flapping-wrap");
  if (flapWrap) {
    flapWrap.classList.toggle("is-warn", flapping > 0);
    flapWrap.hidden = signedIn;
  }
  if (!signedIn) {
    return;
  }
  const liveDown = (counts.live_total ?? 0) - (counts.live_up ?? 0);
  statLive.textContent = `${counts.live_up ?? "—"}/${counts.live_total ?? "—"}`;
  statLive.closest(".stat")?.classList.toggle("is-bad", liveDown > 0);
  setText("stat-live-cap", liveDown > 0 ? `${liveDown} live host${liveDown === 1 ? "" : "s"} down` : "all live hosts on air");
  const playlists = data.playlists || [];
  statPlaylists.textContent = String(counts.playlists ?? playlists.length);
  const manual = playlists.filter((item) => item.failover === false).length;
  setText("stat-playlists-cap", manual ? `${manual} manual only · rest auto failover` : "all on auto failover");
  if (statWatch) {
    const online = counts.watch_online ?? (data.watch?.online ?? 0);
    const playing = counts.watch_playing ?? (data.watch?.playing ?? 0);
    const slots = data.watch?.slots || {};
    statWatch.textContent = `${playing} playing`;
    setText(
      "stat-watch-cap",
      `${online} online${slots.max != null ? ` · ${slots.used ?? 0}/${slots.max} streams in use` : ""}`
    );
  }
}

// 14-day outage trend for the Outages tile, from /api/history (refreshed once a minute).
let dailyLoadedAt = 0;

async function loadDailyTrend() {
  const holder = document.getElementById("stat-outages-spark");
  if (!holder || Date.now() - dailyLoadedAt < 60000) {
    return;
  }
  dailyLoadedAt = Date.now();
  try {
    const response = await fetch("/api/history", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    const days = data.window_days || 90;
    const totals = new Array(days).fill(0);
    for (const row of data.urls || []) {
      (row.by_day || []).forEach((n, i) => {
        totals[i] += Number(n) || 0;
      });
    }
    const last = totals.slice(-14);
    const max = Math.max(1, ...last);
    const today = new Date();
    const bars = last
      .map((n, i) => {
        const daysAgo = last.length - 1 - i;
        const day = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - daysAgo));
        const label = daysAgo === 0 ? "Today (UTC)" : day.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
        const h = n ? Math.max(3, Math.round((n / max) * 30)) : 2;
        const x = i * 8;
        return `<g data-tip-title="${n} outage${n === 1 ? "" : "s"}" data-tip-body="${esc(label)}"><rect class="hit" x="${x}" y="0" width="8" height="32"></rect><rect class="bar${daysAgo === 0 ? " now" : ""}" x="${x + 1}" y="${32 - h}" width="6" height="${h + 2}" rx="1.5"></rect></g>`;
      })
      .join("");
    holder.innerHTML = `<svg class="spark-mini" width="112" height="32" viewBox="0 0 112 32" role="img" aria-label="Outages per day, last 14 days">${bars}</svg>`;
  } catch {
    dailyLoadedAt = 0;
    holder.innerHTML = "";
  }
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

function renderAlertHtml(text) {
  // Down hosts render in the Down now panel (down_groups); alerts are plain notices.
  return `<div class="${alertClass(text)}">${esc(text)}</div>`;
}

function renderAlerts(items, fallbackError) {
  // "All portal URLs are up." is what the hero already says; keep only notices that add something.
  const messages = (items || []).filter((text) => !String(text).toLowerCase().startsWith("all portal urls are up"));
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
  alertsEl.innerHTML = messages.map(renderAlertHtml).join("");
}

function tickCountdown() {
  if (!latest) {
    return;
  }
  const interval = latest.check_interval_seconds;
  const left = secondsUntilNext(latest.last_cycle_at, interval);
  const label = left === null ? "—" : left === 0 ? "now" : `${left}s`;
  nextCheck.textContent = label;
  setText("hero-next", label);
  // Progress bars fill as the next check approaches; snap (no animation) when a cycle restarts.
  const done = left === null || !interval ? 0 : Math.min(100, Math.max(0, ((interval - left) / interval) * 100));
  for (const id of ["hero-progress", "side-progress"]) {
    const bar = document.getElementById(id);
    if (!bar) {
      continue;
    }
    const previous = parseFloat(bar.style.width) || 0;
    bar.style.transition = done < previous ? "none" : "";
    bar.style.width = `${done}%`;
  }
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
    lastCycle.textContent = data.last_cycle_at
      ? new Date(data.last_cycle_at).toLocaleTimeString([], { hour12: false })
      : "--:--:--";
    if (playlistStatWrap) {
      playlistStatWrap.hidden = !signedIn;
    }
    if (liveStatWrap) {
      liveStatWrap.hidden = !signedIn;
    }
    if (watchStatWrap) {
      watchStatWrap.hidden = !signedIn;
    }
    renderHero(data, signedIn);
    renderTiles(data, signedIn);
    loadDailyTrend();
    if (ownerLink) {
      ownerLink.hidden = false;
      ownerLink.classList.toggle("is-here", isOwnerView());
    }
    const monitorNav = document.getElementById("nav-monitor");
    if (monitorNav) {
      monitorNav.classList.toggle("is-here", !owner);
    }
    if (publicLink) {
      publicLink.hidden = true;
    }
    if (watchLink) {
      watchLink.hidden = false;
    }
    if (ownerSubnav) {
      ownerSubnav.hidden = !(owner && signedIn);
    }
    setPageHeading(owner);
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
    renderDownNow(data.down_groups);
    renderMatrix(data.available || []);
    renderGrouped(availList, availCount, data.available || [], "No standby URLs in urls.yaml.", true, "avail");
    if (signedIn) {
      renderGrouped(liveList, liveCount, data.live || [], "No live portal URLs yet.", false, "live");
      renderPlaylists(data.playlists || []);
      renderWatchers(data.watch);
    }
    renderEvents(data.events || []);
  } catch (error) {
    modePill.hidden = true;
    latest = null;
    nextCheck.textContent = "—";
    setSideStatus("critical", "Monitor unreachable");
    if (heroEl) {
      heroEl.dataset.level = "critical";
      setText("hero-headline", "Monitor unreachable");
      setText("hero-detail", `The dashboard cannot reach the monitor (${error.message}). Retrying every 4 seconds.`);
      const tally = document.getElementById("hero-tally");
      if (tally) {
        tally.className = "tally critical";
      }
    }
    renderAlerts([`Dashboard cannot reach the monitor: ${error.message}`]);
  }
}

refresh();
setInterval(refresh, 4000);
setInterval(tickCountdown, 1000);

