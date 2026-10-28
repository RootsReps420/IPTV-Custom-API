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
const ownerSubnav = document.getElementById("owner-subnav");
const sideDot = document.getElementById("side-dot");
const sideStatusText = document.getElementById("side-status-text");

// Sidebar status: red if live DNS is down, amber if only standbys are, green otherwise.
function setSideStatus(level, text) {
  if (sideDot) {
    sideDot.className = `dot ${level}`;
  }
  if (sideStatusText) {
    sideStatusText.textContent = text;
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
      ? "Playlists, live DNS, Watch sessions and the standby pool"
      : "Standby pool health and recent events";
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

function card(item) {
  const state = item.healthy ? "up" : "down";
  const reason = item.fail_reason
    ? `<span class="card-reason" title="${esc(item.fail_reason)}${
        item.error_detail ? ` · ${esc(String(item.error_detail).slice(0, 80))}` : ""
      }">${esc(reasonLabel(item.fail_reason))}</span>`
    : "";
  const playlists = item.playlists?.length ? `<span>playlists ${esc(item.playlists.join(", "))}</span>` : "";
  const downFor = item.down_since ? ` · down ${fmtAge(secondsSince(item.down_since))}` : "";
  const checked = item.last_checked ? ` · checked ${agoLabel(item.last_checked)}` : "";
  const check = item.healthy
    ? `check-pass completed: ${item.consecutive_successes || 0}${checked}`
    : `fails ${item.consecutive_failures}${downFor}${checked}`;
  const downs = `Service 'Down' count (24hr): ${item.down_events_24h || 0}`;
  const frequent = item.frequent_failure
    ? `<span class="pill frequent" title="${item.down_events_24h || 0} separate downs in 24h">Frequent failure</span>`
    : "";
  const tsLabel = item.pool === "magnum" ? "mpeg-ts" : "xtream";
  return `
    <article class="card ${state}${item.cloudflare ? " cf" : ""}${item.frequent_failure ? " frequent" : ""}${item.vpn && item.pool !== "magnum" ? " vpn-lane" : ""}">
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
        ${flag(tsLabel, item.stream_ok, item)}
        ${reason}
        ${playlists}
      </div>
      ${ipRow(item.resolved_ips)}
      <div class="check-line">${esc(check)} <span class="sep">|</span> ${esc(downs)}</div>
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

function groupBlock(title, rows, listClass) {
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
      <div class="${listClass}">${ordered.map(card).join("")}</div>
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
  const vpnBlock = groupBlock("Strong 8K VPN", vpn, listClass);
  const magnumBlock = groupBlock("Magnum", magnum, listClass);
  const cfBlocks = CF_GROUPS.map((group) => groupBlock(group.title, buckets[group.id], listClass)).join("");
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
      return `
        <tr>
          <td>${esc(item.name)}${
            item.pool_label
              ? ` <span class="pill ${item.pool === "magnum" ? "magnum" : item.vpn ? "vpn-dns" : "strong8k"}">${esc(item.pool_label)}</span>`
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
    renderEvents(window.latest?.events || []);
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
  alertsEl.innerHTML = messages.map(renderAlertHtml).join("");
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
    statAvail.parentElement.classList.toggle("is-bad", (counts.available_up ?? 0) < (counts.available_total ?? 0));
    statLive.parentElement.classList.toggle("is-bad", (counts.live_up ?? 0) < (counts.live_total ?? 0));
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
    const liveDown = (counts.live_up ?? 0) < (counts.live_total ?? 0);
    const standbyDown = (counts.available_total ?? 0) - (counts.available_up ?? 0);
    if (liveDown) {
      setSideStatus("bad", "Live DNS down");
    } else if (standbyDown > 0) {
      setSideStatus("warn", `${standbyDown} standby down`);
    } else {
      setSideStatus("ok", "All systems up");
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
    renderDownNow(data.down_groups);
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
    setSideStatus("bad", "Monitor unreachable");
    renderAlerts([`Dashboard cannot reach the monitor: ${error.message}`]);
  }
}

refresh();
setInterval(refresh, 4000);
setInterval(tickCountdown, 1000);

