/* /watch player: Xtream catalogue + HLS/mpegts.js against same-origin /api/player.
 *
 * Site login cookie, then Live / Movies / Series lists from proxied player_api.
 * Playback: live is MPEG-TS (mpegts.js) on Chrome/Edge/Android. Safari and
 * every iOS browser use native HLS. Live TS: play() in the same click as
 * the channel (Chrome autoplay). Never pause to "fill" — that blocks the
 * later play() and drops the panel socket. Stash + 0.97× if the cushion
 * thins; reconnect only after a real stall. Panel user/pass never appear here.
 */

const loginPanel = document.getElementById("login-panel");
const appPanel = document.getElementById("app-panel");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const slotStat = document.getElementById("slot-stat");
const userStat = document.getElementById("user-stat");
const guideStat = document.getElementById("guide-stat");
const banner = document.getElementById("watch-banner");
const syncPanel = document.getElementById("watch-sync");
const syncLabel = document.getElementById("watch-sync-label");
const syncEta = document.getElementById("watch-sync-eta");
const syncFill = document.getElementById("watch-sync-fill");
const syncDetail = document.getElementById("watch-sync-detail");
const refreshPlaylistBtn = document.getElementById("refresh-playlist-btn");
const refreshEpgBtn = document.getElementById("refresh-epg-btn");
const video = document.getElementById("player");
const nowTitle = document.getElementById("now-title");
const nowEpg = document.getElementById("now-epg");
const nowNext = document.getElementById("now-next");
const nowClock = document.getElementById("now-clock");
const nowProgressWrap = document.getElementById("now-progress-wrap");
const nowProgress = document.getElementById("now-progress");
const categoryList = document.getElementById("category-list");
const itemList = document.getElementById("item-list");
const seriesPanel = document.getElementById("series-panel");
const searchEl = document.getElementById("watch-search");
const searchBtn = document.getElementById("search-btn");
const liveBadge = document.getElementById("live-badge");
const bufferRow = document.getElementById("buffer-row");
const watchSpinner = document.getElementById("watch-spinner");
const termsPanel = document.getElementById("terms-panel");
const termsAgree = document.getElementById("terms-agree");
const termsOk = document.getElementById("terms-ok");

/* mpegts.js default stash is 384KB. Multi-MB stash (old Medium/Large) waits
 * to fill before the first MSE append, so FHD live never shows a frame.
 * Small/Medium/Large only change how much cushion we try to keep after play. */
const BUFFER_PROFILES = {
  small: { target: 3, stash: 256 * 1024 },
  medium: { target: 6, stash: 384 * 1024 },
  large: { target: 10, stash: 512 * 1024 },
};

function playId() {
  // One UUID per tab so two tabs from the same friend consume two panel slots.
  try {
    let id = sessionStorage.getItem("watch_play_id");
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem("watch_play_id", id);
    }
    return id;
  } catch {
    if (!memoryPlayId) {
      memoryPlayId = crypto.randomUUID();
    }
    return memoryPlayId;
  }
}

function canPlayMpegTs() {
  try {
    return Boolean(window.mpegts && window.mpegts.getFeatureList().mseLivePlayback);
  } catch {
    return false;
  }
}

function canPlayNativeHls() {
  return Boolean(video.canPlayType && video.canPlayType("application/vnd.apple.mpegurl"));
}

function preferNativeHls() {
  // Safari, all iOS browsers (Chrome/Firefox/Edge on iPhone are WebKit),
  // and any engine without MPEG-TS MSE: use HLS instead of mpegts.js.
  return !canPlayMpegTs() && canPlayNativeHls();
}

function liveExtensions() {
  if (canPlayMpegTs()) {
    return ["ts"];
  }
  // Safari / iOS native HLS, or hls.js MSE (Firefox, etc.).
  return ["m3u8"];
}

function vodExtensions(preferred) {
  const ext = String(preferred || "mp4").replace(/^\./, "") || "mp4";
  if (preferNativeHls()) {
    return [...new Set(["m3u8", ext, "mp4", "mkv"])];
  }
  return [...new Set([ext, "mp4", "m3u8", "mkv", "ts"])];
}

function meUrl() {
  const params = new URLSearchParams({ play_id: playId() });
  if (playing) {
    const q = playbackQuality();
    if (q.buffer_s) {
      params.set("buffer_s", String(q.buffer_s));
    }
    if (q.stalls) {
      params.set("stalls", String(q.stalls));
    }
    if (q.dropped) {
      params.set("dropped", String(q.dropped));
    }
    if (q.decoded) {
      params.set("decoded", String(q.decoded));
    }
    if (q.width) {
      params.set("width", String(q.width));
    }
    if (q.height) {
      params.set("height", String(q.height));
    }
    stallReports = 0;
  }
  return `/api/watch/me?${params}`;
}

function playbackQuality() {
  const q = video.getVideoPlaybackQuality?.();
  const dropped = q && Number.isFinite(q.droppedVideoFrames) ? q.droppedVideoFrames : 0;
  const decoded = q && Number.isFinite(q.totalVideoFrames) ? q.totalVideoFrames : 0;
  let bufferS = 0;
  try {
    bufferS = Math.round(bufferedAhead() * 10) / 10;
  } catch {
    bufferS = 0;
  }
  return {
    buffer_s: bufferS,
    stalls: stallReports,
    dropped,
    decoded,
    width: video.videoWidth || 0,
    height: video.videoHeight || 0,
  };
}

function nowPlayingBody() {
  const body = { play_id: playId() };
  if (!playing) {
    return body;
  }
  const item = state.playingItem || {};
  body.kind = state.playingKind || "";
  body.stream_id = String(item.stream_id || item.id || "").slice(0, 80);
  const title = String(item.name || item.title || nowTitle?.textContent || "").trim();
  if (title) {
    body.title = title.slice(0, 200);
  }
  const detail = String(item.now_title || nowEpg?.textContent || "").trim();
  if (detail) {
    body.detail = detail.slice(0, 200);
  }
  const q = playbackQuality();
  body.buffer_s = q.buffer_s;
  body.stalls = q.stalls;
  body.dropped = q.dropped;
  body.decoded = q.decoded;
  body.width = q.width;
  body.height = q.height;
  stallReports = 0;
  return body;
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function apiError(data, fallback) {
  if (typeof data?.detail === "string") {
    return data.detail;
  }
  if (Array.isArray(data?.detail) && data.detail.length) {
    return data.detail.map((item) => item.msg || item).join("; ");
  }
  return fallback;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(apiError(data, `HTTP ${response.status}`));
    error.status = response.status;
    if (response.status === 401 && appPanel && !appPanel.hidden) {
      state.playingItem = null;
      state.playingLiveId = "";
      setTermsAgreed(false);
      stopPlayback();
      showLogin();
      showBanner("You were signed out.", "bad");
    }
    throw error;
  }
  return data;
}

const state = {
  user: null,
  configured: false,
  tab: "live",
  categories: [],
  categoryId: "",
  items: [],
  seriesDetail: null,
  playingLiveId: "",
  playingItem: null,
  playingKind: "",
  mediaToken: "",
  wasSyncing: false,
  epgTries: 0,
  searchKind: "all",
  searchHits: { live: [], movies: [], series: [] },
  syncBusy: false,
};

let hls = null;
let tsPlayer = null;
let beatTimer = null;
let liveTimer = null;
let playing = false;
let playGen = 0;
let itemsGen = 0;
let searchGen = 0;
let searchTimer = null;
let liveHold = false;
let liveMpeg = false;
let liveFillAt = 0;
let liveTsUrl = "";
let liveReconnectTimer = null;
let liveStallTimer = null;
let liveReconnectTries = 0;
let lastLiveResume = 0;
let lastMediaTime = 0;
let lastMediaTimeAt = 0;
let vodRuntimeSec = null;
let memoryPlayId = "";
let stallReports = 0;

function bufferKey() {
  const key = localStorage.getItem("watch_buffer") || "medium";
  return BUFFER_PROFILES[key] ? key : "medium";
}

function bufferProfile() {
  return BUFFER_PROFILES[bufferKey()];
}

function paintBufferButtons() {
  if (!bufferRow) {
    return;
  }
  bufferRow.hidden = !canPlayMpegTs();
  const key = bufferKey();
  bufferRow.querySelectorAll("[data-buf]").forEach((button) => {
    button.classList.toggle("is-here", button.getAttribute("data-buf") === key);
  });
}

function bufferedAhead() {
  if (!video.buffered.length) {
    return 0;
  }
  return Math.max(0, video.buffered.end(video.buffered.length - 1) - video.currentTime);
}

function showWatchSpinner(on) {
  if (!watchSpinner) {
    return;
  }
  watchSpinner.hidden = !on;
}

function clearLiveStallTimer() {
  if (liveStallTimer) {
    clearTimeout(liveStallTimer);
    liveStallTimer = null;
  }
}

function stopLiveWatch() {
  liveHold = false;
  liveMpeg = false;
  liveFillAt = 0;
  clearLiveStallTimer();
  showWatchSpinner(false);
  if (liveTimer) {
    clearInterval(liveTimer);
    liveTimer = null;
  }
  try {
    if (video.playbackRate !== 1) {
      video.playbackRate = 1;
    }
  } catch {
    /* ignore */
  }
}

function paintLiveBadge() {
  if (!liveBadge) {
    return;
  }
  if (!playing || !state.playingLiveId) {
    liveBadge.hidden = true;
    return;
  }
  liveBadge.hidden = false;
  if (liveHold) {
    liveBadge.textContent = "BUFFERING";
    liveBadge.classList.add("is-behind");
    return;
  }
  liveBadge.textContent = "LIVE";
  liveBadge.classList.remove("is-behind");
}

function tickLiveFrozen() {
  /* Play-button freeze (paused/ended/EOF) never fires `waiting`, so the 4.5s
   * stall reconnect never runs. If currentTime is stuck ~4s while we still
   * own the channel, re-open the TS socket. Leave a real user pause alone. */
  if (!playing || !state.playingLiveId || !liveMpeg || !liveTsUrl || liveHold) {
    return;
  }
  if (liveReconnectTimer) {
    return;
  }
  const t = video.currentTime;
  const now = performance.now();
  if (Math.abs(t - lastMediaTime) > 0.05) {
    lastMediaTime = t;
    lastMediaTimeAt = now;
    return;
  }
  if (!lastMediaTimeAt) {
    lastMediaTimeAt = now;
    return;
  }
  if (now - lastMediaTimeAt < 4000) {
    return;
  }
  if (video.paused && !video.ended && bufferedAhead() > 1.5) {
    return;
  }
  lastMediaTimeAt = now;
  scheduleLiveReconnect(liveTsUrl, playGen);
}

function tickLivePace() {
  if (!playing || !state.playingLiveId || liveHold) {
    return;
  }
  tickLiveFrozen();
  if (video.paused) {
    return;
  }
  if (lastLiveResume && performance.now() - lastLiveResume > 30000) {
    liveReconnectTries = 0;
  }
  const ahead = bufferedAhead();
  const { target } = bufferProfile();
  const low = Math.min(2.5, Math.max(1.2, target * 0.28));
  const recover = Math.min(target * 0.55, Math.max(low + 1.5, 4));
  if (ahead > 0.2 && ahead < low) {
    if (Math.abs(video.playbackRate - 0.97) > 0.001) {
      video.playbackRate = 0.97;
    }
  } else if (ahead >= recover && video.playbackRate !== 1) {
    video.playbackRate = 1;
  }
}

function tickLiveFill() {
  /* Spinner until the first media, then pace. Never pause the element. */
  if (!playing || !state.playingLiveId) {
    return;
  }
  paintLiveBadge();
  if (liveMpeg && liveHold && tsPlayer) {
    const ahead = bufferedAhead();
    const waited = liveFillAt ? performance.now() - liveFillAt : 0;
    if (ahead >= 0.4 || video.readyState >= 3 || waited >= 4000) {
      liveHold = false;
      lastLiveResume = performance.now();
      if (ahead >= 0.3 || video.readyState >= 3) {
        showWatchSpinner(false);
      }
      if (video.playbackRate !== 1) {
        video.playbackRate = 1;
      }
      paintLiveBadge();
      return;
    }
    if (video.paused) {
      playNow();
    }
    showWatchSpinner(true);
    return;
  }
  tickLivePace();
}

function beginStallRecover() {
  /* Do not pause here: that stops the TS loader and IPTV panels drop the
   * socket. If we are still starved after a few seconds, reconnect. */
  if (!playing || !state.playingLiveId || liveHold) {
    return;
  }
  if (lastLiveResume && performance.now() - lastLiveResume < 2500) {
    return;
  }
  if (!liveMpeg || !liveTsUrl || liveStallTimer || liveReconnectTimer) {
    return;
  }
  liveStallTimer = window.setTimeout(() => {
    liveStallTimer = null;
    if (!playing || !state.playingLiveId || liveHold) {
      return;
    }
    if (bufferedAhead() >= 1.5 && video.readyState >= 3) {
      return;
    }
    scheduleLiveReconnect(liveTsUrl, playGen);
  }, 4500);
}

function scheduleLiveReconnect(url, gen) {
  if (!url || gen !== playGen || liveReconnectTimer) {
    return;
  }
  if (liveReconnectTries >= 6) {
    showBanner("Live stream dropped. Click the channel again.", "bad");
    return;
  }
  liveReconnectTries += 1;
  liveReconnectTimer = window.setTimeout(() => {
    liveReconnectTimer = null;
    if (gen !== playGen || !playing || !state.playingLiveId) {
      return;
    }
    if (tsPlayer) {
      try {
        tsPlayer.pause();
        tsPlayer.unload();
        tsPlayer.detachMediaElement();
        tsPlayer.destroy();
      } catch {
        /* ignore */
      }
      tsPlayer = null;
    }
    attachMpegTs(url, gen, true);
  }, 700);
}

function startLiveWatch() {
  stopLiveWatch();
  liveMpeg = true;
  liveHold = true;
  liveFillAt = performance.now();
  lastMediaTime = 0;
  lastMediaTimeAt = performance.now();
  showWatchSpinner(true);
  paintLiveBadge();
  playNow();
  liveTimer = setInterval(tickLiveFill, 200);
  tickLiveFill();
}

function startLivePaceOnly() {
  stopLiveWatch();
  liveMpeg = false;
  liveHold = false;
  paintLiveBadge();
  liveTimer = setInterval(tickLiveFill, 250);
}

function applyBufferSize() {
  paintBufferButtons();
  // Size is startup stash + first-fill. Changing it mid-stream does not seek.
}

function formatClock() {
  return new Date().toLocaleString(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatTime(ts) {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) {
    return "";
  }
  return new Date(n * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function parseRuntime(value, { seconds } = {}) {
  if (value == null || value === "") {
    return null;
  }
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    if (seconds || value >= 1000) {
      return Math.round(value);
    }
    return Math.round(value * 60);
  }
  const text = String(value).trim();
  if (!text || text === "0" || text === "00:00" || text === "00:00:00") {
    return null;
  }
  if (/^\d+(\.\d+)?$/.test(text)) {
    const n = Number(text);
    if (!Number.isFinite(n) || n <= 0) {
      return null;
    }
    if (seconds || n >= 1000) {
      return Math.round(n);
    }
    return Math.round(n * 60);
  }
  const parts = text.split(":").map((part) => Number(part));
  if (parts.some((part) => !Number.isFinite(part) || part < 0)) {
    return null;
  }
  if (parts.length === 3) {
    return Math.round(parts[0] * 3600 + parts[1] * 60 + parts[2]);
  }
  if (parts.length === 2) {
    return Math.round(parts[0] * 60 + parts[1]);
  }
  return null;
}

function formatRuntime(seconds) {
  const n = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(n / 3600);
  const mins = Math.floor((n % 3600) / 60);
  const secs = n % 60;
  if (hours > 0) {
    return `${hours}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${mins}:${String(secs).padStart(2, "0")}`;
}

function paintVodRuntime() {
  if (!vodRuntimeSec || state.playingLiveId) {
    return;
  }
  const played = Math.max(0, video.currentTime || 0);
  if (nowNext) {
    nowNext.textContent = `${formatRuntime(played)} / ${formatRuntime(vodRuntimeSec)}`;
  }
  if (nowProgressWrap && nowProgress) {
    nowProgressWrap.hidden = false;
    nowProgress.style.width = `${Math.min(100, (played / vodRuntimeSec) * 100)}%`;
  }
}

function setVodRuntime(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n <= 0) {
    return;
  }
  vodRuntimeSec = n;
  paintVodRuntime();
}

function clearVodRuntime() {
  vodRuntimeSec = null;
}

function progressPct(start, stop) {
  const a = Number(start);
  const b = Number(stop);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b <= a) {
    return 0;
  }
  return Math.min(100, Math.max(0, ((Date.now() / 1000 - a) / (b - a)) * 100));
}

function setProgress(start, stop) {
  const pct = progressPct(start, stop);
  if (!nowProgressWrap || !nowProgress) {
    return;
  }
  if (pct <= 0) {
    nowProgressWrap.hidden = true;
    return;
  }
  nowProgressWrap.hidden = false;
  nowProgress.style.width = `${pct}%`;
}

function tickClock() {
  if (nowClock) {
    nowClock.textContent = formatClock();
  }
}

tickClock();
setInterval(tickClock, 15000);

function setPreview(item, extra) {
  const now = extra?.now || item?.now_title || "";
  const next = extra?.next || item?.next_title || "";
  const start = extra?.start || item?.now_start;
  const stop = extra?.stop || item?.now_stop;
  nowTitle.textContent = item?.name || extra?.title || "Select a channel";
  const times = [formatTime(start), formatTime(stop)].filter(Boolean).join(" – ");
  nowEpg.textContent = [now, times].filter(Boolean).join(" · ") || extra?.fallback || "";
  nowNext.textContent = next ? `Next: ${next}` : "";
  setProgress(start, stop);
}

function showBanner(text, kind) {
  if (!text) {
    banner.hidden = true;
    banner.textContent = "";
    banner.className = "watch-banner";
    return;
  }
  banner.hidden = false;
  banner.textContent = text;
  banner.className = `watch-banner ${kind || ""}`;
}

function formatEta(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n <= 0) {
    return "calculating…";
  }
  if (n < 75) {
    return `~${Math.max(10, Math.round(n / 5) * 5)}s left`;
  }
  if (n < 3600) {
    return `~${Math.round(n / 60)} min left`;
  }
  const hours = Math.floor(n / 3600);
  const mins = Math.round((n % 3600) / 60);
  return `~${hours}h ${mins}m left`;
}

function formatElapsed(seconds) {
  const n = Number(seconds);
  if (!Number.isFinite(n) || n < 0) {
    return "";
  }
  if (n < 60) {
    return `${n}s elapsed`;
  }
  return `${Math.floor(n / 60)}m ${String(n % 60).padStart(2, "0")}s elapsed`;
}

function phaseLabel(phase) {
  if (phase === "live") {
    return "Live groups";
  }
  if (phase === "epg") {
    return "EPG";
  }
  if (phase === "movies") {
    return "Movies";
  }
  if (phase === "series") {
    return "Shows";
  }
  return "Guide";
}

function renderSyncPanel(sync) {
  if (!syncPanel) {
    return;
  }
  if (sync?.running) {
    syncPanel.hidden = false;
    syncPanel.className = "watch-sync";
    const done = Number(sync.phase_done) || 0;
    const total = Number(sync.phase_total) || 0;
    const counts = total ? ` ${done}/${total}` : "";
    syncLabel.textContent = `Syncing ${phaseLabel(sync.phase)}${counts}`;
    const etaBits = [formatElapsed(sync.elapsed_seconds), formatEta(sync.eta_seconds)].filter(Boolean);
    syncEta.textContent = etaBits.join(" · ");
    const pct = Math.max(2, Math.min(100, Number(sync.percent) || 0));
    if (syncFill) {
      syncFill.style.width = `${pct}%`;
    }
    const inflight = Array.isArray(sync.inflight) ? sync.inflight.filter(Boolean) : [];
    if (sync.phase === "epg") {
      syncDetail.textContent = sync.progress || "Downloading XMLTV from the panel…";
    } else {
      const current = inflight.length ? inflight.join(" · ") : sync.phase_item || sync.progress || "";
      syncDetail.textContent = current
        ? `Now: ${current}`
        : "Working… programme titles appear when EPG finishes.";
    }
    return;
  }
  if (sync?.last_error && !(Number(sync.epg_channels) > 0)) {
    syncPanel.hidden = false;
    syncPanel.className = "watch-sync is-bad";
    syncLabel.textContent = "Guide sync issue";
    syncEta.textContent = "";
    if (syncFill) {
      syncFill.style.width = "100%";
    }
    syncDetail.textContent = sync.last_error;
    return;
  }
  syncPanel.hidden = true;
}

function setRefreshEnabled(enabled) {
  const on = !!enabled;
  if (refreshPlaylistBtn) {
    refreshPlaylistBtn.disabled = !on;
  }
  if (refreshEpgBtn) {
    refreshEpgBtn.disabled = !on;
  }
}

function setGuide(sync) {
  renderSyncPanel(sync);
  const canRefresh = state.configured && !state.syncBusy && !sync?.running;
  setRefreshEnabled(canRefresh);
  if (!guideStat) {
    return;
  }
  if (!sync) {
    guideStat.textContent = "—";
    return;
  }
  if (sync.running) {
    const eta = formatEta(sync.eta_seconds);
    const counts =
      sync.phase_total != null && Number(sync.phase_total) > 0
        ? `${sync.phase_done || 0}/${sync.phase_total}`
        : "";
    guideStat.textContent = [counts || "syncing", eta !== "calculating…" ? eta : ""].filter(Boolean).join(" · ");
    return;
  }
  if (!sync.ready) {
    guideStat.textContent = "not ready";
    return;
  }
  const age = Number(sync.age_seconds);
  let extra;
  if (!Number.isFinite(age)) {
    extra = `${sync.streams || 0} ch`;
  } else if (age < 120) {
    extra = "just now";
  } else if (age < 3600) {
    extra = `${Math.floor(age / 60)}m ago`;
  } else {
    extra = `${Math.floor(age / 3600)}h ago`;
  }
  const epg = Number(sync.epg_channels);
  const epgBit = Number.isFinite(epg) && epg > 0 ? ` · ${epg} EPG` : "";
  guideStat.textContent = `${extra}${epgBit}`;
}

let guideTimer = null;
let guidePollMs = 0;

async function tickGuide() {
  try {
    const me = await api(meUrl());
    if (me.media_token) {
      state.mediaToken = me.media_token;
    }
    setSlots(me.slots);
    const running = !!me.sync?.running;
    if (running) {
      state.wasSyncing = true;
    }
    setGuide(me.sync);
    if (state.wasSyncing && me.sync?.ready && !running) {
      state.wasSyncing = false;
      showBanner("");
      await loadCategories();
      if (state.categoryId) {
        await loadItems();
      }
    }
    const want = running ? 2000 : 8000;
    if (want !== guidePollMs) {
      startGuidePoll(want);
    }
  } catch {
    /* ignore */
  }
}

function startGuidePoll(ms) {
  const interval = ms || 2000;
  if (guideTimer && guidePollMs === interval) {
    return;
  }
  if (guideTimer) {
    clearInterval(guideTimer);
  }
  guidePollMs = interval;
  guideTimer = setInterval(tickGuide, interval);
}

function setSlots(slots) {
  if (!slots) {
    slotStat.textContent = "—";
    return;
  }
  slotStat.textContent = `${slots.used}/${slots.max}`;
}

function showLogin() {
  if (termsPanel) {
    termsPanel.hidden = true;
  }
  loginPanel.hidden = false;
  appPanel.hidden = true;
}

function showApp() {
  if (termsPanel) {
    termsPanel.hidden = true;
  }
  loginPanel.hidden = true;
  appPanel.hidden = false;
}

function termsAgreed() {
  try {
    return sessionStorage.getItem("watch_terms_ok") === "1";
  } catch {
    return false;
  }
}

function setTermsAgreed(ok) {
  try {
    if (ok) {
      sessionStorage.setItem("watch_terms_ok", "1");
    } else {
      sessionStorage.removeItem("watch_terms_ok");
    }
  } catch {
    /* ignore */
  }
}

function requireTerms() {
  /* Every login (and each new tab) must tick the box before the player unlocks. */
  if (termsAgreed()) {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    if (!termsPanel || !termsAgree || !termsOk) {
      resolve();
      return;
    }
    loginPanel.hidden = true;
    appPanel.hidden = true;
    termsPanel.hidden = false;
    termsAgree.checked = false;
    termsOk.disabled = true;
    const finish = () => {
      termsOk.removeEventListener("click", onOk);
      termsAgree.removeEventListener("change", onTick);
      setTermsAgreed(true);
      termsPanel.hidden = true;
      resolve();
    };
    const onTick = () => {
      termsOk.disabled = !termsAgree.checked;
    };
    const onOk = () => {
      if (!termsAgree.checked) {
        return;
      }
      finish();
    };
    termsAgree.addEventListener("change", onTick);
    termsOk.addEventListener("click", onOk);
  });
}

function destroyPlayers() {
  if (hls) {
    hls.destroy();
    hls = null;
  }
  if (tsPlayer) {
    try {
      tsPlayer.pause();
      tsPlayer.unload();
      tsPlayer.detachMediaElement();
      tsPlayer.destroy();
    } catch {
      /* ignore */
    }
    tsPlayer = null;
  }
  video.pause();
  video.removeAttribute("src");
  video.load();
}

function stopPlayback() {
  playing = false;
  liveTsUrl = "";
  liveReconnectTries = 0;
  if (liveReconnectTimer) {
    clearTimeout(liveReconnectTimer);
    liveReconnectTimer = null;
  }
  stopLiveWatch();
  showWatchSpinner(false);
  if (beatTimer) {
    clearInterval(beatTimer);
    beatTimer = null;
  }
  if (liveBadge) {
    liveBadge.hidden = true;
  }
  destroyPlayers();
}

async function releaseSlot() {
  try {
    const data = await api("/api/player/slot/release", {
      method: "POST",
      body: JSON.stringify({ play_id: playId() }),
    });
    setSlots(data.slots);
  } catch {
    /* ignore */
  }
}

async function heartbeat() {
  const data = await api("/api/player/slot/heartbeat", {
    method: "POST",
    body: JSON.stringify(nowPlayingBody()),
  });
  setSlots(data.slots);
}

function startHeartbeat() {
  if (beatTimer) {
    clearInterval(beatTimer);
  }
  beatTimer = setInterval(() => {
    heartbeat().catch((error) => {
      showBanner(error.message, "bad");
    });
  }, 20000);
}

function mediaUrl(kind, streamId, ext) {
  const params = new URLSearchParams({ sid: playId() });
  if (state.mediaToken) {
    params.set("k", state.mediaToken);
  }
  return `/api/player/media/${kind}/${encodeURIComponent(streamId)}.${ext}?${params}`;
}

function attachHls(url) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => done(false, new Error("HLS timeout")), 12000);
    const done = (ok, value) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      if (ok) {
        resolve(value);
      } else {
        reject(value);
      }
    };
    if (!window.Hls || !window.Hls.isSupported()) {
      if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = url;
        done(true, "native");
        return;
      }
      done(false, new Error("HLS is not supported in this browser."));
      return;
    }
    hls = new window.Hls({
      xhrSetup(xhr) {
        xhr.withCredentials = true;
      },
      liveSyncDurationCount: 5,
      liveMaxLatencyDurationCount: 12,
    });
    const onError = (_event, info) => {
      if (info?.fatal) {
        hls.off(window.Hls.Events.ERROR, onError);
        done(false, new Error("HLS failed"));
      }
    };
    hls.on(window.Hls.Events.ERROR, onError);
    hls.on(window.Hls.Events.MANIFEST_PARSED, () => done(true, "hls"));
    hls.loadSource(url);
    hls.attachMedia(video);
  });
}

function playNow() {
  video.muted = false;
  video.defaultMuted = false;
  if (!Number.isFinite(video.volume) || video.volume === 0) {
    video.volume = 1;
  }
  if (!liveHold && video.playbackRate !== 1) {
    video.playbackRate = 1;
  }
  const p = video.play();
  if (p && typeof p.catch === "function") {
    p.catch((error) => {
      if (error && error.name === "AbortError") {
        return;
      }
      if (error && error.name === "NotAllowedError") {
        showBanner("Click the video to start playback.", "bad");
      }
    });
  }
}

function attachMpegTs(url, gen, live) {
  if (!canPlayMpegTs()) {
    throw new Error(
      preferNativeHls() || canPlayNativeHls()
        ? "MPEG-TS is not available here; use HLS instead."
        : "This browser cannot play MPEG-TS. Safari and iPhone need HLS; Chrome/Edge on desktop or Android can play the live TS stream."
    );
  }
  const buf = bufferProfile();
  liveTsUrl = url;
  tsPlayer = window.mpegts.createPlayer(
    {
      type: "mpegts",
      isLive: Boolean(live),
      hasAudio: true,
      hasVideo: true,
      url,
      withCredentials: true,
    },
    {
      enableWorker: false,
      enableStashBuffer: true,
      stashInitialSize: live ? Math.min(buf.stash, 512 * 1024) : buf.stash,
      isLive: Boolean(live),
      liveBufferLatencyChasing: false,
      liveSync: false,
      autoCleanupSourceBuffer: true,
      autoCleanupMaxBackwardDuration: live ? 40 : 120,
      autoCleanupMinBackwardDuration: live ? 10 : 15,
      lazyLoad: false,
      deferLoadAfterSourceOpen: false,
      accurateSeek: false,
      fixAudioTimestampGap: !live,
    }
  );
  if (window.mpegts.Events) {
    tsPlayer.on(window.mpegts.Events.ERROR, (errorType, detail) => {
      if (gen !== playGen) {
        return;
      }
      const kind = String(errorType || "");
      const raw = detail?.msg || detail?.code || kind || "Stream error";
      const msg = String(raw);
      if (
        live &&
        (kind === "NetworkError" ||
          kind === "MediaError" ||
          /network|http|status|eof|unrecoverable|mediaerror|loader/i.test(`${kind} ${msg}`))
      ) {
        scheduleLiveReconnect(url, gen);
        return;
      }
      if (/network|http|status|eof|unrecoverable/i.test(msg)) {
        showBanner("Could not play this channel. If the portal is blocked, failover will pick a new DNS shortly.", "bad");
      } else {
        showBanner(msg, "bad");
      }
    });
    if (live && window.mpegts.Events.LOADING_COMPLETE) {
      tsPlayer.on(window.mpegts.Events.LOADING_COMPLETE, () => {
        if (gen !== playGen) {
          return;
        }
        scheduleLiveReconnect(url, gen);
      });
    }
  }
  tsPlayer.attachMediaElement(video);
  tsPlayer.load();
  if (live) {
    startLiveWatch();
  } else {
    playNow();
  }
}

async function playSources(kind, streamId, extensions, gen) {
  // Start the player in this turn (keep the click's autoplay gesture). Heartbeat is not on the critical path.
  const keepItem = state.playingItem;
  const keepLive = state.playingLiveId;
  const keepKind = state.playingKind;
  stopPlayback();
  state.playingItem = keepItem;
  state.playingLiveId = keepLive;
  state.playingKind = keepKind;
  if (gen != null && gen !== playGen) {
    return;
  }
  playing = true;
  startHeartbeat();
  heartbeat().catch((error) => {
    if (gen != null && gen !== playGen) {
      return;
    }
    showBanner(error.message, "bad");
  });
  let lastError = null;
  for (const ext of extensions) {
    if (gen != null && gen !== playGen) {
      return;
    }
    const url = mediaUrl(kind, streamId, ext);
    try {
      if (ext === "m3u8") {
        // iOS AVPlayer: play() must stay in the tap turn; awaiting hls.js loses the gesture.
        if (canPlayNativeHls() && !(window.Hls && window.Hls.isSupported())) {
          video.src = url;
          playNow();
          if (kind === "live") {
            startLivePaceOnly();
          }
        } else {
          await attachHls(url);
          if (gen != null && gen !== playGen) {
            return;
          }
          playNow();
          if (kind === "live") {
            startLivePaceOnly();
          }
        }
      } else if (ext === "ts") {
        attachMpegTs(url, gen, kind === "live");
        if (kind === "live") {
          return;
        }
        await video.play().catch((error) => {
          if (error && error.name === "AbortError") {
            return;
          }
          throw error;
        });
      } else {
        video.src = url;
        video.muted = false;
        video.defaultMuted = false;
        video.volume = 1;
        if (kind !== "live") {
          showWatchSpinner(true);
        }
        try {
          playNow();
          if (kind !== "live") {
            await video.play().catch((error) => {
              if (error && error.name === "AbortError") {
                return;
              }
              throw error;
            });
          }
        } finally {
          if (kind !== "live") {
            showWatchSpinner(false);
          }
        }
      }
      return;
    } catch (error) {
      lastError = error;
      destroyPlayers();
    }
  }
  if (gen != null && gen !== playGen) {
    return;
  }
  playing = false;
  if (beatTimer) {
    clearInterval(beatTimer);
    beatTimer = null;
  }
  await releaseSlot();
  throw lastError || new Error("Playback failed.");
}

function playLive(item) {
  const gen = ++playGen;
  liveReconnectTries = 0;
  clearVodRuntime();
  state.playingLiveId = String(item.stream_id);
  state.playingKind = "live";
  state.playingItem = item;
  setPreview(item, { fallback: "Starting…" });
  showBanner("");
  try {
    playSources("live", String(item.stream_id), liveExtensions(), gen).catch((error) => {
      if (gen !== playGen) {
        return;
      }
      showBanner(error.message, "bad");
    });
  } catch (error) {
    if (gen !== playGen) {
      return;
    }
    showBanner(error.message, "bad");
    return;
  }
  api(`/api/player/live/epg?stream_id=${encodeURIComponent(item.stream_id)}`)
    .then((data) => {
      if (gen !== playGen) {
        return;
      }
      const rows = data.epg || [];
      const current = rows[0] || {};
      const upcoming = rows[1] || {};
      const nowTitleText = current.title || item.now_title || "";
      const nextTitleText = upcoming.title || item.next_title || "";
      const start = current.start_timestamp || current.start || item.now_start;
      const stop = current.stop_timestamp || current.end || item.now_stop;
      setPreview(item, {
        now: nowTitleText,
        next: nextTitleText,
        start,
        stop,
        fallback: "No programme info",
      });
      const row = state.items.find((entry) => String(entry.stream_id) === String(item.stream_id));
      if (row && nowTitleText) {
        row.now_title = nowTitleText;
        row.next_title = nextTitleText;
        if (start) {
          row.now_start = start;
        }
        if (stop) {
          row.now_stop = stop;
        }
        renderItems();
      }
    })
    .catch(() => {
      /* keep now/next from the channel list */
    });
}

async function playVod(item) {
  const gen = ++playGen;
  state.playingLiveId = "";
  state.playingKind = "movie";
  state.playingItem = item;
  const ext = String(item.container_extension || "mp4").replace(/^\./, "");
  nowTitle.textContent = item.name || `Title ${item.stream_id}`;
  nowEpg.textContent = item.plot || "";
  setProgress(0, 0);
  setVodRuntime(parseRuntime(item.duration_secs, { seconds: true }) || parseRuntime(item.duration));
  if (!vodRuntimeSec && nowNext) {
    nowNext.textContent = "Runtime…";
  }
  showBanner("");
  api(`/api/player/vod/info?vod_id=${encodeURIComponent(item.stream_id)}`)
    .then((data) => {
      if (gen !== playGen) {
        return;
      }
      const info = data.info || {};
      if (!item.plot && info.plot) {
        nowEpg.textContent = info.plot;
      }
      setVodRuntime(parseRuntime(info.duration_secs, { seconds: true }) || parseRuntime(info.duration));
    })
    .catch(() => {});
  const order = vodExtensions(ext);
  try {
    await playSources("movie", String(item.stream_id), order, gen);
  } catch (error) {
    if (gen !== playGen) {
      return;
    }
    showBanner(error.message, "bad");
  }
}

async function playEpisode(episode, seriesName) {
  const gen = ++playGen;
  state.playingLiveId = "";
  state.playingKind = "series";
  state.playingItem = {
    ...episode,
    stream_id: episode.id,
    name: `${seriesName || "Series"} · ${episode.title || `Episode ${episode.episode_num}`}`,
  };
  const ext = String(episode.container_extension || "mp4").replace(/^\./, "");
  nowTitle.textContent = `${seriesName || "Series"} · ${episode.title || `Episode ${episode.episode_num}`}`;
  nowEpg.textContent = episode.plot || episode.info?.plot || "";
  setProgress(0, 0);
  setVodRuntime(
    parseRuntime(episode.duration_secs || episode.info?.duration_secs, { seconds: true }) ||
      parseRuntime(episode.duration || episode.info?.duration)
  );
  if (!vodRuntimeSec && nowNext) {
    nowNext.textContent = "Runtime…";
  }
  showBanner("");
  const order = vodExtensions(ext);
  try {
    await playSources("series", String(episode.id), order, gen);
  } catch (error) {
    if (gen !== playGen) {
      return;
    }
    showBanner(error.message, "bad");
  }
}

function visibleItems() {
  const query = (searchEl.value || "").trim().toLowerCase();
  let rows = state.items;
  if (query && state.tab !== "search") {
    const tokens = query.split(/\s+/).filter(Boolean);
    rows = rows.filter((item) => {
      const hay = `${item.name || ""} ${item.now_title || ""} ${item.next_title || ""} ${item.plot || ""} ${item.genre || ""}`.toLowerCase();
      const compact = hay.replace(/[^a-z0-9]+/g, "");
      const joined = query.replace(/\s+/g, "");
      if (joined.length >= 2 && compact.includes(joined)) {
        return true;
      }
      return tokens.every((token) => hay.includes(token));
    });
  }
  return rows.slice(0, 800);
}

function catMark(name) {
  const words = String(name || "")
    .replace(/[^a-zA-Z0-9| ]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!words.length) {
    return "·";
  }
  if (words.length === 1) {
    return words[0].slice(0, 2);
  }
  return `${words[0][0] || ""}${words[1][0] || ""}`;
}

function renderCategories() {
  categoryList.innerHTML = state.categories
    .map((cat) => {
      const id = String(cat.category_id ?? "");
      const name = cat.category_name || id;
      const here = id === String(state.categoryId) ? " is-here" : "";
      const count =
        cat.stream_count != null && cat.stream_count !== ""
          ? ` (${esc(cat.stream_count)})`
          : "";
      return `<button type="button" class="watch-cat${here}" data-cat="${esc(id)}"><span class="watch-cat-mark">${esc(catMark(name))}</span><span class="watch-cat-label">${esc(name)}${count}</span></button>`;
    })
    .join("");
}

function renderItems() {
  const rows = visibleItems();
  if (!rows.length) {
    itemList.innerHTML = `<div class="empty-events">${
      state.categoryId ? "Nothing in this group." : "Pick a group to see channels."
    }</div>`;
    return;
  }
  if (state.tab === "live") {
    itemList.innerHTML = rows
      .map((item, index) => {
        const icon = item.stream_icon
          ? `<img src="${esc(item.stream_icon)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
          : `<span></span>`;
        const now = item.now_title || "";
        const epg = now
          ? `<small class="watch-item-epg">${esc(now)}</small>`
          : `<small class="watch-item-epg is-empty">No programme info</small>`;
        const pct = progressPct(item.now_start, item.now_stop);
        const bar = pct > 0 ? `<span class="watch-item-bar"><i style="width:${pct}%"></i></span>` : "";
        const here = String(item.stream_id) === String(state.playingLiveId) ? " is-here" : "";
        const num = item.num || index + 1;
        return `<button type="button" class="watch-item${here}" data-live="${esc(item.stream_id)}"><span class="watch-num">${esc(num)}</span>${icon}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span>${epg}${bar}</span></button>`;
      })
      .join("");
    return;
  }
  if (state.tab === "movies") {
    itemList.innerHTML = rows
      .map((item) => {
        const poster = item.stream_icon
          ? `<img src="${esc(item.stream_icon)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
          : "";
        return `<button type="button" class="watch-item poster" data-vod="${esc(item.stream_id)}">${poster}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span></span></button>`;
      })
      .join("");
    return;
  }
  itemList.innerHTML = rows
    .map((item) => {
      const poster = item.cover
        ? `<img src="${esc(item.cover)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
        : "";
      return `<button type="button" class="watch-item poster" data-series="${esc(item.series_id)}">${poster}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span></span></button>`;
    })
    .join("");
}

function renderSeries(detail, seriesName) {
  if (!detail) {
    seriesPanel.hidden = true;
    seriesPanel.innerHTML = "";
    return;
  }
  const episodes = detail.episodes || {};
  const seasons = Object.keys(episodes).sort((a, b) => Number(a) - Number(b));
  seriesPanel.hidden = false;
  seriesPanel.innerHTML = seasons
    .map((season) => {
      const list = (episodes[season] || [])
        .map((ep) => {
          return `<button type="button" class="watch-item" data-episode="${esc(ep.id)}" data-ext="${esc(ep.container_extension || "")}" data-title="${esc(ep.title || "")}" data-plot="${esc(ep.plot || ep.info?.plot || "")}" data-duration="${esc(ep.duration || ep.info?.duration || "")}" data-duration-secs="${esc(ep.duration_secs || ep.info?.duration_secs || "")}" data-series-name="${esc(seriesName)}">E${esc(ep.episode_num ?? ep.id)} ${esc(ep.title || "")}</button>`;
        })
        .join("");
      return `<div class="watch-season"><h3>Season ${esc(season)}</h3><div class="watch-season-eps">${list}</div></div>`;
    })
    .join("");
}

function searchCounts() {
  return {
    live: state.searchHits.live.length,
    movies: state.searchHits.movies.length,
    series: state.searchHits.series.length,
  };
}

function renderSearchNav() {
  const counts = searchCounts();
  const total = counts.live + counts.movies + counts.series;
  const rows = [
    ["all", "All", total],
    ["live", "TV", counts.live],
    ["movies", "Movies", counts.movies],
    ["series", "Shows", counts.series],
  ];
  categoryList.innerHTML = rows
    .map(([id, label, count]) => {
      const here = state.searchKind === id ? " is-here" : "";
      const extra = state.searchHits.live.length || state.searchHits.movies.length || state.searchHits.series.length
        ? ` (${esc(count)})`
        : "";
      return `<button type="button" class="watch-cat${here}" data-search-kind="${id}"><span class="watch-cat-mark">${esc(label.slice(0, 2))}</span><span class="watch-cat-label">${esc(label)}${extra}</span></button>`;
    })
    .join("");
}

function searchRowLive(item, index) {
  const icon = item.stream_icon
    ? `<img src="${esc(item.stream_icon)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
    : `<span></span>`;
  const now = item.now_title || "";
  const epg = now
    ? `<small class="watch-item-epg">${esc(now)}</small>`
    : `<small class="watch-item-epg">${esc(item.category_name || item.match || "Live")}</small>`;
  const here = String(item.stream_id) === String(state.playingLiveId) ? " is-here" : "";
  const num = item.num || index + 1;
  return `<button type="button" class="watch-item${here}" data-live="${esc(item.stream_id)}"><span class="watch-num">${esc(num)}</span>${icon}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span>${epg}</span></button>`;
}

function searchRowMovie(item) {
  const poster = item.stream_icon
    ? `<img src="${esc(item.stream_icon)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
    : "";
  const meta = item.match || item.category_name || item.genre || "Movie";
  return `<button type="button" class="watch-item poster" data-vod="${esc(item.stream_id)}">${poster}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span><small class="watch-item-epg">${esc(meta)}</small></span></button>`;
}

function searchRowSeries(item) {
  const poster = item.cover
    ? `<img src="${esc(item.cover)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
    : "";
  const meta = item.match || item.category_name || item.genre || "Show";
  return `<button type="button" class="watch-item poster" data-series="${esc(item.series_id)}">${poster}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span><small class="watch-item-epg">${esc(meta)}</small></span></button>`;
}

function renderSearchResults() {
  const q = (searchEl.value || "").trim();
  if (q.length < 2) {
    itemList.innerHTML = `<div class="empty-events">Type at least two letters. Matches live channels, movies, and shows — names, what’s on now, plot, and genre.</div>`;
    renderSearchNav();
    return;
  }
  const kind = state.searchKind;
  const live = kind === "all" || kind === "live" ? state.searchHits.live : [];
  const movies = kind === "all" || kind === "movies" ? state.searchHits.movies : [];
  const series = kind === "all" || kind === "series" ? state.searchHits.series : [];
  if (!live.length && !movies.length && !series.length) {
    itemList.innerHTML = `<div class="empty-events">No matches for “${esc(q)}”.</div>`;
    renderSearchNav();
    return;
  }
  const parts = [];
  if (live.length) {
    parts.push(`<div class="watch-search-group"><strong>TV</strong><span>${esc(live.length)}</span></div>`);
    parts.push(live.map((item, index) => searchRowLive(item, index)).join(""));
  }
  if (movies.length) {
    parts.push(`<div class="watch-search-group"><strong>Movies</strong><span>${esc(movies.length)}</span></div>`);
    parts.push(movies.map((item) => searchRowMovie(item)).join(""));
  }
  if (series.length) {
    parts.push(`<div class="watch-search-group"><strong>Shows</strong><span>${esc(series.length)}</span></div>`);
    parts.push(series.map((item) => searchRowSeries(item)).join(""));
  }
  itemList.innerHTML = parts.join("");
  renderSearchNav();
}

async function runSearch() {
  if (state.tab !== "search") {
    return;
  }
  const q = (searchEl.value || "").trim();
  const gen = ++searchGen;
  seriesPanel.hidden = true;
  if (q.length < 2) {
    state.searchHits = { live: [], movies: [], series: [] };
    renderSearchResults();
    return;
  }
  itemList.innerHTML = `<div class="empty-events">Searching…</div>`;
  try {
    const data = await api(`/api/player/search?q=${encodeURIComponent(q)}`);
    if (gen !== searchGen || state.tab !== "search") {
      return;
    }
    state.searchHits = {
      live: data.live || [],
      movies: data.movies || [],
      series: data.series || [],
    };
    renderSearchResults();
  } catch (error) {
    if (gen !== searchGen) {
      return;
    }
    itemList.innerHTML = `<div class="empty-events">${esc(error.message)}</div>`;
  }
}

function queueSearch() {
  if (searchTimer) {
    clearTimeout(searchTimer);
  }
  searchTimer = setTimeout(() => {
    runSearch().catch(() => {});
  }, 220);
}

function findSearchItem(kind, id) {
  if (kind === "live") {
    return state.searchHits.live.find((row) => String(row.stream_id) === String(id));
  }
  if (kind === "movie") {
    return state.searchHits.movies.find((row) => String(row.stream_id) === String(id));
  }
  return state.searchHits.series.find((row) => String(row.series_id) === String(id));
}

async function loadCategories() {
  searchEl.placeholder = "Filter this group…";
  const kind = state.tab === "movies" ? "vod" : state.tab === "series" ? "series" : "live";
  const path =
    kind === "live"
      ? "/api/player/live/categories"
      : kind === "vod"
        ? "/api/player/vod/categories"
        : "/api/player/series/categories";
  categoryList.innerHTML = `<div class="empty-events">Loading categories…</div>`;
  itemList.innerHTML = `<div class="empty-events">Loading…</div>`;
  const data = await api(path);
  state.categories = data.categories || [];
  state.categoryId = "";
  renderCategories();
  if (!state.categories.length) {
    const me = await api(meUrl()).catch(() => ({}));
    setGuide(me.sync);
    if (me.sync?.running) {
      itemList.innerHTML = `<div class="empty-events">Downloading the full channel guide. This can take a few minutes, then every group is instant.</div>`;
    } else {
      itemList.innerHTML = `<div class="empty-events">No categories from the panel.</div>`;
    }
    return;
  }
  itemList.innerHTML = `<div class="empty-events">Pick a group. Channels and what's on now show in the list; click one for a live preview.</div>`;
}

async function loadItems(opts) {
  seriesPanel.hidden = true;
  const kind = state.tab;
  const refresh = !!opts?.epgRefresh;
  if (!refresh) {
    itemsGen += 1;
    state.epgTries = 0;
  }
  const gen = itemsGen;
  const categoryId = state.categoryId;
  if (kind === "live") {
    const data = await api(
      `/api/player/live/streams?category_id=${encodeURIComponent(categoryId)}`
    );
    if (gen !== itemsGen) {
      return;
    }
    state.items = data.streams || [];
  } else if (kind === "movies") {
    const data = await api(
      `/api/player/vod/streams?category_id=${encodeURIComponent(categoryId)}`
    );
    if (gen !== itemsGen) {
      return;
    }
    state.items = data.streams || [];
  } else {
    const data = await api(
      `/api/player/series/list?category_id=${encodeURIComponent(categoryId)}`
    );
    if (gen !== itemsGen) {
      return;
    }
    state.items = data.series || [];
  }
  renderItems();
  if (kind === "live") {
    const missing = state.items.filter((item) => !item.now_title).length;
    if (missing > 0 && (state.epgTries || 0) < 3) {
      state.epgTries = (state.epgTries || 0) + 1;
      window.setTimeout(() => {
        if (gen === itemsGen && state.tab === "live" && state.categoryId === categoryId) {
          loadItems({ epgRefresh: true }).catch(() => {});
        }
      }, 1800);
    }
  }
}

async function boot() {
  try {
    const me = await api(meUrl());
    if (me.media_token) {
      state.mediaToken = me.media_token;
    }
    setSlots(me.slots);
    if (!me.username) {
      showLogin();
      return;
    }
    await requireTerms();
    state.user = me.username;
    state.configured = me.configured;
    userStat.textContent = me.username;
    setGuide(me.sync);
    showApp();
    video.setAttribute("playsinline", "");
    video.setAttribute("webkit-playsinline", "");
    video.playsInline = true;
    paintBufferButtons();
    if (!me.configured) {
      showBanner(
        "Watch is signed in, but config/player.yaml has no Xtream DNS / username / password yet.",
        "warn"
      );
      return;
    }
    if (me.sync?.running) {
      state.wasSyncing = true;
    }
    startGuidePoll(me.sync?.running ? 2000 : 8000);
    try {
      await loadCategories();
    } catch (error) {
      showBanner(error.message, "bad");
      itemList.innerHTML = `<div class="empty-events">${esc(error.message)}</div>`;
    }
  } catch (error) {
    showLogin();
    loginError.hidden = false;
    loginError.textContent = error.message;
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  try {
    await api("/api/watch/login", {
      method: "POST",
      body: JSON.stringify({
        username: document.getElementById("login-user").value,
        password: document.getElementById("login-pass").value,
      }),
    });
    setTermsAgreed(false);
    await boot();
  } catch (error) {
    loginError.hidden = false;
    loginError.textContent = error.message;
  }
});

async function requestSync(kind) {
  if (state.syncBusy || !state.configured) {
    return;
  }
  state.syncBusy = true;
  setRefreshEnabled(false);
  try {
    await api("/api/player/sync", {
      method: "POST",
      body: JSON.stringify({ kind }),
    });
    state.wasSyncing = true;
    showBanner(kind === "epg" ? "EPG refresh queued…" : "Playlist refresh queued…");
    startGuidePoll(2000);
  } catch (error) {
    showBanner(error.message, "bad");
  } finally {
    state.syncBusy = false;
    await tickGuide();
  }
}

document.getElementById("logout-btn").addEventListener("click", async () => {
  state.playingItem = null;
  state.playingLiveId = "";
  stopPlayback();
  try {
    await api("/api/watch/logout", {
      method: "POST",
      body: JSON.stringify({ play_id: playId() }),
    });
  } catch {
    /* ignore */
  }
  setTermsAgreed(false);
  showLogin();
});

if (refreshPlaylistBtn) {
  refreshPlaylistBtn.addEventListener("click", () => requestSync("playlist"));
}
if (refreshEpgBtn) {
  refreshEpgBtn.addEventListener("click", () => requestSync("epg"));
}

document.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", async () => {
    document.querySelectorAll("[data-tab]").forEach((item) => {
      item.classList.toggle("is-here", item === button);
    });
    state.tab = button.getAttribute("data-tab") || "live";
    showBanner("");
    seriesPanel.hidden = true;
    if (state.tab === "search") {
      searchEl.placeholder = "Search live, movies and shows…";
      renderSearchNav();
      renderSearchResults();
      searchEl.focus();
      if ((searchEl.value || "").trim().length >= 2) {
        await runSearch();
      }
      return;
    }
    try {
      await loadCategories();
    } catch (error) {
      showBanner(error.message, "bad");
    }
  });
});

categoryList.addEventListener("click", async (event) => {
  const kindBtn = event.target.closest("[data-search-kind]");
  if (kindBtn) {
    state.searchKind = kindBtn.getAttribute("data-search-kind") || "all";
    renderSearchResults();
    return;
  }
  const button = event.target.closest("[data-cat]");
  if (!button) {
    return;
  }
  state.categoryId = button.getAttribute("data-cat") || "";
  renderCategories();
  try {
    await loadItems();
  } catch (error) {
    showBanner(error.message, "bad");
  }
});

itemList.addEventListener("click", async (event) => {
  const live = event.target.closest("[data-live]");
  if (live) {
    const id = live.getAttribute("data-live");
    const item = state.items.find((row) => String(row.stream_id) === String(id)) || findSearchItem("live", id);
    if (item) {
      localStorage.setItem("watch_last_live", String(id));
      state.playingLiveId = String(id);
      itemList.querySelectorAll(".watch-item[data-live]").forEach((el) => {
        el.classList.toggle("is-here", el.getAttribute("data-live") === String(id));
      });
      playLive(item);
    }
    return;
  }
  const vod = event.target.closest("[data-vod]");
  if (vod) {
    const id = vod.getAttribute("data-vod");
    const item = state.items.find((row) => String(row.stream_id) === String(id)) || findSearchItem("movie", id);
    if (item) {
      await playVod(item);
    }
    return;
  }
  const series = event.target.closest("[data-series]");
  if (series) {
    const id = series.getAttribute("data-series");
    const item = state.items.find((row) => String(row.series_id) === String(id)) || findSearchItem("series", id);
    try {
      const detail = await api(`/api/player/series/info?series_id=${encodeURIComponent(id)}`);
      renderSeries(detail, item?.name || "");
    } catch (error) {
      showBanner(error.message, "bad");
    }
  }
});

seriesPanel.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-episode]");
  if (!button) {
    return;
  }
  await playEpisode(
    {
      id: button.getAttribute("data-episode"),
      title: button.getAttribute("data-title"),
      container_extension: button.getAttribute("data-ext"),
      plot: button.getAttribute("data-plot"),
      duration: button.getAttribute("data-duration"),
      duration_secs: button.getAttribute("data-duration-secs"),
    },
    button.getAttribute("data-series-name")
  );
});

searchEl.addEventListener("input", () => {
  if (state.tab === "search") {
    queueSearch();
    return;
  }
  renderItems();
});

searchEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && state.tab === "search") {
    event.preventDefault();
    if (searchTimer) {
      clearTimeout(searchTimer);
    }
    runSearch().catch(() => {});
  }
});

if (bufferRow) {
  bufferRow.addEventListener("click", (event) => {
    const button = event.target.closest("[data-buf]");
    if (!button) {
      return;
    }
    const key = button.getAttribute("data-buf");
    if (!BUFFER_PROFILES[key]) {
      return;
    }
    localStorage.setItem("watch_buffer", key);
    applyBufferSize();
  });
}

video.addEventListener("timeupdate", paintVodRuntime);
video.addEventListener("playing", () => {
  clearLiveStallTimer();
  if (liveHold) {
    return;
  }
  showWatchSpinner(false);
  paintLiveBadge();
});
video.addEventListener("pause", paintLiveBadge);
video.addEventListener("ended", () => {
  if (playing && state.playingLiveId && liveMpeg && liveTsUrl) {
    scheduleLiveReconnect(liveTsUrl, playGen);
  }
});
video.addEventListener("waiting", () => {
  if (!playing) {
    return;
  }
  if (liveHold) {
    showWatchSpinner(true);
    paintLiveBadge();
    return;
  }
  stallReports += 1;
  showWatchSpinner(true);
  if (state.playingLiveId) {
    beginStallRecover();
    if (liveBadge && !liveBadge.hidden) {
      liveBadge.textContent = "BUFFERING";
      liveBadge.classList.add("is-behind");
    }
    return;
  }
});
video.addEventListener("stalled", () => {
  if (playing && state.playingLiveId && !liveHold) {
    beginStallRecover();
  }
});

window.addEventListener("pagehide", () => {
  if (playing) {
    navigator.sendBeacon?.(
      "/api/player/slot/release",
      new Blob([JSON.stringify({ play_id: playId() })], { type: "application/json" })
    );
  }
});

boot();
