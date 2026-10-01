/* /watch player: Xtream catalogue + HLS/mpegts.js against same-origin /api/player.
 *
 * Site login cookie, then Live / Movies / Series lists from proxied player_api.
 * Playback: live is MPEG-TS (mpegts.js) on Chrome/Edge/Android. Safari and
 * every iOS browser use native HLS. Live TS: play() in the same click as
 * the channel (Chrome autoplay). Never pause to "fill" — that blocks the
 * later play() and drops the panel socket. Keep rate at 1×. Reconnect only
 * when the HTTP pipe is dead (error / EOF), not on ordinary buffer waits.
 * Panel user/pass never appear here.
 */

const loginPanel = document.getElementById("login-panel");
const appPanel = document.getElementById("app-panel");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const passwordPanel = document.getElementById("password-panel");
const passwordForm = document.getElementById("password-form");
const passwordError = document.getElementById("password-error");
const pwLogoutBtn = document.getElementById("pw-logout-btn");
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
const videoWrap = document.getElementById("watch-video-wrap");
const vodChrome = document.getElementById("vod-chrome");
const vodHit = document.getElementById("vod-hit");
const vodSeekRange = document.getElementById("vod-seek-range");
const vodSeekTime = document.getElementById("vod-seek-time");
const vodSeekBack = document.getElementById("vod-seek-back");
const vodSeekFwd = document.getElementById("vod-seek-fwd");
const vodPlayBtn = document.getElementById("vod-play");
const vodMuteBtn = document.getElementById("vod-mute");
const vodVol = document.getElementById("vod-vol");
const vodFsBtn = document.getElementById("vod-fs");
const vodRestartBtn = document.getElementById("vod-restart");
const vodSkipIntro = document.getElementById("vod-skip-intro");
const vodRateBtn = document.getElementById("vod-rate");
const vodEpPrev = document.getElementById("vod-ep-prev");
const vodEpNext = document.getElementById("vod-ep-next");
const vodUpNext = document.getElementById("vod-upnext");
const vodUpNextTitle = document.getElementById("vod-upnext-title");
const vodUpNextSecs = document.getElementById("vod-upnext-secs");
const vodUpNextPlay = document.getElementById("vod-upnext-play");
const vodUpNextCancel = document.getElementById("vod-upnext-cancel");
const categoryList = document.getElementById("category-list");
const itemList = document.getElementById("item-list");
const watchStage = document.getElementById("watch-stage");
const seriesPanel = document.getElementById("series-panel");
const searchEl = document.getElementById("watch-search");
const searchBtn = document.getElementById("search-btn");
const liveBadge = document.getElementById("live-badge");
const streamStat = document.getElementById("stream-stat");
const bufferRow = document.getElementById("buffer-row");
const watchSpinner = document.getElementById("watch-spinner");
const termsPanel = document.getElementById("terms-panel");
const termsAgree = document.getElementById("terms-agree");
const termsOk = document.getElementById("terms-ok");
const vodDetail = document.getElementById("vod-detail");
const vodDetailClose = document.getElementById("vod-detail-close");
const vodDetailBackdrop = document.getElementById("vod-detail-backdrop");
const vodDetailMeta = document.getElementById("vod-detail-meta");
const vodDetailTitle = document.getElementById("vod-detail-title");
const vodDetailPlot = document.getElementById("vod-detail-plot");
const vodDetailPlay = document.getElementById("vod-detail-play");
const vodDetailPeople = document.getElementById("vod-detail-people");
const vodDetailEps = document.getElementById("vod-detail-episodes");
const vodPlayerClose = document.getElementById("vod-player-close");

/* Live stash is capped at 512KB so FHD still shows a frame quickly.
 * Multi-MB stash used to wait to fill before the first MSE append.
 * target is leftover profile metadata; live no longer eases playbackRate. */
const BUFFER_PROFILES = {
  small: { target: 3, stash: 256 * 1024 },
  medium: { target: 6, stash: 512 * 1024 },
  large: { target: 10, stash: 512 * 1024 },
};
const UP_NEXT_SECS = 8;
const VOD_VIEW_ALL_CAP = 400;
const VOD_RATES = [1, 1.25, 1.5, 2, 0.75];
const SKIP_INTRO_SEC = 90;

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

function isAppleHlsClient() {
  const ua = navigator.userAgent || "";
  if (/iPhone|iPad|iPod/i.test(ua)) {
    return true;
  }
  if (navigator.platform === "MacIntel" && Number(navigator.maxTouchPoints) > 1) {
    return true;
  }
  return /Safari/i.test(ua) && !/Chrome|Chromium|CriOS|FxiOS|Edg|OPR|Android/i.test(ua);
}

function canPlayHevc() {
  try {
    return Boolean(
      video.canPlayType('video/mp4; codecs="hvc1.1.6.L93.B0"') ||
        video.canPlayType('video/mp4; codecs="hev1.1.6.L93.B0"')
    );
  } catch {
    return false;
  }
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
  void preferred;
  // Only Safari / iOS. Chrome's canPlayType("hls") is a maybe on some builds
  // and must not send VOD down the HLS wrapper (that path never starts).
  if (isAppleHlsClient()) {
    return ["m3u8"];
  }
  return ["mp4"];
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
    if (q.audio) {
      params.set("audio", q.audio);
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
    width: streamInfo.width || video.videoWidth || 0,
    height: streamInfo.height || video.videoHeight || 0,
    audio: audioStatLabel(),
  };
}

function prettyCodec(raw) {
  const text = String(raw || "").toLowerCase().trim();
  if (!text) {
    return "";
  }
  const named = {
    aac: "AAC",
    "he-aac": "HE-AAC",
    "ac-3": "AC-3",
    ac3: "AC-3",
    "e-ac-3": "E-AC-3",
    eac3: "E-AC-3",
    mp2: "MP2",
    mp3: "MP3",
    dts: "DTS",
    opus: "Opus",
    flac: "FLAC",
    pcm: "PCM",
    "h.264": "H.264",
    h264: "H.264",
    hevc: "HEVC",
    "h.265": "HEVC",
    h265: "HEVC",
    av1: "AV1",
    vp9: "VP9",
  };
  if (named[text]) {
    return named[text];
  }
  if (/ec-3|ec3|eac3|e-ac-3/.test(text)) {
    return "E-AC-3";
  }
  if (/ac-3|ac3|a52/.test(text)) {
    return "AC-3";
  }
  if (/dts/.test(text)) {
    return "DTS";
  }
  if (/opus/.test(text)) {
    return "Opus";
  }
  if (/flac/.test(text)) {
    return "FLAC";
  }
  if (/vorbis/.test(text)) {
    return "Vorbis";
  }
  if (/mp4a\.40\.(5|29)|he-aac/.test(text)) {
    return "HE-AAC";
  }
  if (/mp4a|aac/.test(text)) {
    return "AAC";
  }
  if (/mp2|mpga/.test(text)) {
    return "MP2";
  }
  if (/mp3|mpeg/.test(text) && !/mpeg-4|mpeg4|mpegh/.test(text)) {
    return "MP3";
  }
  if (/pcm|lpcm/.test(text)) {
    return "PCM";
  }
  if (/hev1|hvc1|h265|hevc/.test(text)) {
    return "HEVC";
  }
  if (/avc1|avc3|h264/.test(text)) {
    return "H.264";
  }
  if (/av01|av1/.test(text)) {
    return "AV1";
  }
  if (/vp9/.test(text)) {
    return "VP9";
  }
  return "";
}

function audioLayout(channels) {
  const n = Number(channels) || 0;
  if (n >= 8) {
    return "7.1";
  }
  if (n >= 6) {
    return "5.1";
  }
  if (n === 2) {
    return "stereo";
  }
  if (n === 1) {
    return "mono";
  }
  return n ? `${n}ch` : "";
}

function resolutionTag(width, height) {
  const w = Number(width) || 0;
  const h = Number(height) || 0;
  if (w >= 3800 || h >= 2100) {
    return "4K";
  }
  if (w >= 2500 || h >= 1400) {
    return "1440p";
  }
  if (w >= 1800 || h >= 800) {
    return "1080p";
  }
  if (w >= 1200 || h >= 700) {
    return "720p";
  }
  if (w >= 700 || h >= 480) {
    return `${h || w}p`;
  }
  return "";
}

function audioStatLabel() {
  const codec = streamInfo.audio || "";
  const layout = audioLayout(streamInfo.channels);
  return [codec, layout].filter(Boolean).join(" ").slice(0, 40);
}

function resetStreamInfo() {
  streamInfo = { width: 0, height: 0, video: "", audio: "", rate: 0, channels: 0 };
  paintStreamStat();
}

function mergeStreamInfo(partial) {
  if (!partial) {
    return;
  }
  if (partial.width) {
    streamInfo.width = Number(partial.width) || streamInfo.width;
  }
  if (partial.height) {
    streamInfo.height = Number(partial.height) || streamInfo.height;
  }
  if (partial.video) {
    streamInfo.video = prettyCodec(partial.video) || streamInfo.video;
  }
  if (partial.audio) {
    streamInfo.audio = prettyCodec(partial.audio) || streamInfo.audio;
  }
  if (partial.rate) {
    streamInfo.rate = Number(partial.rate) || streamInfo.rate;
  }
  if (partial.channels) {
    streamInfo.channels = Number(partial.channels) || streamInfo.channels;
  }
  paintStreamStat();
}

function captureStreamInfo() {
  if (video.videoWidth && video.videoHeight) {
    mergeStreamInfo({ width: video.videoWidth, height: video.videoHeight });
  }
  const info = tsPlayer && tsPlayer.mediaInfo;
  if (info) {
    mergeStreamInfo({
      width: info.width,
      height: info.height,
      video: info.videoCodec,
      audio: info.audioCodec,
      rate: info.audioSampleRate,
      channels: info.audioChannelCount,
    });
  }
  if (hls) {
    const level = hls.levels?.[hls.currentLevel] || hls.levels?.[0];
    if (level) {
      const codecs = String(level.codecs || "").split(",");
      mergeStreamInfo({
        width: level.width,
        height: level.height,
        video: level.videoCodec || codecs[0],
        audio: level.audioCodec || codecs[1],
      });
    }
    const track = hls.audioTracks?.[hls.audioTrack];
    if (track?.codec) {
      mergeStreamInfo({ audio: track.codec });
    }
  }
}

function paintStreamStat() {
  if (!streamStat) {
    return;
  }
  if (!playing) {
    streamStat.hidden = true;
    streamStat.textContent = "";
    streamStat.classList.remove("is-uhd");
    return;
  }
  const w = streamInfo.width || video.videoWidth || 0;
  const h = streamInfo.height || video.videoHeight || 0;
  const tag = resolutionTag(w, h);
  const bits = [];
  if (w && h) {
    bits.push(`${w}×${h}${tag ? ` ${tag}` : ""}`);
  }
  if (streamInfo.video) {
    bits.push(streamInfo.video);
  }
  const audio = audioStatLabel();
  if (audio) {
    bits.push(audio);
  }
  if (streamInfo.rate) {
    bits.push(`${Math.round(streamInfo.rate / 1000)} kHz`);
  }
  streamStat.hidden = !bits.length;
  streamStat.textContent = bits.join(" · ");
  streamStat.classList.toggle("is-uhd", tag === "4K");
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
  if (q.audio) {
    body.audio = q.audio;
  }
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
    if (response.status === 403 && String(data.detail || "").includes("new password")) {
      stopPlayback();
      showPasswordChange();
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
  seriesName: "",
  episodeQueue: [],
  playingEpisodes: [],
  episodeIndex: -1,
  playingLiveId: "",
  playingItem: null,
  playingKind: "",
  mediaToken: "",
  wasSyncing: false,
  epgTries: 0,
  searchKind: "all",
  searchHits: { live: [], movies: [], series: [] },
  syncBusy: false,
  vodHome: null,
  vodExpanded: {},
  detailItem: null,
  detailKind: "",
  seasonId: "",
};

let hls = null;
let tsPlayer = null;
let streamInfo = { width: 0, height: 0, video: "", audio: "", rate: 0, channels: 0 };
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
let vodSeekOffset = 0;
let vodScrubbing = false;
let vodSeeking = false;
let vodHoldActive = false;
let vodChromeTimer = 0;
let vodDetailHideTimer = 0;
let vodWaitTimer = 0;
let upNextTimer = 0;
let upNextLeft = 0;
let upNextGoing = false;
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
  const live = Boolean(state.playingLiveId) || state.playingKind === "live";
  bufferRow.hidden = !canPlayMpegTs() || !live;
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
  if (!on) {
    window.clearTimeout(vodWaitTimer);
    vodWaitTimer = 0;
  }
  watchSpinner.hidden = !on;
}

function showVodWaitSpinner() {
  window.clearTimeout(vodWaitTimer);
  vodWaitTimer = window.setTimeout(() => {
    vodWaitTimer = 0;
    if (!playing || video.paused || state.playingLiveId) {
      return;
    }
    if (video.readyState < HTMLMediaElement.HAVE_FUTURE_DATA) {
      showWatchSpinner(true);
    }
  }, 500);
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

function liveLoadUrl(url) {
  try {
    const parsed = new URL(url, window.location.origin);
    parsed.searchParams.set("r", String(Date.now()));
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return url;
  }
}

function tickLiveFrozen() {
  /* Last resort only: clock frozen ~20s with an empty buffer, and no HTTP
   * error yet. Ordinary `waiting` must not reopen the Magnum socket. */
  if (!playing || !state.playingLiveId || !liveMpeg || !liveTsUrl || liveHold) {
    return;
  }
  if (liveReconnectTimer || video.paused) {
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
  if (now - lastMediaTimeAt < 20000) {
    return;
  }
  if (bufferedAhead() >= 0.4) {
    lastMediaTimeAt = now;
    return;
  }
  lastMediaTimeAt = now;
  scheduleLiveReconnect(liveTsUrl, playGen);
}

function tickLiveFill() {
  /* Spinner until the first media. Never pause the element; never 0.97×. */
  if (!playing || !state.playingLiveId) {
    return;
  }
  captureStreamInfo();
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
  if (lastLiveResume && performance.now() - lastLiveResume > 30000) {
    liveReconnectTries = 0;
  }
  tickLiveFrozen();
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
  const delay = Math.min(8000, 1500 + (liveReconnectTries - 1) * 1000);
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
  }, delay);
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

const EPG_HOURS = 8;
const EPG_PX_HOUR = 210;
const EPG_CH_W_WIDE = 344;
const EPG_CH_W_NARROW = 220;
const EPG_SNAP = 30 * 60;
let epgWinStart = 0;

function epgChannelWidth() {
  return window.innerWidth < 720 ? EPG_CH_W_NARROW : EPG_CH_W_WIDE;
}

function epgWindowStart(nowSec) {
  return Math.floor(nowSec / EPG_SNAP) * EPG_SNAP;
}

function epgX(ts) {
  return ((Number(ts) - epgWinStart) / 3600) * EPG_PX_HOUR;
}

function epgGridWidth() {
  return EPG_HOURS * EPG_PX_HOUR;
}

function epgBlockStyle(start, stop) {
  const width = epgGridWidth();
  const left = Math.max(0, epgX(start));
  const right = Math.min(width, epgX(stop));
  const w = Math.max(36, right - left - 3);
  return `left:${left + 1}px;width:${w}px`;
}

function tickEpgNow() {
  const clock = itemList && itemList.querySelector(".watch-epg-clock");
  if (clock) {
    clock.textContent = formatClock();
  }
  if (!itemList || !epgWinStart) {
    return;
  }
  const now = Date.now() / 1000;
  const line = itemList.querySelector(".watch-epg-now");
  const needle = itemList.querySelector(".watch-epg-needle");
  const x = Math.max(0, Math.min(epgGridWidth(), epgX(now)));
  if (line) {
    line.style.left = `${epgChannelWidth() + x}px`;
    line.hidden = now < epgWinStart || now > epgWinStart + EPG_HOURS * 3600;
  }
  if (needle) {
    needle.style.left = `${x}px`;
    needle.hidden = now < epgWinStart || now > epgWinStart + EPG_HOURS * 3600;
  }
  itemList.querySelectorAll(".watch-epg-prog[data-start]").forEach((el) => {
    const start = Number(el.getAttribute("data-start"));
    const stop = Number(el.getAttribute("data-stop"));
    const on = Number.isFinite(start) && Number.isFinite(stop) && start <= now && now < stop;
    el.classList.toggle("is-now", on);
  });
}

function clearEpgLayout() {
  itemList.classList.remove("is-epg");
  if (watchStage) {
    watchStage.classList.remove("is-guide");
  }
  epgWinStart = 0;
}

function renderLiveEpg(rows) {
  const now = Date.now() / 1000;
  epgWinStart = epgWindowStart(now);
  const gridW = epgGridWidth();
  const ticks = [];
  for (let t = epgWinStart; t < epgWinStart + EPG_HOURS * 3600; t += EPG_SNAP) {
    ticks.push(
      `<span class="watch-epg-tick" style="left:${epgX(t)}px">${esc(formatTime(t))}</span>`
    );
  }
  const chW = epgChannelWidth();
  const nowLeft = chW + epgX(now);
  const needleLeft = epgX(now);
  const body = rows
    .map((item, index) => {
      const here = String(item.stream_id) === String(state.playingLiveId) ? " is-here" : "";
      const num = item.num || index + 1;
      const icon = item.stream_icon
        ? `<img src="${esc(item.stream_icon)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
        : `<span></span>`;
      const listings = Array.isArray(item.guide) ? item.guide : [];
      const slots = listings.length
        ? listings
            .map((row) => {
              const start = Number(row.start || row.start_timestamp);
              const stop = Number(row.stop || row.stop_timestamp || row.end);
              if (!Number.isFinite(start) || !Number.isFinite(stop) || stop <= epgWinStart) {
                return "";
              }
              if (start >= epgWinStart + EPG_HOURS * 3600) {
                return "";
              }
              const title = row.title || "No title";
              const on = start <= now && now < stop ? " is-now" : "";
              const when = [formatTime(start), formatTime(stop)].filter(Boolean).join(" – ");
              return `<button type="button" class="watch-epg-prog${on}" data-live="${esc(item.stream_id)}" data-start="${esc(start)}" data-stop="${esc(stop)}" title="${esc(when ? `${when} · ${title}` : title)}" style="${epgBlockStyle(start, stop)}">${esc(title)}</button>`;
            })
            .join("")
        : `<span class="watch-epg-empty">No programme info</span>`;
      return `<div class="watch-epg-row${here}" data-live="${esc(item.stream_id)}"><button type="button" class="watch-epg-ch${here}" data-live="${esc(item.stream_id)}" title="${esc(item.name)}"><span class="watch-num">${esc(num)}</span>${icon}<span class="watch-item-body"><span class="watch-item-name">${esc(item.name)}</span></span></button><div class="watch-epg-slots">${slots}</div></div>`;
    })
    .join("");
  itemList.innerHTML = `<div class="watch-epg-scroller" style="--epg-ch:${chW}px;--epg-grid:${gridW}px"><div class="watch-epg-inner" style="min-width:${chW + gridW}px"><div class="watch-epg-head"><div class="watch-epg-clock">${esc(formatClock())}</div><div class="watch-epg-times">${ticks.join("")}<span class="watch-epg-needle" style="left:${needleLeft}px"></span></div></div>${body}<div class="watch-epg-now" style="left:${nowLeft}px"></div></div></div>`;
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

function vodLength() {
  if (vodRuntimeSec && vodRuntimeSec > 0) {
    return vodRuntimeSec;
  }
  const native = Number(video.duration);
  if (Number.isFinite(native) && native > 1) {
    return native + vodSeekOffset;
  }
  return 0;
}

function vodClock() {
  return Math.max(0, vodSeekOffset + (Number(video.currentTime) || 0));
}

function waitMs(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function setVodHold(on) {
  vodHoldActive = Boolean(on);
  if (videoWrap) {
    videoWrap.classList.toggle("is-vod-hold", vodHoldActive);
  }
  if (vodHoldActive) {
    video.muted = true;
    video.volume = 0;
    video.playbackRate = 1;
  }
}

function vodDecodedFrames() {
  const quality = video.getVideoPlaybackQuality?.();
  if (quality && Number.isFinite(quality.totalVideoFrames)) {
    return quality.totalVideoFrames;
  }
  const webkit = Number(video.webkitDecodedFrameCount);
  return Number.isFinite(webkit) ? webkit : 0;
}

function waitForVodSteady(gen, timeoutMs) {
  // Remuxed fMP4 often has audio ready first. Playing unmute'd lets the audio
  // clock run while video is still a smear / catch-up dump. Stay dark+silent
  // until presented fps is movie-rate and the playhead is 1x with buffer.
  const limit = Math.max(4000, Number(timeoutMs) || 20000);
  return new Promise((resolve) => {
    let settled = false;
    let poll = 0;
    let rvfc = 0;
    let presented = 0;
    let prevPresented = 0;
    let prevFrames = vodDecodedFrames();
    let prevMedia = Number(video.currentTime) || 0;
    let prevAt = 0;
    let smoothMs = 0;
    const finish = () => {
      if (settled) {
        return;
      }
      settled = true;
      window.clearTimeout(timer);
      window.clearInterval(poll);
      if (rvfc && video.cancelVideoFrameCallback) {
        try {
          video.cancelVideoFrameCallback(rvfc);
        } catch {
          /* ignore */
        }
      }
      resolve();
    };
    const onFrame = () => {
      presented += 1;
      if (!settled && video.requestVideoFrameCallback) {
        rvfc = video.requestVideoFrameCallback(onFrame);
      }
    };
    if (video.requestVideoFrameCallback) {
      rvfc = video.requestVideoFrameCallback(onFrame);
    }
    const timer = window.setTimeout(finish, limit);
    const tick = () => {
      if (settled) {
        return;
      }
      if (gen != null && gen !== playGen) {
        finish();
        return;
      }
      const now = performance.now();
      if (!prevAt) {
        prevAt = now;
        prevFrames = vodDecodedFrames();
        prevPresented = presented;
        prevMedia = Number(video.currentTime) || 0;
        return;
      }
      const dt = now - prevAt;
      if (dt < 280) {
        return;
      }
      const frames = vodDecodedFrames();
      const media = Number(video.currentTime) || 0;
      const decodedFps = (frames - prevFrames) / (dt / 1000);
      const presentedFps = (presented - prevPresented) / (dt / 1000);
      const clockRate = (media - prevMedia) / (dt / 1000);
      const fps = presentedFps >= 8 ? presentedFps : decodedFps;
      prevFrames = frames;
      prevPresented = presented;
      prevMedia = media;
      prevAt = now;
      const picture = video.videoWidth >= 16 && video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA;
      const realtime =
        picture &&
        !video.paused &&
        fps >= 18 &&
        fps <= 40 &&
        clockRate >= 0.9 &&
        clockRate <= 1.12 &&
        bufferedAhead() >= 0.75;
      if (realtime) {
        smoothMs += dt;
      } else {
        smoothMs = 0;
      }
      if (smoothMs >= 1100) {
        finish();
      }
    };
    poll = window.setInterval(tick, 100);
  });
}

function isTouchIos() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

function isVodPlay() {
  return state.playingKind === "movie" || state.playingKind === "series";
}

function flattenEpisodes(detail) {
  const grouped = (detail && detail.episodes) || {};
  const seasons = Object.keys(grouped).sort((a, b) => Number(a) - Number(b));
  const rows = [];
  seasons.forEach((season) => {
    (grouped[season] || []).forEach((ep) => {
      if (!ep || ep.id == null) {
        return;
      }
      const info = ep.info || {};
      rows.push({
        id: String(ep.id),
        title: ep.title || "",
        episode_num: ep.episode_num,
        season,
        container_extension: ep.container_extension || info.container_extension || "mp4",
        plot: ep.plot || info.plot || "",
        duration: ep.duration || info.duration || "",
        duration_secs: ep.duration_secs || info.duration_secs || "",
        still: ep.still || info.movie_image || "",
        rating: ep.rating || info.rating || "",
        release_date: ep.release_date || info.release_date || info.air_date || "",
      });
    });
  });
  return rows;
}

function episodeLabel(episode) {
  if (!episode) {
    return "Episode";
  }
  const bits = [];
  if (episode.season != null && episode.season !== "") {
    bits.push(`S${episode.season}`);
  }
  if (episode.episode_num != null && episode.episode_num !== "") {
    bits.push(`E${episode.episode_num}`);
  }
  bits.push(episode.title || `Episode ${episode.episode_num || episode.id || ""}`.trim());
  return bits.filter(Boolean).join(" · ");
}

function currentEpisodeOffset(delta) {
  const queue = state.playingEpisodes || [];
  const index = Number(state.episodeIndex);
  if (!queue.length || !Number.isInteger(index) || index < 0) {
    return null;
  }
  return queue[index + delta] || null;
}

function upNextOpen() {
  return Boolean(vodUpNext && !vodUpNext.hidden);
}

function hideUpNext() {
  if (upNextTimer) {
    window.clearInterval(upNextTimer);
    upNextTimer = 0;
  }
  upNextLeft = 0;
  if (vodUpNext) {
    vodUpNext.hidden = true;
  }
}

function paintEpisodeButtons() {
  const series = state.playingKind === "series";
  const prev = series ? currentEpisodeOffset(-1) : null;
  const next = series ? currentEpisodeOffset(1) : null;
  if (vodEpPrev) {
    vodEpPrev.hidden = !prev;
  }
  if (vodEpNext) {
    vodEpNext.hidden = !next;
  }
}

async function goAdjacentEpisode(delta) {
  const target = currentEpisodeOffset(delta);
  if (!target || upNextGoing) {
    return;
  }
  upNextGoing = true;
  hideUpNext();
  try {
    await playEpisode(target, state.seriesName);
  } finally {
    upNextGoing = false;
  }
}

function showUpNext(next) {
  if (!next) {
    return;
  }
  hideUpNext();
  if (!vodUpNext) {
    goAdjacentEpisode(1).catch(() => {});
    return;
  }
  vodUpNext.hidden = false;
  if (vodUpNextTitle) {
    vodUpNextTitle.textContent = episodeLabel(next);
  }
  upNextLeft = UP_NEXT_SECS;
  if (vodUpNextSecs) {
    vodUpNextSecs.textContent = String(upNextLeft);
  }
  showVodChrome();
  upNextTimer = window.setInterval(() => {
    upNextLeft -= 1;
    if (vodUpNextSecs) {
      vodUpNextSecs.textContent = String(Math.max(0, upNextLeft));
    }
    if (upNextLeft <= 0) {
      hideUpNext();
      goAdjacentEpisode(1).catch(() => {});
    }
  }, 1000);
}

function vodUsesOverlay() {
  return isVodPlay() && !isTouchIos();
}

function paintVodPlayBtn() {
  if (!vodPlayBtn) {
    return;
  }
  const paused = video.paused || video.ended;
  vodPlayBtn.textContent = paused ? "▶" : "❚❚";
  vodPlayBtn.setAttribute("aria-label", paused ? "Play" : "Pause");
}

function paintVodMuteBtn() {
  if (!vodMuteBtn) {
    return;
  }
  const muted = video.muted || video.volume === 0;
  vodMuteBtn.textContent = muted ? "🔇" : "🔊";
  vodMuteBtn.setAttribute("aria-label", muted ? "Unmute" : "Mute");
}

function storedVodRate() {
  const n = Number(localStorage.getItem("watch_vod_rate"));
  return VOD_RATES.includes(n) ? n : 1;
}

function paintVodRateBtn() {
  if (!vodRateBtn) {
    return;
  }
  const rate = Number(video.playbackRate) || storedVodRate();
  const label = `${rate}×`;
  vodRateBtn.textContent = label;
  vodRateBtn.title = `Playback speed ${label}`;
}

function applyVodRate(rate, persist) {
  const next = VOD_RATES.includes(rate) ? rate : 1;
  video.playbackRate = next;
  try {
    video.preservesPitch = true;
  } catch {
    /* ignore */
  }
  if (persist !== false) {
    localStorage.setItem("watch_vod_rate", String(next));
  }
  paintVodRateBtn();
}

function cycleVodRate() {
  const cur = Number(video.playbackRate) || storedVodRate();
  const idx = VOD_RATES.indexOf(cur);
  applyVodRate(VOD_RATES[(idx + 1) % VOD_RATES.length], true);
  showVodChrome();
}

function paintSkipIntro() {
  if (!vodSkipIntro) {
    return;
  }
  const length = vodLength();
  const pos = vodClock();
  const show =
    isVodPlay() &&
    vodUsesOverlay() &&
    length >= 10 * 60 &&
    pos < 6 * 60 &&
    pos + SKIP_INTRO_SEC < length - 30;
  vodSkipIntro.hidden = !show;
}

function showVodChrome() {
  if (!vodChrome || vodChrome.hidden) {
    return;
  }
  vodChrome.classList.add("is-on");
  if (videoWrap) {
    videoWrap.classList.remove("is-vod-idle");
  }
  window.clearTimeout(vodChromeTimer);
  if (video.paused || vodScrubbing || upNextOpen()) {
    return;
  }
  const dock = vodChrome.querySelector(".watch-vod-dock");
  if (dock && dock.matches(":hover")) {
    return;
  }
  vodChromeTimer = window.setTimeout(() => {
    if (video.paused || vodScrubbing || upNextOpen()) {
      return;
    }
    vodChrome.classList.remove("is-on");
    if (videoWrap) {
      videoWrap.classList.add("is-vod-idle");
    }
  }, 2200);
}

function setPlayerChrome() {
  const overlay = vodUsesOverlay();
  video.controls = !overlay;
  if (vodChrome) {
    vodChrome.hidden = !overlay;
    if (!overlay) {
      vodChrome.classList.remove("is-on");
    }
  }
  if (videoWrap) {
    videoWrap.classList.toggle("is-vod-idle", false);
  }
  if (overlay && !vodHoldActive) {
    const stored = Number(localStorage.getItem("watch_volume"));
    if (Number.isFinite(stored) && stored >= 0 && stored <= 1) {
      video.volume = stored;
      video.muted = stored === 0;
    }
    if (vodVol) {
      vodVol.value = String(video.muted ? 0 : video.volume);
    }
    paintVodPlayBtn();
    paintVodMuteBtn();
    paintEpisodeButtons();
    paintVodRateBtn();
    showVodChrome();
  }
}

function toggleVodPlay() {
  if (upNextOpen()) {
    goAdjacentEpisode(1).catch(() => {});
    return;
  }
  if (video.paused || video.ended) {
    const play = video.play();
    if (play && typeof play.catch === "function") {
      play.catch(() => {});
    }
  } else {
    video.pause();
  }
  paintVodPlayBtn();
  showVodChrome();
}

function toggleVodMute() {
  if (vodHoldActive) {
    return;
  }
  video.muted = !video.muted;
  if (!video.muted && video.volume === 0) {
    video.volume = 0.5;
  }
  if (!video.muted) {
    localStorage.setItem("watch_volume", String(video.volume));
  }
  if (vodVol) {
    vodVol.value = String(video.muted ? 0 : video.volume);
  }
  paintVodMuteBtn();
  showVodChrome();
}

function fullscreenNode() {
  return document.fullscreenElement || document.webkitFullscreenElement || null;
}

function syncVodFsClass() {
  const fs = fullscreenNode();
  const on = Boolean(fs && (fs === videoWrap || fs === video || (videoWrap && videoWrap.contains(fs))));
  if (videoWrap) {
    videoWrap.classList.toggle("is-fs", on);
  }
  if (vodFsBtn) {
    vodFsBtn.setAttribute("aria-label", on ? "Exit full screen" : "Full screen");
    vodFsBtn.title = on ? "Exit full screen" : "Full screen";
  }
}

function requestNodeFullscreen(node) {
  if (!node) {
    return Promise.reject(new Error("no node"));
  }
  if (node.requestFullscreen) {
    return node.requestFullscreen({ navigationUI: "hide" }).catch(() => node.requestFullscreen());
  }
  if (node.webkitRequestFullscreen) {
    node.webkitRequestFullscreen();
    return Promise.resolve();
  }
  return Promise.reject(new Error("no fullscreen"));
}

function toggleVodFs() {
  const node = videoWrap || video;
  if (fullscreenNode()) {
    if (document.exitFullscreen) {
      document.exitFullscreen().catch(() => {});
    } else {
      document.webkitExitFullscreen?.();
    }
    return;
  }
  requestNodeFullscreen(node).catch(() => {
    if (video.webkitEnterFullscreen) {
      video.webkitEnterFullscreen();
      return;
    }
    requestNodeFullscreen(video).catch(() => {});
  });
}

function paintVodSeek(at) {
  const overlay = vodUsesOverlay();
  const length = vodLength();
  const pos = Math.max(0, Math.min(length || 0, at == null ? vodClock() : at));
  if (vodChrome) {
    vodChrome.hidden = !overlay;
  }
  if (nowNext) {
    nowNext.hidden = overlay;
  }
  if (vodSeekTime) {
    vodSeekTime.textContent = length
      ? `${formatRuntime(pos)} / ${formatRuntime(length)}`
      : "0:00 / 0:00";
  }
  if (vodSeekRange && length) {
    vodSeekRange.style.setProperty("--seek-pct", `${(pos / length) * 100}%`);
    if (!vodScrubbing) {
      vodSeekRange.value = String(Math.round((pos / length) * 1000));
    }
  }
  paintVodPlayBtn();
  paintSkipIntro();
}

function rangeToVodTime() {
  const length = vodLength();
  const raw = Number(vodSeekRange && vodSeekRange.value);
  if (!length || !Number.isFinite(raw)) {
    return 0;
  }
  return (raw / 1000) * length;
}

async function seekVod(seconds) {
  if (state.playingLiveId) {
    return;
  }
  const length = vodLength();
  if (!length) {
    return;
  }
  const target = Math.max(0, Math.min(length - 0.25, Number(seconds) || 0));
  if (Math.abs(target - vodClock()) < 0.4 && !vodSeeking) {
    paintVodSeek(target);
    return;
  }
  const item = state.playingItem;
  const kind = state.playingKind;
  if (!item || (kind !== "movie" && kind !== "series")) {
    return;
  }
  vodSeeking = true;
  showWatchSpinner(true);
  const gen = ++playGen;
  // Abort the current Magnum pull before asking for a new one.
  destroyPlayers();
  vodSeekOffset = target;
  paintVodSeek(target);
  paintSkipIntro();
  await waitMs(250);
  if (gen !== playGen) {
    vodSeeking = false;
    return;
  }
  const streamId = String(item.stream_id || item.id || "");
  const ext = String(item.container_extension || "mp4").replace(/^\./, "");
  try {
    await playSources(kind === "movie" ? "movie" : "series", streamId, vodExtensions(ext), gen);
  } catch (error) {
    if (gen !== playGen) {
      return;
    }
    vodSeekOffset = 0;
    showBanner(error.message, "bad");
  } finally {
    if (gen === playGen) {
      vodSeeking = false;
      showWatchSpinner(false);
    }
  }
}

function paintVodRuntime() {
  if (!vodRuntimeSec || state.playingLiveId) {
    if (state.playingLiveId) {
      setPlayerChrome();
    }
    return;
  }
  if (vodScrubbing) {
    return;
  }
  const played = vodClock();
  if (nowNext && !vodUsesOverlay()) {
    nowNext.hidden = false;
    nowNext.textContent = `${formatRuntime(played)} / ${formatRuntime(vodRuntimeSec)}`;
  }
  if (nowProgressWrap) {
    nowProgressWrap.hidden = true;
  }
  paintVodSeek(played);
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
  vodSeekOffset = 0;
  vodScrubbing = false;
  vodSeeking = false;
  if (vodChrome) {
    vodChrome.hidden = true;
    vodChrome.classList.remove("is-on");
  }
  if (nowNext) {
    nowNext.hidden = false;
  }
  if (videoWrap) {
    videoWrap.classList.remove("is-vod-idle");
    videoWrap.classList.remove("is-vod-hold");
  }
  vodHoldActive = false;
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
  tickEpgNow();
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
  paintRefreshButtons(!!enabled);
}

const SYNC_COOLDOWN_MS = 5 * 60 * 1000;
const SYNC_COOLDOWN_KEY = {
  playlist: "watch_sync_cd_playlist",
  epg: "watch_sync_cd_epg",
};
const SYNC_BTN_LABEL = {
  playlist: "Refresh list",
  epg: "Refresh EPG",
};

function syncCooldownLeft(kind) {
  try {
    const started = Number(localStorage.getItem(SYNC_COOLDOWN_KEY[kind]) || 0);
    if (!started) {
      return 0;
    }
    return Math.max(0, started + SYNC_COOLDOWN_MS - Date.now());
  } catch {
    return 0;
  }
}

function markSyncClicked(kind) {
  try {
    localStorage.setItem(SYNC_COOLDOWN_KEY[kind], String(Date.now()));
  } catch {
    /* ignore */
  }
}

function formatCooldown(ms) {
  const total = Math.ceil(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  if (m <= 0) {
    return `Wait ${s}s`;
  }
  return `Wait ${m}:${String(s).padStart(2, "0")}`;
}

let refreshCooldownTimer = null;

function paintRefreshButtons(canRefresh) {
  const allowed = canRefresh !== false && state.configured && !state.syncBusy;
  const rows = [
    ["playlist", refreshPlaylistBtn],
    ["epg", refreshEpgBtn],
  ];
  let ticking = false;
  for (const [kind, btn] of rows) {
    if (!btn) {
      continue;
    }
    const left = syncCooldownLeft(kind);
    if (left > 0) {
      ticking = true;
    }
    const on = allowed && left <= 0;
    btn.disabled = !on;
    btn.textContent = left > 0 ? formatCooldown(left) : SYNC_BTN_LABEL[kind];
  }
  if (ticking && !refreshCooldownTimer) {
    refreshCooldownTimer = window.setInterval(() => paintRefreshButtons(), 1000);
  }
  if (!ticking && refreshCooldownTimer) {
    clearInterval(refreshCooldownTimer);
    refreshCooldownTimer = null;
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
  let ageBit = "";
  if (Number.isFinite(age)) {
    if (age < 120) {
      ageBit = "just now";
    } else if (age < 3600) {
      ageBit = `${Math.floor(age / 60)}m ago`;
    } else {
      ageBit = `${Math.floor(age / 3600)}h ago`;
    }
  }
  const ch = Number(sync.streams);
  const chBit = Number.isFinite(ch) ? `${ch} ch` : "";
  const epg = Number(sync.epg_channels);
  const epgBit = Number.isFinite(epg) && epg > 0 ? `${epg} EPG` : "";
  guideStat.textContent = [chBit, epgBit, ageBit].filter(Boolean).join(" · ") || "—";
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
  if (passwordPanel) {
    passwordPanel.hidden = true;
  }
  loginPanel.hidden = false;
  appPanel.hidden = true;
}

function showPasswordChange() {
  if (termsPanel) {
    termsPanel.hidden = true;
  }
  loginPanel.hidden = true;
  appPanel.hidden = true;
  if (passwordPanel) {
    passwordPanel.hidden = false;
  }
  if (passwordError) {
    passwordError.hidden = true;
    passwordError.textContent = "";
  }
}

function showApp() {
  if (termsPanel) {
    termsPanel.hidden = true;
  }
  if (passwordPanel) {
    passwordPanel.hidden = true;
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
    if (passwordPanel) {
      passwordPanel.hidden = true;
    }
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
  try {
    video.removeAttribute("src");
    video.src = "";
  } catch {
    /* ignore */
  }
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
  resetStreamInfo();
  paintBufferButtons();
  setPlayerChrome();
  hideUpNext();
  if (isVodPlay()) {
    paintVodSeek();
  }
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
  if (kind !== "live") {
    const src = String(state.playingItem?.container_extension || "mp4").replace(/^\./, "");
    if (src && src !== "m3u8" && src !== "mpd") {
      params.set("src", src);
    }
    params.set("vc", canPlayHevc() ? "h264,hevc" : "h264");
    if (vodSeekOffset >= 1) {
      params.set("start", String(Math.floor(vodSeekOffset)));
    }
    if (canPlayNativeHls()) {
      params.set("cb", String(Date.now()));
    }
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
        video.src = vodSeekOffset >= 1 ? `${url}#t=${Math.floor(vodSeekOffset)}` : url;
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
      startPosition: vodSeekOffset >= 1 ? vodSeekOffset : -1,
    });
    const onError = (_event, info) => {
      if (info?.fatal) {
        hls.off(window.Hls.Events.ERROR, onError);
        done(false, new Error("HLS failed"));
      }
    };
    hls.on(window.Hls.Events.ERROR, onError);
    hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
      captureStreamInfo();
      done(true, "hls");
    });
    if (window.Hls.Events.LEVEL_SWITCHED) {
      hls.on(window.Hls.Events.LEVEL_SWITCHED, () => captureStreamInfo());
    }
    if (window.Hls.Events.AUDIO_TRACK_SWITCHED) {
      hls.on(window.Hls.Events.AUDIO_TRACK_SWITCHED, () => captureStreamInfo());
    }
    hls.loadSource(url);
    hls.attachMedia(video);
  });
}

function playNow() {
  if (vodHoldActive) {
    video.muted = true;
    video.volume = 0;
    video.playbackRate = 1;
  } else if (!vodUsesOverlay()) {
    video.muted = false;
    video.defaultMuted = false;
    if (!Number.isFinite(video.volume) || video.volume === 0) {
      video.volume = 1;
    }
  }
  if (!vodHoldActive && vodUsesOverlay()) {
    applyVodRate(storedVodRate(), false);
  } else if (!vodHoldActive && !liveHold && video.playbackRate !== 1) {
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
      url: live ? liveLoadUrl(url) : url,
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
      accurateSeek: !live,
      fixAudioTimestampGap: true,
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
          /network|http|status|eof|unrecoverable|loader/i.test(`${kind} ${msg}`))
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
    if (window.mpegts.Events.MEDIA_INFO) {
      tsPlayer.on(window.mpegts.Events.MEDIA_INFO, (info) => {
        if (gen !== playGen) {
          return;
        }
        mergeStreamInfo({
          width: info?.width,
          height: info?.height,
          video: info?.videoCodec,
          audio: info?.audioCodec,
          rate: info?.audioSampleRate,
          channels: info?.audioChannelCount,
        });
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
        // Safari / iOS: native HLS only. hls.js MSE on desktop Safari never
        // starts VOD (clock stuck at 0:00). iOS has no MSE.
        if (canPlayNativeHls()) {
          if (kind !== "live") {
            showWatchSpinner(true);
          }
          video.src = url;
          video.load();
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
        if (!vodUsesOverlay()) {
          video.muted = false;
          video.defaultMuted = false;
          video.volume = 1;
        }
        if (kind !== "live") {
          showWatchSpinner(true);
        }
        const holdAudio = kind !== "live" && vodUsesOverlay();
        const wasMuted = video.muted;
        const wasVolume = Number.isFinite(video.volume) ? video.volume : 1;
        try {
          if (holdAudio) {
            setVodHold(true);
          }
          playNow();
          if (kind !== "live") {
            await video.play().catch((error) => {
              if (error && error.name === "AbortError") {
                return;
              }
              throw error;
            });
            await waitForVodSteady(gen, 20000);
          }
        } finally {
          if (holdAudio && (gen == null || gen === playGen)) {
            setVodHold(false);
            video.volume = wasVolume;
            video.muted = wasMuted;
            applyVodRate(storedVodRate(), false);
            paintVodMuteBtn();
          } else if (holdAudio) {
            setVodHold(false);
          }
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
  setPlayingVod(false);
  hideVodDetail();
  const gen = ++playGen;
  liveReconnectTries = 0;
  clearVodRuntime();
  hideUpNext();
  state.playingLiveId = String(item.stream_id);
  state.playingKind = "live";
  state.playingItem = item;
  state.episodeIndex = -1;
  setPreview(item, { fallback: "Starting…" });
  paintBufferButtons();
  setPlayerChrome();
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
        if (state.tab !== "live" || !itemList.classList.contains("is-epg")) {
          renderItems();
        }
      }
    })
    .catch(() => {
      /* keep now/next from the channel list */
    });
}

async function playVod(item) {
  presentVodPlayer();
  const gen = ++playGen;
  vodSeekOffset = 0;
  clearVodRuntime();
  hideUpNext();
  state.playingLiveId = "";
  state.playingKind = "movie";
  state.playingItem = item;
  state.episodeIndex = -1;
  const ext = String(item.container_extension || "mp4").replace(/^\./, "");
  nowTitle.textContent = vodTitle(item) || `Title ${item.stream_id}`;
  nowEpg.textContent = item.plot || "";
  setProgress(0, 0);
  setVodRuntime(parseRuntime(item.duration_secs, { seconds: true }) || parseRuntime(item.duration));
  paintBufferButtons();
  setPlayerChrome();
  vodSeekOffset = vodResumeSeconds("movie", item.stream_id);
  paintVodSeek();
  if (!vodRuntimeSec && nowNext && !vodUsesOverlay()) {
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
  presentVodPlayer();
  const gen = ++playGen;
  vodSeekOffset = 0;
  clearVodRuntime();
  hideUpNext();
  state.playingLiveId = "";
  state.playingKind = "series";
  const id = String(episode.id || "");
  const fromBrowse = state.episodeQueue || [];
  if (fromBrowse.some((row) => String(row.id) === id)) {
    state.playingEpisodes = fromBrowse;
  } else if (!(state.playingEpisodes || []).some((row) => String(row.id) === id)) {
    state.playingEpisodes = [{ ...episode, id }];
  }
  state.episodeIndex = (state.playingEpisodes || []).findIndex((row) => String(row.id) === id);
  if (seriesName) {
    state.seriesName = seriesName;
  }
  state.playingItem = {
    ...episode,
    stream_id: episode.id,
    name: `${state.seriesName || "Series"} · ${episode.title || `Episode ${episode.episode_num}`}`,
  };
  const ext = String(episode.container_extension || "mp4").replace(/^\./, "");
  nowTitle.textContent = `${state.seriesName || "Series"} · ${episode.title || `Episode ${episode.episode_num}`}`;
  nowEpg.textContent = episode.plot || episode.info?.plot || "";
  setProgress(0, 0);
  setVodRuntime(
    parseRuntime(episode.duration_secs || episode.info?.duration_secs, { seconds: true }) ||
      parseRuntime(episode.duration || episode.info?.duration)
  );
  paintBufferButtons();
  setPlayerChrome();
  vodSeekOffset = vodResumeSeconds("series", episode.id);
  paintVodSeek();
  if (!vodRuntimeSec && nowNext && !vodUsesOverlay()) {
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

function isVodBrowseTab(tab) {
  return tab === "movies" || tab === "series";
}

function vodBrowseKind() {
  return state.tab === "series" ? "series" : "movie";
}

function vodTitle(item) {
  return String((item && (item.display_name || item.name)) || "").trim();
}

function vodPoster(item) {
  return String((item && (item.poster || item.stream_icon || item.cover || item.cover_big)) || "").trim();
}

function vodBackdrop(item) {
  return String((item && (item.backdrop || item.cover_big || vodPoster(item))) || "").trim();
}

function vodItemId(item, kind) {
  if (!item) {
    return "";
  }
  return String(kind === "series" ? item.series_id : item.stream_id || "");
}

function tearDownVodPlayer() {
  playGen += 1;
  lastSeenWrite = 0;
  markVodProgress();
  setPlayingVod(false);
  stopPlayback();
  state.playingKind = "";
  state.playingItem = null;
  clearVodRuntime();
}

function setVodBrowse(on) {
  if (appPanel) {
    appPanel.classList.toggle("is-vod-home", on);
  }
  hideVodDetail();
  state.detailItem = null;
  state.detailKind = "";
  state.seasonId = "";
  // Catalog tabs must stay on the grid. Re-applying is-playing-vod from
  // leftover playingKind made Close pop the player back open on Movies/Series.
  if (appPanel && appPanel.classList.contains("is-playing-vod")) {
    tearDownVodPlayer();
    releaseSlot().catch(() => {});
  } else {
    setPlayingVod(false);
  }
}

function setPlayingVod(on) {
  if (appPanel) {
    appPanel.classList.toggle("is-playing-vod", on);
  }
  if (vodPlayerClose) {
    vodPlayerClose.hidden = !on;
  }
}

function motionOff() {
  return Boolean(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

function showVodDetail() {
  if (!vodDetail) {
    return;
  }
  if (vodDetailHideTimer) {
    clearTimeout(vodDetailHideTimer);
    vodDetailHideTimer = 0;
  }
  vodDetail.hidden = false;
  vodDetail.inert = false;
  vodDetail.setAttribute("aria-hidden", "false");
  vodDetail.classList.remove("is-open");
  void vodDetail.offsetWidth;
  vodDetail.classList.add("is-open");
}

function concealVodDetail() {
  if (!vodDetail) {
    return;
  }
  vodDetail.classList.remove("is-open");
  vodDetail.setAttribute("aria-hidden", "true");
  vodDetail.inert = true;
  if (vodDetailHideTimer) {
    clearTimeout(vodDetailHideTimer);
  }
  const finish = () => {
    vodDetailHideTimer = 0;
    if (vodDetail && !vodDetail.classList.contains("is-open")) {
      vodDetail.hidden = true;
    }
  };
  if (motionOff() || vodDetail.hidden) {
    finish();
    return;
  }
  vodDetailHideTimer = window.setTimeout(finish, 220);
}

function clearVodDetailBody() {
  if (vodDetailEps) {
    vodDetailEps.hidden = true;
    vodDetailEps.innerHTML = "";
  }
  if (vodDetailPeople) {
    vodDetailPeople.hidden = true;
    vodDetailPeople.innerHTML = "";
  }
}

function hideVodDetail() {
  if (vodDetailHideTimer) {
    clearTimeout(vodDetailHideTimer);
    vodDetailHideTimer = 0;
  }
  if (vodDetail) {
    vodDetail.classList.remove("is-open");
    vodDetail.hidden = true;
    vodDetail.inert = true;
    vodDetail.setAttribute("aria-hidden", "true");
  }
  clearVodDetailBody();
}

function presentVodPlayer() {
  concealVodDetail();
  setPlayingVod(true);
}

function seenStoreKey() {
  return `watch_seen_${state.user || "anon"}`;
}

function loadSeen() {
  try {
    const raw = JSON.parse(localStorage.getItem(seenStoreKey()) || "{}");
    return raw && typeof raw === "object" ? raw : {};
  } catch {
    return {};
  }
}

function seenRecord(kind, id) {
  return loadSeen()[`${kind}:${id}`] || null;
}

function isWatched(kind, id) {
  const row = seenRecord(kind, id);
  return Boolean(row && row.watched);
}

function saveSeen(kind, id, patch) {
  if (!id) {
    return;
  }
  const all = loadSeen();
  const key = `${kind}:${id}`;
  all[key] = { ...(all[key] || {}), ...patch, at: Date.now() };
  const keys = Object.keys(all);
  if (keys.length > 120) {
    keys
      .sort((a, b) => Number((all[a] && all[a].at) || 0) - Number((all[b] && all[b].at) || 0))
      .slice(0, keys.length - 100)
      .forEach((drop) => {
        delete all[drop];
      });
  }
  try {
    localStorage.setItem(seenStoreKey(), JSON.stringify(all));
  } catch {
    /* ignore quota */
  }
}

let lastSeenWrite = 0;

function markVodProgress() {
  if (!isVodPlay() || !state.playingItem) {
    return;
  }
  const item = state.playingItem;
  const id = String(item.stream_id || item.id || "");
  if (!id) {
    return;
  }
  const dur = vodLength();
  const pos = vodClock();
  if (!Number.isFinite(pos) || pos < 2) {
    return;
  }
  const watched = (dur > 0 && pos / dur >= 0.9) || video.ended;
  const now = Date.now();
  if (!watched && now - lastSeenWrite < 4000) {
    return;
  }
  lastSeenWrite = now;
  const kind = state.playingKind === "series" ? "ep" : "movie";
  saveSeen(kind, id, {
    pos,
    dur,
    watched,
    title: item.name || item.title || "",
    poster: vodPoster(item) || item.still || "",
    seriesName: state.seriesName || "",
    seriesId: String(state.detailItem?.series_id || item.series_id || ""),
    season: item.season || "",
    episode_num: item.episode_num || "",
    ext: String(item.container_extension || "mp4").replace(/^\./, ""),
    plot: item.plot || "",
  });
}

function vodResumeSeconds(kind, id) {
  const rec = seenRecord(kind === "series" ? "ep" : "movie", id);
  if (!rec || rec.watched) {
    return 0;
  }
  const pos = Number(rec.pos);
  const dur = Number(rec.dur) || 0;
  if (!Number.isFinite(pos) || pos < 20) {
    return 0;
  }
  if (dur > 0 && pos / dur >= 0.9) {
    return 0;
  }
  return pos;
}

function seriesPlayTarget() {
  const queue = state.episodeQueue || state.playingEpisodes || [];
  if (!queue.length) {
    return null;
  }
  let best = null;
  queue.forEach((ep) => {
    const rec = seenRecord("ep", ep.id);
    if (rec && !rec.watched && Number(rec.pos) > 20) {
      if (!best || Number(rec.at) > Number(best.at)) {
        best = { ep, at: rec.at };
      }
    }
  });
  if (best) {
    return best.ep;
  }
  return queue.find((ep) => !isWatched("ep", ep.id)) || queue[0];
}

function paintVodDetailPlay() {
  if (!vodDetailPlay) {
    return;
  }
  const kind = state.detailKind;
  const item = state.detailItem;
  if (!item) {
    vodDetailPlay.textContent = "Play";
    return;
  }
  if (kind === "series") {
    const ep = seriesPlayTarget();
    if (!ep) {
      vodDetailPlay.textContent = "Play";
      return;
    }
    const rec = seenRecord("ep", ep.id);
    if (rec && !rec.watched && Number(rec.pos) > 20) {
      vodDetailPlay.textContent = `Resume ${episodeLabel(ep)}`;
      return;
    }
    vodDetailPlay.textContent = `Play ${episodeLabel(ep)}`;
    return;
  }
  const rec = seenRecord("movie", vodItemId(item, "movie"));
  if (rec && !rec.watched && Number(rec.pos) > 20) {
    vodDetailPlay.textContent = `Resume ${formatRuntime(rec.pos)}`;
    return;
  }
  vodDetailPlay.textContent = "Play";
}

function continueRows(tabKind) {
  const want = tabKind === "series" ? "ep" : "movie";
  const all = loadSeen();
  return Object.keys(all)
    .map((key) => {
      const split = key.indexOf(":");
      if (split < 1) {
        return null;
      }
      const kind = key.slice(0, split);
      const id = key.slice(split + 1);
      const rec = all[key];
      if (kind !== want || !rec || rec.watched || !id) {
        return null;
      }
      const pos = Number(rec.pos);
      const dur = Number(rec.dur) || 0;
      if (!Number.isFinite(pos) || pos < 20) {
        return null;
      }
      if (dur > 0 && pos / dur >= 0.9) {
        return null;
      }
      const pct = dur > 0 ? Math.max(4, Math.min(96, Math.round((pos / dur) * 100))) : 8;
      return { kind, id, rec, pos, dur, pct, at: Number(rec.at) || 0 };
    })
    .filter(Boolean)
    .sort((a, b) => b.at - a.at)
    .slice(0, 16);
}

function continueCard(row) {
  const rec = row.rec || {};
  const title =
    row.kind === "ep"
      ? `${rec.seriesName || "Show"} · ${rec.title || `Episode ${rec.episode_num || row.id}`}`
      : rec.title || `Title ${row.id}`;
  const art = rec.poster || "";
  const img = art
    ? `<img src="${esc(art)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
    : `<span class="watch-poster-fallback">${esc((title || "?").slice(0, 1))}</span>`;
  const attr = row.kind === "ep" ? `data-continue-ep="${esc(row.id)}"` : `data-continue-movie="${esc(row.id)}"`;
  const sub = formatRuntime(row.pos) + (row.dur ? ` / ${formatRuntime(row.dur)}` : "");
  return `<button type="button" class="watch-poster" ${attr}><span class="watch-poster-art">${img}<span class="watch-poster-bar" style="--pct:${row.pct}%"><i></i></span></span><span class="watch-poster-copy"><span class="watch-poster-name">${esc(title)}</span><span class="watch-poster-year">${esc(sub)}</span></span></button>`;
}

function continueWatchingRow(tabKind) {
  const rows = continueRows(tabKind);
  if (!rows.length) {
    return "";
  }
  return `<section class="watch-row" data-vod-group="continue">
    <header class="watch-row-head"><h3>Continue watching</h3></header>
    <div class="watch-row-frame">
      <button type="button" class="watch-row-arrow is-prev" data-row-dir="-1" hidden aria-label="Previous">‹</button>
      <div class="watch-row-scroll">${rows.map(continueCard).join("")}</div>
      <button type="button" class="watch-row-arrow is-next" data-row-dir="1" hidden aria-label="Next">›</button>
    </div>
  </section>`;
}

async function playContinueMovie(id) {
  const rec = seenRecord("movie", id) || {};
  const item = findVodItem("movie", id) || {
    stream_id: id,
    name: rec.title || `Title ${id}`,
    poster: rec.poster || "",
    plot: rec.plot || "",
    container_extension: rec.ext || "mp4",
    duration_secs: rec.dur || "",
  };
  await playVod(item);
}

async function playContinueEpisode(id) {
  const rec = seenRecord("ep", id) || {};
  if (rec.seriesId) {
    try {
      const detail = await api(`/api/player/series/info?series_id=${encodeURIComponent(rec.seriesId)}`);
      state.seriesDetail = detail;
      state.seriesName = rec.seriesName || vodTitle(detail.info) || state.seriesName;
      state.episodeQueue = flattenEpisodes(detail);
      state.playingEpisodes = state.episodeQueue;
      const hit = (state.episodeQueue || []).find((row) => String(row.id) === String(id));
      if (hit) {
        await playEpisode(hit, state.seriesName);
        return;
      }
    } catch {
      /* play the stub below */
    }
  }
  await playEpisode(
    {
      id,
      title: rec.title || "",
      container_extension: rec.ext || "mp4",
      plot: rec.plot || "",
      duration_secs: rec.dur || "",
      season: rec.season,
      episode_num: rec.episode_num,
      still: rec.poster || "",
    },
    rec.seriesName || ""
  );
}

function formatEpRuntime(duration, secs) {
  const n = Number(secs);
  if (Number.isFinite(n) && n > 0) {
    const m = Math.round(n / 60);
    if (m >= 60) {
      const hours = Math.floor(m / 60);
      const mins = m % 60;
      return mins ? `${hours}h ${mins}m` : `${hours}h`;
    }
    return `${m}m`;
  }
  const raw = String(duration || "").trim();
  const hm = raw.match(/^(\d+):(\d+)/);
  if (hm) {
    const hours = Number(hm[1]);
    const mins = Number(hm[2]);
    return hours >= 2 ? `${hours}h ${mins}m` : `${hours * 60 + mins}m`;
  }
  return raw;
}

function formatEpDate(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  const stamp = Date.parse(raw);
  if (!Number.isFinite(stamp)) {
    return raw;
  }
  return new Date(stamp).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function closeVodDetail() {
  const open = Boolean(vodDetail && (!vodDetail.hidden || vodDetail.classList.contains("is-open")));
  concealVodDetail();
  const wrapUp = () => {
    clearVodDetailBody();
    state.detailItem = null;
    state.detailKind = "";
    state.seasonId = "";
    if (isVodBrowseTab(state.tab)) {
      seriesPanel.hidden = true;
      seriesPanel.innerHTML = "";
    }
  };
  if (!open || motionOff()) {
    wrapUp();
    return;
  }
  window.setTimeout(wrapUp, 220);
}

function seriesMount() {
  if (vodDetail && vodDetailEps && (!vodDetail.hidden || vodDetail.classList.contains("is-open"))) {
    return vodDetailEps;
  }
  return seriesPanel;
}

function findVodItem(kind, id) {
  const key = kind === "series" ? "series_id" : "stream_id";
  if (state.detailItem && String(state.detailItem[key] || "") === String(id)) {
    return state.detailItem;
  }
  const home = state.vodHome;
  if (home) {
    if (home.featured && String(home.featured[key] || "") === String(id)) {
      return home.featured;
    }
    for (const group of home.groups || []) {
      const pools = [group.items || [], group.fullItems || []];
      for (const pool of pools) {
        const hit = pool.find((row) => String(row[key] || "") === String(id));
        if (hit) {
          return hit;
        }
      }
    }
  }
  const fromItems = (state.items || []).find((row) => String(row[key] || "") === String(id));
  if (fromItems) {
    return fromItems;
  }
  return findSearchItem(kind === "series" ? "series" : "movie", id);
}

function vodMetaLine(item, kind) {
  const bits = [kind === "series" ? "Show" : "Movie"];
  if (item?.year) {
    bits.push(String(item.year));
  }
  const rating = item?.tmdb_rating;
  if (rating != null && rating !== "") {
    const num = Number(rating);
    bits.push(`${Number.isFinite(num) ? num.toFixed(1) : rating} TMDB`);
  }
  const genres = item?.tmdb?.genres || [];
  if (genres.length) {
    bits.push(genres.slice(0, 3).join(" · "));
  }
  return bits.join(" · ");
}

function paintVodDetail(item, kind) {
  if (!vodDetail) {
    return;
  }
  if (vodDetailTitle) {
    vodDetailTitle.textContent = vodTitle(item) || "Untitled";
  }
  if (vodDetailMeta) {
    vodDetailMeta.textContent = vodMetaLine(item, kind);
  }
  if (vodDetailPlot) {
    vodDetailPlot.textContent = item.plot || "";
  }
  if (vodDetailBackdrop) {
    const bg = vodBackdrop(item);
    vodDetailBackdrop.style.backgroundImage = bg ? `url("${bg}")` : "";
  }
  paintVodPeople(item);
  paintVodDetailPlay();
}

function paintVodPeople(item) {
  if (!vodDetailPeople) {
    return;
  }
  const tmdb = (item && item.tmdb) || {};
  const genres = tmdb.genres || [];
  const directors = tmdb.directors || [];
  const writers = tmdb.writers || [];
  const creators = tmdb.creators || [];
  const cast = tmdb.cast || [];
  const countries = tmdb.countries || [];
  const runtime = tmdb.runtime;
  const magnumCast = String((item && item.cast) || "").trim();
  const facts = [];
  if (genres.length) {
    facts.push(`<div class="watch-vod-facts-row"><span>Genres</span><strong>${genres.map((name) => esc(name)).join(" · ")}</strong></div>`);
  }
  if (directors.length) {
    facts.push(`<div class="watch-vod-facts-row"><span>Director</span><strong>${directors.map((name) => esc(name)).join(", ")}</strong></div>`);
  }
  if (creators.length) {
    facts.push(`<div class="watch-vod-facts-row"><span>Created by</span><strong>${creators.map((name) => esc(name)).join(", ")}</strong></div>`);
  }
  if (writers.length) {
    facts.push(`<div class="watch-vod-facts-row"><span>Writers</span><strong>${writers.map((name) => esc(name)).join(", ")}</strong></div>`);
  }
  if (runtime) {
    facts.push(`<div class="watch-vod-facts-row"><span>Runtime</span><strong>${esc(formatEpRuntime("", runtime * 60))}</strong></div>`);
  }
  if (countries.length) {
    facts.push(`<div class="watch-vod-facts-row"><span>Country</span><strong>${countries.map((name) => esc(name)).join(", ")}</strong></div>`);
  }
  if (tmdb.status) {
    facts.push(`<div class="watch-vod-facts-row"><span>Status</span><strong>${esc(tmdb.status)}</strong></div>`);
  }
  let people = "";
  if (cast.length) {
    people = `<div class="watch-cast-row">${cast
      .map((person) => {
        const photo = person.photo
          ? `<img src="${esc(person.photo)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
          : `<span class="watch-cast-fallback">${esc((person.name || "?").slice(0, 1))}</span>`;
        return `<div class="watch-cast-card">
          <span class="watch-cast-photo">${photo}</span>
          <strong>${esc(person.name || "")}</strong>
          ${person.character ? `<small>${esc(person.character)}</small>` : ""}
        </div>`;
      })
      .join("")}</div>`;
  } else if (magnumCast) {
    people = `<p class="watch-cast-fallback-line">${esc(magnumCast)}</p>`;
  }
  if (!facts.length && !people) {
    vodDetailPeople.hidden = true;
    vodDetailPeople.innerHTML = "";
    return;
  }
  vodDetailPeople.hidden = false;
  vodDetailPeople.innerHTML = `${facts.length ? `<div class="watch-vod-facts">${facts.join("")}</div>` : ""}${people}`;
}

async function openVodDetail(item, kind) {
  if (!item || !vodDetail) {
    return;
  }
  state.detailItem = item;
  state.detailKind = kind;
  paintVodDetail(item, kind);
  showVodDetail();
  vodDetail.scrollTop = 0;
  if (kind === "series") {
    state.seasonId = "";
    if (vodDetailEps) {
      vodDetailEps.hidden = false;
      vodDetailEps.innerHTML = `<div class="empty-events">Loading seasons…</div>`;
    }
    try {
      const detail = await api(`/api/player/series/info?series_id=${encodeURIComponent(item.series_id)}`);
      if (vodItemId(state.detailItem, "series") !== String(item.series_id)) {
        return;
      }
      const info = detail.info || {};
      const tmdb = detail.tmdb || {};
      const merged = {
        ...item,
        display_name: tmdb.title || info.name || vodTitle(item),
        plot: tmdb.plot || info.plot || item.plot || "",
        year: tmdb.year || info.year || item.year,
        poster: tmdb.poster || item.poster,
        backdrop: tmdb.backdrop || item.backdrop,
        tmdb_rating: tmdb.rating != null ? tmdb.rating : item.tmdb_rating,
        cast: info.cast || item.cast || "",
        tmdb,
      };
      state.detailItem = merged;
      paintVodDetail(merged, "series");
      if (appPanel && appPanel.classList.contains("is-playing-vod")) {
        state.seriesDetail = detail;
        return;
      }
      renderSeries(detail, vodTitle(merged));
    } catch (error) {
      if (vodDetailEps) {
        vodDetailEps.innerHTML = `<div class="empty-events">${esc(error.message)}</div>`;
      }
      showBanner(error.message, "bad");
    }
    return;
  }
  if (vodDetailEps) {
    vodDetailEps.hidden = true;
    vodDetailEps.innerHTML = "";
  }
  seriesPanel.hidden = true;
  api(`/api/player/vod/info?vod_id=${encodeURIComponent(item.stream_id)}`)
    .then((data) => {
      if (vodItemId(state.detailItem, "movie") !== String(item.stream_id)) {
        return;
      }
      const info = data.info || {};
      const tmdb = data.tmdb || {};
      const merged = {
        ...item,
        display_name: tmdb.title || info.name || vodTitle(item),
        plot: tmdb.plot || info.plot || item.plot || "",
        year: tmdb.year || info.year || item.year,
        poster: tmdb.poster || item.poster,
        backdrop: tmdb.backdrop || item.backdrop,
        tmdb_rating: tmdb.rating != null ? tmdb.rating : item.tmdb_rating,
        duration: info.duration || item.duration,
        duration_secs: info.duration_secs || item.duration_secs,
        container_extension: info.container_extension || item.container_extension,
        cast: info.cast || item.cast || "",
        tmdb,
      };
      state.detailItem = merged;
      paintVodDetail(merged, "movie");
    })
    .catch(() => {});
}

async function playFromDetail() {
  const item = state.detailItem;
  const kind = state.detailKind;
  if (!item) {
    return;
  }
  presentVodPlayer();
  if (kind === "series") {
    const target = seriesPlayTarget() || (state.episodeQueue || [])[0];
    if (!target) {
      setPlayingVod(false);
      showVodDetail();
      showBanner("No episodes in this show yet.", "warn");
      return;
    }
    await playEpisode(target, vodTitle(item));
    return;
  }
  await playVod(item);
}

async function closeVodPlayer() {
  const detail = state.detailItem;
  const detailKind = state.detailKind || vodBrowseKind();
  const seriesDetail = state.seriesDetail;
  tearDownVodPlayer();
  await releaseSlot();
  if (detail) {
    state.detailItem = detail;
    state.detailKind = detailKind;
    paintVodDetail(detail, detailKind);
    if (detailKind === "series" && seriesDetail && vodDetailEps && !vodDetailEps.querySelector(".watch-ep-card, .watch-season-pills")) {
      state.seriesDetail = seriesDetail;
      renderSeries(seriesDetail, vodTitle(detail));
    }
    showVodDetail();
  }
}

function posterCard(item, kind) {
  const id = vodItemId(item, kind);
  const attr = kind === "series" ? "data-open-series" : "data-open-movie";
  const title = vodTitle(item);
  const art = vodPoster(item);
  const img = art
    ? `<img src="${esc(art)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
    : `<span class="watch-poster-fallback">${esc((title || "?").slice(0, 1))}</span>`;
  const year = item.year ? `<span class="watch-poster-year">${esc(item.year)}</span>` : "";
  return `<button type="button" class="watch-poster" ${attr}="${esc(id)}"><span class="watch-poster-art">${img}</span><span class="watch-poster-copy"><span class="watch-poster-name">${esc(title)}</span>${year}</span></button>`;
}

function vodHomeMount() {
  return itemList.querySelector(".watch-vod-home");
}

function vodRowEl(categoryId) {
  const value = String(categoryId);
  const safe = window.CSS && CSS.escape ? CSS.escape(value) : value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  return itemList.querySelector(`[data-vod-group="${safe}"]`);
}

function vodGroupSource(group) {
  const expanded = !!state.vodExpanded[group.category_id];
  return expanded && group.fullItems ? group.fullItems : group.items || [];
}

function vodRowMarkup(group, kind) {
  const items = vodGroupSource(group);
  if (!items.length) {
    return "";
  }
  const expanded = !!state.vodExpanded[group.category_id];
  const total = group.stream_count || items.length;
  const canExpand = total > (group.items || []).length;
  const count = total > items.length ? ` · ${esc(total)}` : "";
  const allBtn =
    canExpand || expanded
      ? `<button type="button" class="watch-row-all" data-vod-all="${esc(group.category_id)}">${
          expanded ? "Show less" : "View all"
        }${expanded ? "" : count}</button>`
      : "";
  return `<section class="watch-row${expanded ? " is-all" : ""}" data-vod-group="${esc(group.category_id)}">
    <header class="watch-row-head"><h3>${esc(group.category_name)}</h3>${allBtn}</header>
    <div class="watch-row-frame">
      <button type="button" class="watch-row-arrow is-prev" data-row-dir="-1" hidden aria-label="Previous">‹</button>
      <div class="watch-row-scroll">${items.map((item) => posterCard(item, kind)).join("")}</div>
      <button type="button" class="watch-row-arrow is-next" data-row-dir="1" hidden aria-label="Next">›</button>
    </div>
  </section>`;
}

function revealVodImages(root) {
  const scope = root || itemList;
  if (!scope || !scope.querySelectorAll) {
    return;
  }
  scope.querySelectorAll(".watch-poster-art img").forEach((img) => {
    const ready = () => img.classList.add("is-ready");
    if (img.complete && img.naturalWidth) {
      ready();
    } else {
      img.addEventListener("load", ready, { once: true });
      img.addEventListener("error", ready, { once: true });
    }
  });
}

function renderVodHome() {
  const home = state.vodHome;
  itemList.classList.remove("is-epg");
  if (watchStage) {
    watchStage.classList.remove("is-guide");
  }
  if (!home) {
    const kind = state.tab === "series" ? "series" : "movie";
    const cont = continueWatchingRow(kind);
    itemList.innerHTML = `<div class="watch-vod-home">${cont}<div class="empty-events">Loading the shelf…</div></div>`;
    if (cont) {
      bindVodRowArrows();
      revealVodImages();
    }
    return;
  }
  const kind = home.kind === "series" ? "series" : "movie";
  const feat = home.featured;
  let heroHtml = "";
  if (feat) {
    const bg = vodBackdrop(feat);
    const year = feat.year ? ` · ${esc(feat.year)}` : "";
    const kicker = kind === "series" ? "Show" : "Movie";
    const plot = String(feat.plot || "").trim();
    const attr = kind === "series" ? "data-open-series" : "data-open-movie";
    heroHtml = `<article class="watch-hero">
      <div class="watch-hero-bg"${bg ? ` style="background-image:url('${esc(bg)}')"` : ""}></div>
      <div class="watch-hero-copy">
        <p class="watch-hero-kicker">${kicker}${year}</p>
        <h2>${esc(vodTitle(feat))}</h2>
        ${plot ? `<p class="watch-hero-plot">${esc(plot)}</p>` : ""}
        <div class="watch-hero-actions">
          <button type="button" class="switch-btn" ${kind === "series" ? "data-play-series" : "data-play-movie"}="${esc(vodItemId(feat, kind))}">Play</button>
          <button type="button" class="watch-refresh-btn" ${attr}="${esc(vodItemId(feat, kind))}">More info</button>
        </div>
      </div>
    </article>`;
  }
  const rows = (home.groups || []).map((group) => vodRowMarkup(group, kind)).join("");
  itemList.innerHTML = `<div class="watch-vod-home">${heroHtml}${continueWatchingRow(kind)}${rows || `<div class="empty-events">Nothing in the guide yet.</div>`}</div>`;
  bindVodRowArrows();
  revealVodImages();
}

function updateVodRow(categoryId) {
  const home = state.vodHome;
  if (!home || !vodHomeMount()) {
    renderVodHome();
    return;
  }
  const group = (home.groups || []).find((row) => String(row.category_id) === String(categoryId));
  if (!group) {
    return;
  }
  const kind = home.kind === "series" ? "series" : "movie";
  const html = vodRowMarkup(group, kind);
  const existing = vodRowEl(categoryId);
  const y = itemList.scrollTop;
  if (!html) {
    if (existing) {
      existing.remove();
    }
    itemList.scrollTop = y;
    return;
  }
  if (!existing) {
    renderVodHome();
    return;
  }
  const railLeft = existing.classList.contains("is-all")
    ? 0
    : existing.querySelector(".watch-row-scroll")?.scrollLeft || 0;
  existing.insertAdjacentHTML("afterend", html);
  const next = existing.nextElementSibling;
  existing.remove();
  itemList.scrollTop = y;
  if (next && !next.classList.contains("is-all")) {
    const scroller = next.querySelector(".watch-row-scroll");
    if (scroller) {
      scroller.scrollLeft = railLeft;
    }
  }
  bindVodRowArrows(next);
  revealVodImages(next);
}

let vodArrowsBound = false;

function paintRowArrows(row) {
  if (!row) {
    return;
  }
  const scroller = row.querySelector(".watch-row-scroll");
  const prev = row.querySelector("[data-row-dir='-1']");
  const next = row.querySelector("[data-row-dir='1']");
  if (!scroller || row.classList.contains("is-all")) {
    if (prev) prev.hidden = true;
    if (next) next.hidden = true;
    return;
  }
  const max = scroller.scrollWidth - scroller.clientWidth - 8;
  const overflow = max > 8;
  if (prev) prev.hidden = !overflow || scroller.scrollLeft <= 8;
  if (next) next.hidden = !overflow || scroller.scrollLeft >= max;
}

function bindVodRowArrows(root) {
  if (!vodArrowsBound && itemList) {
    vodArrowsBound = true;
    itemList.addEventListener(
      "scroll",
      (event) => {
        const scroller = event.target;
        if (!(scroller instanceof HTMLElement) || !scroller.classList.contains("watch-row-scroll")) {
          return;
        }
        paintRowArrows(scroller.closest(".watch-row"));
      },
      { passive: true, capture: true }
    );
    window.addEventListener(
      "resize",
      () => {
        itemList.querySelectorAll(".watch-row").forEach(paintRowArrows);
      },
      { passive: true }
    );
  }
  const rows =
    root && root.classList && root.classList.contains("watch-row")
      ? [root]
      : [...(root || itemList).querySelectorAll(".watch-row")];
  rows.forEach((row) => {
    paintRowArrows(row);
    window.requestAnimationFrame(() => paintRowArrows(row));
  });
}

function scrollVodRow(button) {
  const frame = button.closest(".watch-row-frame");
  const scroller = frame && frame.querySelector(".watch-row-scroll");
  if (!scroller) {
    return;
  }
  const dir = Number(button.getAttribute("data-row-dir") || 1);
  const step = Math.max(scroller.clientWidth * 0.86, 420);
  scroller.scrollBy({ left: dir * step, behavior: "smooth" });
}

async function loadVodHome() {
  setVodBrowse(true);
  searchEl.placeholder = state.tab === "movies" ? "Search movies…" : "Search shows…";
  clearEpgLayout();
  categoryList.innerHTML = "";
  seriesPanel.hidden = true;
  state.vodHome = null;
  state.vodExpanded = {};
  const pending = (searchEl.value || "").trim().length >= 2;
  if (!pending) {
    renderVodHome();
  } else {
    itemList.innerHTML = `<div class="empty-events">Searching…</div>`;
  }
  const path = state.tab === "movies" ? "/api/player/vod/home" : "/api/player/series/home";
  const data = await api(path);
  if (!isVodBrowseTab(state.tab)) {
    return;
  }
  state.vodHome = data;
  if ((searchEl.value || "").trim().length >= 2) {
    return;
  }
  renderVodHome();
}

async function expandVodGroup(categoryId) {
  const home = state.vodHome;
  if (!home) {
    return;
  }
  const group = (home.groups || []).find((row) => String(row.category_id) === String(categoryId));
  if (!group) {
    return;
  }
  if (state.vodExpanded[categoryId]) {
    state.vodExpanded[categoryId] = false;
    updateVodRow(categoryId);
    return;
  }
  if (!group.fullItems) {
    const path =
      home.kind === "series"
        ? `/api/player/series/list?category_id=${encodeURIComponent(categoryId)}`
        : `/api/player/vod/streams?category_id=${encodeURIComponent(categoryId)}`;
    const data = await api(path);
    const rows = home.kind === "series" ? data.series || [] : data.streams || [];
    group.fullItems = rows.slice(0, VOD_VIEW_ALL_CAP);
  }
  state.vodExpanded[categoryId] = true;
  updateVodRow(categoryId);
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
  const liveGuide = state.tab === "live";
  itemList.classList.toggle("is-epg", liveGuide);
  if (watchStage) {
    watchStage.classList.toggle("is-guide", liveGuide);
  }
  const rows = visibleItems();
  if (!rows.length) {
    itemList.classList.remove("is-epg");
    itemList.innerHTML = `<div class="empty-events">${
      state.categoryId ? "Nothing in this group." : "Pick a group to see the TV guide."
    }</div>`;
    return;
  }
  if (liveGuide) {
    renderLiveEpg(rows);
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

function seasonIds(detail) {
  const ids = new Set();
  const episodes = (detail && detail.episodes) || {};
  Object.keys(episodes).forEach((id) => {
    if (id === "0" && !(episodes[id] || []).length) {
      return;
    }
    ids.add(String(id));
  });
  ((detail && detail.seasons) || []).forEach((row) => {
    const id = String((row && (row.season_number ?? row.season)) || "");
    if (!id || (id === "0" && !(episodes[id] || []).length)) {
      return;
    }
    ids.add(id);
  });
  return [...ids].sort((a, b) => Number(a) - Number(b));
}

function seasonLabel(detail, id) {
  const rows = (detail && detail.seasons) || [];
  const hit = rows.find((row) => String(row.season_number ?? row.season) === String(id));
  if (hit && hit.name) {
    return hit.name;
  }
  return String(id) === "0" ? "Specials" : `Season ${id}`;
}

function renderSeries(detail, seriesName, opts) {
  const mount = seriesMount();
  if (!detail) {
    mount.hidden = true;
    mount.innerHTML = "";
    if (mount !== seriesPanel) {
      seriesPanel.hidden = true;
      seriesPanel.innerHTML = "";
    }
    state.episodeQueue = [];
    return;
  }
  state.seriesDetail = detail;
  state.seriesName = seriesName || "";
  state.episodeQueue = flattenEpisodes(detail);
  const episodes = detail.episodes || {};
  const seasons = seasonIds(detail);
  if (!seasons.includes(String(state.seasonId))) {
    state.seasonId = seasons[0] || "";
  }
  const season = String(state.seasonId || seasons[0] || "");
  const list = episodes[season] || [];
  const pills = seasons
    .map((id) => {
      const here = String(id) === season ? " is-here" : "";
      return `<button type="button" class="watch-season-pill${here}" data-season="${esc(id)}">${esc(seasonLabel(detail, id))}</button>`;
    })
    .join("");
  const cards = list
    .map((ep) => {
      const info = ep.info || {};
      const still = ep.still || info.movie_image || "";
      const title = ep.title || info.name || `Episode ${ep.episode_num ?? ep.id}`;
      const plot = ep.plot || info.plot || "";
      const runtime = formatEpRuntime(ep.duration || info.duration, ep.duration_secs || info.duration_secs);
      const rating = ep.rating || info.rating || "";
      const date = formatEpDate(ep.release_date || info.release_date || info.air_date);
      const rec = seenRecord("ep", ep.id);
      const watched = Boolean(rec && rec.watched);
      const pct = rec && rec.dur > 0 ? Math.min(100, Math.round((rec.pos / rec.dur) * 100)) : 0;
      const img = still
        ? `<img src="${esc(still)}" alt="" referrerpolicy="no-referrer" loading="lazy" decoding="async" />`
        : `<span class="watch-ep-fallback"></span>`;
      const tick = watched
        ? `<span class="watch-ep-tick is-done" title="Watched">✓</span>`
        : pct > 0
          ? `<span class="watch-ep-tick is-mid" style="--pct:${pct}" title="${pct}% watched"></span>`
          : `<span class="watch-ep-tick" title="Unwatched"></span>`;
      const meta = [runtime, rating !== "" && rating != null ? `${Number(rating).toFixed ? Number(rating).toFixed(1) : rating}` : "", date]
        .filter(Boolean)
        .join(" · ");
      return `<button type="button" class="watch-ep-card${watched ? " is-watched" : ""}" data-episode="${esc(ep.id)}" data-ext="${esc(ep.container_extension || info.container_extension || "")}" data-title="${esc(title)}" data-plot="${esc(plot)}" data-duration="${esc(ep.duration || info.duration || "")}" data-duration-secs="${esc(ep.duration_secs || info.duration_secs || "")}" data-series-name="${esc(seriesName)}">
        <span class="watch-ep-still">${img}${tick}</span>
        <span class="watch-ep-kicker">Episode ${esc(ep.episode_num ?? "")}</span>
        <strong>${esc(title)}</strong>
        ${plot ? `<small class="watch-ep-plot">${esc(plot)}</small>` : ""}
        ${meta ? `<span class="watch-ep-meta">${esc(meta)}</span>` : ""}
      </button>`;
    })
    .join("");
  mount.hidden = false;
  const empty = list.length
    ? ""
    : `<div class="empty-events">This season is not on the panel yet.</div>`;
  mount.innerHTML = `<div class="watch-season-bar"><div class="watch-season-pills">${pills}</div></div>
  <div class="watch-ep-grid">${cards || empty}</div>`;
  if (mount !== seriesPanel) {
    seriesPanel.hidden = true;
    seriesPanel.innerHTML = "";
  }
  if (!opts?.skipEnrich) {
    enrichSeasonStills(detail, season).catch(() => {});
  }
  paintVodDetailPlay();
}

async function enrichSeasonStills(detail, season) {
  const seriesId = state.detailItem?.series_id || detail?.info?.id || detail?.info?.series_id;
  if (!seriesId || (!detail?.tmdb?.matched && !detail?.tmdb?.tmdb_id)) {
    return;
  }
  const data = await api(
    `/api/player/series/season?series_id=${encodeURIComponent(seriesId)}&season=${encodeURIComponent(season)}`
  );
  const extra = data.episodes || {};
  const list = (detail.episodes || {})[season] || [];
  let changed = false;
  list.forEach((ep) => {
    const hit = extra[String(ep.episode_num)];
    if (!hit) {
      return;
    }
    ep.info = ep.info || {};
    if (hit.still) {
      ep.still = hit.still;
      ep.info.movie_image = hit.still;
      changed = true;
    }
    if (hit.plot && !(ep.plot || ep.info.plot)) {
      ep.info.plot = hit.plot;
      changed = true;
    }
    if (hit.title && (!ep.title || /^episode\s+\d+/i.test(String(ep.title)))) {
      ep.title = hit.title;
      changed = true;
    }
    if (hit.rating != null && hit.rating !== "") {
      ep.info.rating = hit.rating;
      changed = true;
    }
    if (hit.air_date && !(ep.info.release_date || ep.release_date)) {
      ep.info.release_date = hit.air_date;
      changed = true;
    }
  });
  if (changed && String(state.seasonId) === String(season) && state.seriesDetail === detail) {
    renderSeries(detail, state.seriesName, { skipEnrich: true });
  }
}

function searchScope() {
  if (state.tab === "movies") {
    return "movie";
  }
  if (state.tab === "series") {
    return "series";
  }
  return "all";
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

function searchPosterRow(label, kind, items) {
  if (!items.length) {
    return "";
  }
  const expanded = items.length > 8;
  return `<section class="watch-row${expanded ? " is-all" : ""}" data-vod-group="search-${esc(kind)}">
    <header class="watch-row-head"><h3>${esc(label)}</h3><span class="watch-row-count">${esc(items.length)}</span></header>
    <div class="watch-row-frame">
      <button type="button" class="watch-row-arrow is-prev" data-row-dir="-1" hidden aria-label="Previous">‹</button>
      <div class="watch-row-scroll">${items.map((item) => posterCard(item, kind)).join("")}</div>
      <button type="button" class="watch-row-arrow is-next" data-row-dir="1" hidden aria-label="Next">›</button>
    </div>
  </section>`;
}

function searchHeroHtml(item, kind) {
  if (!item) {
    return "";
  }
  const bg = vodBackdrop(item);
  const year = item.year ? ` · ${esc(item.year)}` : "";
  const kicker = kind === "series" ? "Show" : "Movie";
  const plot = String(item.plot || "").trim();
  const attr = kind === "series" ? "data-open-series" : "data-open-movie";
  return `<article class="watch-hero">
    <div class="watch-hero-bg"${bg ? ` style="background-image:url('${esc(bg)}')"` : ""}></div>
    <div class="watch-hero-copy">
      <p class="watch-hero-kicker">Search · ${kicker}${year}</p>
      <h2>${esc(vodTitle(item))}</h2>
      ${plot ? `<p class="watch-hero-plot">${esc(plot)}</p>` : ""}
      <button type="button" class="switch-btn" ${attr}="${esc(vodItemId(item, kind))}">More info</button>
    </div>
  </article>`;
}

function renderSearchShelf() {
  clearEpgLayout();
  categoryList.innerHTML = "";
  itemList.classList.remove("is-epg");
  if (watchStage) {
    watchStage.classList.remove("is-guide");
  }
  const q = (searchEl.value || "").trim();
  if (q.length < 2) {
    if (isVodBrowseTab(state.tab) && state.vodHome) {
      renderVodHome();
      return;
    }
    const hint =
      state.tab === "movies"
        ? "Type at least two letters to search movies."
        : state.tab === "series"
          ? "Type at least two letters to search shows."
          : "Type at least two letters to search movies, shows, and live TV.";
    itemList.innerHTML = `<div class="watch-vod-home is-search"><div class="empty-events">${hint}</div></div>`;
    return;
  }
  const showLive = state.tab === "search";
  const showMovies = state.tab === "search" || state.tab === "movies";
  const showSeries = state.tab === "search" || state.tab === "series";
  const movies = showMovies ? state.searchHits.movies : [];
  const series = showSeries ? state.searchHits.series : [];
  const live = showLive ? state.searchHits.live : [];
  if (!movies.length && !series.length && !live.length) {
    itemList.innerHTML = `<div class="watch-vod-home is-search"><div class="empty-events">No matches for “${esc(q)}”.</div></div>`;
    return;
  }
  const featKind = movies.length ? "movie" : series.length ? "series" : "";
  const feat = featKind === "movie" ? movies[0] : featKind === "series" ? series[0] : null;
  const liveRow = live.length
    ? `<section class="watch-row" data-vod-group="search-live">
        <header class="watch-row-head"><h3>TV</h3><span class="watch-row-count">${esc(live.length)}</span></header>
        <div class="watch-row-frame">
          <button type="button" class="watch-row-arrow is-prev" data-row-dir="-1" hidden aria-label="Previous">‹</button>
          <div class="watch-row-scroll watch-search-live">${live
            .map((item, index) => searchRowLive(item, index))
            .join("")}</div>
          <button type="button" class="watch-row-arrow is-next" data-row-dir="1" hidden aria-label="Next">›</button>
        </div>
      </section>`
    : "";
  const rows = [
    searchPosterRow("Movies", "movie", movies),
    searchPosterRow("Shows", "series", series),
    liveRow,
  ].join("");
  itemList.innerHTML = `<div class="watch-vod-home is-search">${searchHeroHtml(feat, featKind)}${rows}</div>`;
  bindVodRowArrows();
  revealVodImages();
}

async function runSearch() {
  if (state.tab === "live") {
    return;
  }
  const q = (searchEl.value || "").trim();
  const tab = state.tab;
  const gen = ++searchGen;
  seriesPanel.hidden = true;
  if (q.length < 2) {
    state.searchHits = { live: [], movies: [], series: [] };
    renderSearchShelf();
    return;
  }
  if (!itemList.querySelector(".watch-vod-home.is-search")) {
    itemList.innerHTML = `<div class="empty-events">Searching…</div>`;
  }
  try {
    const kind = searchScope();
    const limit = kind === "all" ? 40 : 80;
    const data = await api(
      `/api/player/search?q=${encodeURIComponent(q)}&kind=${encodeURIComponent(kind)}&limit=${limit}`
    );
    if (gen !== searchGen || state.tab !== tab) {
      return;
    }
    state.searchHits = {
      live: data.live || [],
      movies: data.movies || [],
      series: data.series || [],
    };
    renderSearchShelf();
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
  }, 280);
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
  setVodBrowse(false);
  searchEl.placeholder = "Filter this group…";
  clearEpgLayout();
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
    itemList.innerHTML = `<div class="empty-events">Pick a group. The TV guide shows what’s on now and what’s next; click a channel or a programme to play.</div>`;
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
    if (me.must_change_password) {
      showPasswordChange();
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
    if (error.status !== 401) {
      loginError.hidden = false;
      loginError.textContent = error.message;
    }
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

function passwordRuleError(password, username) {
  if (!password || password.length < 8) {
    return "Password must be at least 8 characters.";
  }
  if (password.length > 128) {
    return "Password must be at most 128 characters.";
  }
  if (!/[a-z]/.test(password)) {
    return "Password must include a lowercase letter.";
  }
  if (!/[A-Z]/.test(password)) {
    return "Password must include an uppercase letter.";
  }
  if (!/[0-9]/.test(password)) {
    return "Password must include a number.";
  }
  if (!/[^A-Za-z0-9\s]/.test(password)) {
    return "Password must include a special character.";
  }
  if (username && password.toLowerCase() === username.toLowerCase()) {
    return "Password cannot be the same as your username.";
  }
  return "";
}

if (passwordForm) {
  passwordForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (passwordError) {
      passwordError.hidden = true;
    }
    const currentPassword = document.getElementById("pw-current").value;
    const newPassword = document.getElementById("pw-new").value;
    const confirmPassword = document.getElementById("pw-confirm").value;
    const username = (document.getElementById("login-user") && document.getElementById("login-user").value) || state.user || "";
    const localError =
      newPassword !== confirmPassword
        ? "New password and confirmation do not match."
        : passwordRuleError(newPassword, username);
    if (localError) {
      passwordError.hidden = false;
      passwordError.textContent = localError;
      return;
    }
    try {
      await api("/api/watch/password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
          confirm_password: confirmPassword,
        }),
      });
      passwordForm.reset();
      await boot();
    } catch (error) {
      passwordError.hidden = false;
      passwordError.textContent = error.message;
    }
  });
}

async function logoutWatch() {
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
}

if (pwLogoutBtn) {
  pwLogoutBtn.addEventListener("click", () => {
    logoutWatch().catch(() => {});
  });
}

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

document.getElementById("logout-btn").addEventListener("click", () => {
  logoutWatch().catch(() => {});
});

if (refreshPlaylistBtn) {
  refreshPlaylistBtn.addEventListener("click", () => {
    if (syncCooldownLeft("playlist") > 0) {
      paintRefreshButtons();
      return;
    }
    markSyncClicked("playlist");
    paintRefreshButtons(false);
    requestSync("playlist");
  });
}
if (refreshEpgBtn) {
  refreshEpgBtn.addEventListener("click", () => {
    if (syncCooldownLeft("epg") > 0) {
      paintRefreshButtons();
      return;
    }
    markSyncClicked("epg");
    paintRefreshButtons(false);
    requestSync("epg");
  });
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
      setVodBrowse(true);
      searchEl.placeholder = "Search movies, shows, and TV…";
      clearEpgLayout();
      categoryList.innerHTML = "";
      searchEl.focus();
      await runSearch();
      return;
    }
    try {
      if (isVodBrowseTab(state.tab)) {
        await loadVodHome();
        if ((searchEl.value || "").trim().length >= 2) {
          await runSearch();
        }
      } else {
        await loadCategories();
      }
    } catch (error) {
      showBanner(error.message, "bad");
    }
  });
});

categoryList.addEventListener("click", async (event) => {
  const kindBtn = event.target.closest("[data-search-kind]");
  if (kindBtn) {
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
      if (state.tab !== "live") {
        state.tab = "live";
        document.querySelectorAll("[data-tab]").forEach((btn) => {
          btn.classList.toggle("is-here", btn.getAttribute("data-tab") === "live");
        });
        setVodBrowse(false);
        loadCategories().catch(() => {});
      } else {
        itemList.querySelectorAll("[data-live]").forEach((el) => {
          el.classList.toggle("is-here", el.getAttribute("data-live") === String(id));
        });
      }
      playLive(item);
    }
    return;
  }
  const arrow = event.target.closest("[data-row-dir]");
  if (arrow) {
    scrollVodRow(arrow);
    return;
  }
  const viewAll = event.target.closest("[data-vod-all]");
  if (viewAll) {
    try {
      await expandVodGroup(viewAll.getAttribute("data-vod-all") || "");
    } catch (error) {
      showBanner(error.message, "bad");
    }
    return;
  }
  const continueMovie = event.target.closest("[data-continue-movie]");
  if (continueMovie) {
    playContinueMovie(continueMovie.getAttribute("data-continue-movie") || "").catch((error) => {
      showBanner(error.message, "bad");
    });
    return;
  }
  const continueEp = event.target.closest("[data-continue-ep]");
  if (continueEp) {
    playContinueEpisode(continueEp.getAttribute("data-continue-ep") || "").catch((error) => {
      showBanner(error.message, "bad");
    });
    return;
  }
  const playMovie = event.target.closest("[data-play-movie]");
  if (playMovie) {
    const id = playMovie.getAttribute("data-play-movie");
    const item = findVodItem("movie", id);
    if (item) {
      playVod(item).catch((error) => showBanner(error.message, "bad"));
    }
    return;
  }
  const playSeries = event.target.closest("[data-play-series]");
  if (playSeries) {
    const id = playSeries.getAttribute("data-play-series");
    const item = findVodItem("series", id) || { series_id: id, name: "" };
    openVodDetail(item, "series")
      .then(() => playFromDetail())
      .catch((error) => showBanner(error.message, "bad"));
    return;
  }
  const movieOpen = event.target.closest("[data-open-movie], [data-vod]");
  if (movieOpen) {
    const id = movieOpen.getAttribute("data-open-movie") || movieOpen.getAttribute("data-vod");
    const item = findVodItem("movie", id);
    if (item) {
      await openVodDetail(item, "movie");
    }
    return;
  }
  const seriesOpen = event.target.closest("[data-open-series], [data-series]");
  if (seriesOpen) {
    const id = seriesOpen.getAttribute("data-open-series") || seriesOpen.getAttribute("data-series");
    const item = findVodItem("series", id) || { series_id: id, name: "" };
    await openVodDetail(item, "series");
  }
});

async function onEpisodeClick(event) {
  const button = event.target.closest("[data-episode]");
  if (!button) {
    return;
  }
  const id = button.getAttribute("data-episode");
  const queued = (state.episodeQueue || []).find((row) => String(row.id) === String(id));
  await playEpisode(
    queued || {
      id,
      title: button.getAttribute("data-title"),
      container_extension: button.getAttribute("data-ext"),
      plot: button.getAttribute("data-plot"),
      duration: button.getAttribute("data-duration"),
      duration_secs: button.getAttribute("data-duration-secs"),
    },
    button.getAttribute("data-series-name")
  );
}

seriesPanel.addEventListener("click", onEpisodeClick);
if (vodDetailEps) {
  vodDetailEps.addEventListener("click", (event) => {
    const pill = event.target.closest("[data-season]");
    if (pill) {
      state.seasonId = pill.getAttribute("data-season") || "";
      if (state.seriesDetail) {
        renderSeries(state.seriesDetail, state.seriesName);
      }
      return;
    }
    onEpisodeClick(event);
  });
  vodDetailEps.addEventListener("change", (event) => {
    if (event.target && event.target.id === "vod-season-select") {
      state.seasonId = event.target.value || "";
      if (state.seriesDetail) {
        renderSeries(state.seriesDetail, state.seriesName);
      }
    }
  });
}
if (vodDetailPlay) {
  vodDetailPlay.addEventListener("click", () => {
    playFromDetail().catch((error) => showBanner(error.message, "bad"));
  });
}
if (vodDetailClose) {
  vodDetailClose.addEventListener("click", () => {
    closeVodDetail();
  });
}
if (vodPlayerClose) {
  vodPlayerClose.addEventListener("click", () => {
    closeVodPlayer().catch(() => {});
  });
}

searchEl.addEventListener("input", () => {
  if (state.tab === "search" || isVodBrowseTab(state.tab)) {
    queueSearch();
    return;
  }
  renderItems();
});

searchEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (state.tab === "search" || isVodBrowseTab(state.tab))) {
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

video.addEventListener("timeupdate", () => {
  paintVodRuntime();
  if (isVodPlay()) {
    markVodProgress();
  }
});
video.addEventListener("loadedmetadata", () => {
  captureStreamInfo();
  paintVodRuntime();
});
video.addEventListener("durationchange", paintVodRuntime);
video.addEventListener("resize", captureStreamInfo);
video.addEventListener("playing", () => {
  clearLiveStallTimer();
  captureStreamInfo();
  if (liveHold) {
    return;
  }
  showWatchSpinner(false);
  paintLiveBadge();
});
video.addEventListener("canplay", () => {
  if (!state.playingLiveId) {
    showWatchSpinner(false);
  }
});
video.addEventListener("pause", paintLiveBadge);
video.addEventListener("ended", () => {
  if (playing && state.playingLiveId && liveMpeg && liveTsUrl) {
    scheduleLiveReconnect(liveTsUrl, playGen);
    return;
  }
  markVodProgress();
  if (state.playingKind === "series") {
    const next = currentEpisodeOffset(1);
    if (next) {
      showUpNext(next);
    }
    paintVodPlayBtn();
    showVodChrome();
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
  if (state.playingLiveId) {
    showWatchSpinner(true);
    if (liveBadge && !liveBadge.hidden) {
      liveBadge.textContent = "BUFFERING";
      liveBadge.classList.add("is-behind");
    }
    return;
  }
  showVodWaitSpinner();
});
video.addEventListener("stalled", () => {
  if (playing && state.playingLiveId && !liveHold) {
    showWatchSpinner(true);
  }
});
video.addEventListener("error", () => {
  if (vodSeeking || state.playingLiveId || !playing) {
    return;
  }
  if (!video.currentSrc) {
    return;
  }
  const code = video.error && video.error.code;
  if (code === 4) {
    vodSeekOffset = 0;
    showBanner("Playback failed. Click the title again to restart.", "bad");
  }
});

if (vodSeekRange) {
  vodSeekRange.addEventListener("pointerdown", () => {
    vodScrubbing = true;
    showVodChrome();
  });
  vodSeekRange.addEventListener("input", () => {
    vodScrubbing = true;
    paintVodSeek(rangeToVodTime());
    showVodChrome();
  });
  vodSeekRange.addEventListener("change", () => {
    vodScrubbing = false;
    seekVod(rangeToVodTime()).catch(() => {});
    showVodChrome();
  });
  vodSeekRange.addEventListener("pointerup", () => {
    vodScrubbing = false;
    showVodChrome();
  });
}
if (vodSeekBack) {
  vodSeekBack.addEventListener("click", () => {
    seekVod(vodClock() - 10).catch(() => {});
    showVodChrome();
  });
}
if (vodSeekFwd) {
  vodSeekFwd.addEventListener("click", () => {
    seekVod(vodClock() + 30).catch(() => {});
    showVodChrome();
  });
}
if (vodRestartBtn) {
  vodRestartBtn.addEventListener("click", () => {
    seekVod(0).catch(() => {});
    showVodChrome();
  });
}
if (vodSkipIntro) {
  vodSkipIntro.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    seekVod(vodClock() + SKIP_INTRO_SEC).catch(() => {});
    showVodChrome();
  });
}
if (vodRateBtn) {
  vodRateBtn.addEventListener("click", () => {
    cycleVodRate();
  });
}
if (vodEpPrev) {
  vodEpPrev.addEventListener("click", () => {
    goAdjacentEpisode(-1).catch(() => {});
    showVodChrome();
  });
}
if (vodEpNext) {
  vodEpNext.addEventListener("click", () => {
    goAdjacentEpisode(1).catch(() => {});
    showVodChrome();
  });
}
if (vodUpNextPlay) {
  vodUpNextPlay.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    goAdjacentEpisode(1).catch(() => {});
  });
}
if (vodUpNextCancel) {
  vodUpNextCancel.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    hideUpNext();
    showVodChrome();
  });
}
if (vodPlayBtn) {
  vodPlayBtn.addEventListener("click", () => {
    toggleVodPlay();
  });
}
if (vodMuteBtn) {
  vodMuteBtn.addEventListener("click", () => {
    toggleVodMute();
  });
}
if (vodVol) {
  vodVol.addEventListener("input", () => {
    const level = Number(vodVol.value);
    if (!Number.isFinite(level)) {
      return;
    }
    if (vodHoldActive) {
      return;
    }
    video.volume = Math.max(0, Math.min(1, level));
    video.muted = video.volume === 0;
    if (!video.muted) {
      localStorage.setItem("watch_volume", String(video.volume));
    }
    paintVodMuteBtn();
    showVodChrome();
  });
}
if (vodFsBtn) {
  vodFsBtn.addEventListener("click", () => {
    toggleVodFs();
    showVodChrome();
  });
}
if (vodHit) {
  vodHit.addEventListener("click", (event) => {
    event.preventDefault();
    toggleVodPlay();
  });
  vodHit.addEventListener("dblclick", (event) => {
    event.preventDefault();
    toggleVodFs();
  });
}
if (videoWrap) {
  videoWrap.addEventListener("mousemove", () => {
    if (vodUsesOverlay()) {
      showVodChrome();
    }
  });
  videoWrap.addEventListener("pointerdown", () => {
    if (vodUsesOverlay()) {
      showVodChrome();
    }
  });
}
video.addEventListener("play", () => {
  paintVodPlayBtn();
  if (!upNextGoing) {
    hideUpNext();
  }
  if (vodUsesOverlay()) {
    showVodChrome();
  }
});
video.addEventListener("pause", () => {
  paintVodPlayBtn();
  if (vodUsesOverlay()) {
    showVodChrome();
  }
});
video.addEventListener("volumechange", paintVodMuteBtn);
document.addEventListener("fullscreenchange", syncVodFsClass);
document.addEventListener("webkitfullscreenchange", syncVodFsClass);
document.addEventListener("keydown", (event) => {
  if (!vodUsesOverlay()) {
    return;
  }
  const target = event.target;
  if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
    return;
  }
  if (event.key === " " || event.code === "Space") {
    event.preventDefault();
    toggleVodPlay();
  } else if (event.key === "f" || event.key === "F") {
    event.preventDefault();
    toggleVodFs();
  } else if (event.key === "m" || event.key === "M") {
    event.preventDefault();
    toggleVodMute();
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    seekVod(vodClock() + (event.shiftKey ? 10 : 30)).catch(() => {});
    showVodChrome();
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    seekVod(vodClock() - (event.shiftKey ? 5 : 10)).catch(() => {});
    showVodChrome();
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    video.volume = Math.min(1, (Number(video.volume) || 0) + 0.05);
    video.muted = false;
    localStorage.setItem("watch_volume", String(video.volume));
    if (vodVol) {
      vodVol.value = String(video.volume);
    }
    paintVodMuteBtn();
    showVodChrome();
  } else if (event.key === "ArrowDown") {
    event.preventDefault();
    video.volume = Math.max(0, (Number(video.volume) || 0) - 0.05);
    video.muted = video.volume === 0;
    localStorage.setItem("watch_volume", String(video.volume));
    if (vodVol) {
      vodVol.value = String(video.muted ? 0 : video.volume);
    }
    paintVodMuteBtn();
    showVodChrome();
  } else if (event.key === "Home") {
    event.preventDefault();
    seekVod(0).catch(() => {});
    showVodChrome();
  } else if (event.key === "s" || event.key === "S") {
    if (vodSkipIntro && !vodSkipIntro.hidden) {
      event.preventDefault();
      seekVod(vodClock() + SKIP_INTRO_SEC).catch(() => {});
      showVodChrome();
    }
  } else if (event.key === ">" || event.key === "." || event.key === "<" || event.key === ",") {
    event.preventDefault();
    cycleVodRate();
  } else if (event.key === "n" || event.key === "N") {
    event.preventDefault();
    goAdjacentEpisode(1).catch(() => {});
    showVodChrome();
  } else if (event.key === "p" || event.key === "P") {
    event.preventDefault();
    goAdjacentEpisode(-1).catch(() => {});
    showVodChrome();
  } else if (event.key === "Escape" && upNextOpen()) {
    hideUpNext();
    showVodChrome();
  }
});

window.addEventListener("pagehide", () => {
  lastSeenWrite = 0;
  markVodProgress();
  if (playing) {
    navigator.sendBeacon?.(
      "/api/player/slot/release",
      new Blob([JSON.stringify({ play_id: playId() })], { type: "application/json" })
    );
  }
});

boot();
