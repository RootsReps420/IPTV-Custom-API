/* TV casting for /watch.
 *
 * Chromecast (Chrome desktop / Android): the TV fetches
 * /api/player/media/...mp4?cast=1 itself with the signed `k` token. VOD is the
 * normal fMP4 remux (HEVC copied as-is); live is an ffmpeg TS->fMP4 copy
 * because Cast receivers cannot play raw MPEG-TS.
 *
 * AirPlay (Safari / iPhone / iPad): the <video> element itself plays on the
 * TV. Live is switched to native HLS because MSE cannot be AirPlayed.
 *
 * Loaded before watch.js. Everything here runs at call time or after
 * DOMContentLoaded, when watch.js globals (video, state, playSources, ...) exist.
 */

const CAST_SDK_URL = "https://www.gstatic.com/cv/js/sender/v1/cast_sender.js?loadCastFramework=1";
const CAST_LIVE_RETRIES = 3;

const tvCast = {
  sdk: false,
  devices: false,
  session: null,
  player: null,
  controller: null,
  loadId: 0,
  loadedKind: "",
  loadedId: "",
  pending: false,
  lastClock: 0,
  liveRetries: 0,
  liveRetryTimer: 0,
  playingSince: 0,
  airplayAvailable: false,
  airplayWireless: false,
};

function castOn() {
  return Boolean(tvCast.session);
}

function airplayOn() {
  return tvCast.airplayWireless;
}

function castTime() {
  return Number(tvCast.player?.currentTime) || 0;
}

function castDuration() {
  return Number(tvCast.player?.duration) || 0;
}

function castPaused() {
  const p = tvCast.player;
  if (!p || !p.isMediaLoaded) {
    return true;
  }
  return Boolean(p.isPaused);
}

function castMuted() {
  return Boolean(tvCast.player?.isMuted);
}

function castVolume() {
  const level = Number(tvCast.player?.volumeLevel);
  return Number.isFinite(level) ? level : 1;
}

function castTogglePlay() {
  if (tvCast.controller && tvCast.player?.isMediaLoaded) {
    tvCast.controller.playOrPause();
  }
}

function castToggleMute() {
  if (tvCast.controller) {
    tvCast.controller.muteOrUnmute();
  }
}

function castSetVolume(level) {
  if (!tvCast.controller || !tvCast.player) {
    return;
  }
  const next = Math.max(0, Math.min(1, Number(level) || 0));
  if (tvCast.player.isMuted && next > 0) {
    tvCast.controller.muteOrUnmute();
  }
  tvCast.player.volumeLevel = next;
  tvCast.controller.setVolumeLevel();
}

function castDeviceName() {
  try {
    return tvCast.session?.getCastDevice()?.friendlyName || "your TV";
  } catch {
    return "your TV";
  }
}

function castMediaUrl(kind, streamId) {
  const url = new URL(mediaUrl(kind, streamId, "mp4"), window.location.origin);
  url.searchParams.set("cast", "1");
  url.searchParams.delete("cb");
  if (kind !== "live") {
    // Chromecast with Google TV / Ultra decode HEVC; the VPS cannot transcode 4K live.
    url.searchParams.set("vc", "h264,hevc");
  }
  return url.href;
}

function castArtwork(kind, item) {
  const raw = kind === "live"
    ? item?.stream_icon
    : vodPoster(item) || item?.still || item?.movie_image || item?.info?.movie_image;
  const art = String(raw || "").trim();
  return /^https:\/\//i.test(art) ? art : "";
}

function castErrorText(kind) {
  if (kind === "live") {
    return "The TV could not play this channel. Try another channel or stop casting.";
  }
  return "The TV could not play this title. Older Chromecasts cannot play 4K HEVC films.";
}

function clearCastLiveRetry() {
  if (tvCast.liveRetryTimer) {
    window.clearTimeout(tvCast.liveRetryTimer);
    tvCast.liveRetryTimer = 0;
  }
}

async function castPlay(kind, streamId, gen) {
  const session = tvCast.session;
  if (!session || !window.chrome?.cast?.media) {
    throw new Error("Not connected to a TV.");
  }
  if (!state.mediaToken) {
    throw new Error("Casting needs a fresh sign-in. Reload the page and try again.");
  }
  clearCastLiveRetry();
  const live = kind === "live";
  const item = state.playingItem || {};
  const media = chrome.cast.media;
  const info = new media.MediaInfo(castMediaUrl(kind, streamId), "video/mp4");
  info.streamType = live ? media.StreamType.LIVE : media.StreamType.BUFFERED;
  if (!live) {
    const total = vodLength();
    if (total > 0) {
      info.duration = Math.max(1, total - vodSeekOffset);
    }
  }
  const meta = new media.GenericMediaMetadata();
  meta.title = String(nowTitle?.textContent || vodTitle(item) || "R").slice(0, 200);
  const subtitle = live ? String(nowEpg?.textContent || "").trim() : "";
  if (subtitle) {
    meta.subtitle = subtitle.slice(0, 200);
  }
  const art = castArtwork(kind, item);
  if (art) {
    meta.images = [new chrome.cast.Image(art)];
  }
  info.metadata = meta;
  const request = new media.LoadRequest(info);
  request.autoplay = true;
  request.currentTime = 0;

  const loadId = ++tvCast.loadId;
  tvCast.loadedKind = kind;
  tvCast.loadedId = String(streamId);
  tvCast.lastClock = vodSeekOffset;
  tvCast.playingSince = 0;
  tvCast.pending = true;
  showWatchSpinner(true);
  paintCastUi();
  // Let the tab's own Magnum socket close first; Magnum counts a second pull as another line.
  await waitMs(live ? 700 : 300);
  if ((gen != null && gen !== playGen) || loadId !== tvCast.loadId || session !== tvCast.session) {
    return;
  }
  let failure = null;
  try {
    failure = await session.loadMedia(request);
  } catch (error) {
    failure = error || "load_failed";
  }
  if (loadId !== tvCast.loadId || session !== tvCast.session) {
    return;
  }
  tvCast.pending = false;
  if (failure) {
    tvCast.loadedKind = "";
    tvCast.loadedId = "";
    showWatchSpinner(false);
    throw new Error(castErrorText(kind));
  }
  paintCastUi();
  paintVodRuntime();
}

function castStopMedia() {
  clearCastLiveRetry();
  if (!tvCast.session) {
    return;
  }
  tvCast.loadId += 1;
  tvCast.loadedKind = "";
  tvCast.loadedId = "";
  tvCast.pending = false;
  let mediaSession = null;
  try {
    mediaSession = tvCast.session.getMediaSession();
  } catch {
    mediaSession = null;
  }
  if (mediaSession && window.chrome?.cast?.media) {
    try {
      mediaSession.stop(new chrome.cast.media.StopRequest(), () => {}, () => {});
    } catch {
      /* ignore */
    }
  }
}

function playingStreamId() {
  const item = state.playingItem;
  if (!item) {
    return "";
  }
  if (state.playingKind === "live") {
    return String(state.playingLiveId || item.stream_id || "");
  }
  return String(item.stream_id || item.id || "");
}

function restartCurrent(localClock) {
  const kind = state.playingKind;
  const id = playingStreamId();
  if (!playing || !id || !kind) {
    return;
  }
  if (kind === "live") {
    playLive(state.playingItem);
    return;
  }
  if (kind !== "movie" && kind !== "series") {
    return;
  }
  vodSeekOffset = Math.max(0, Math.floor(localClock || 0));
  paintVodSeek(vodSeekOffset);
  const ext = String(state.playingItem.container_extension || "mp4").replace(/^\./, "");
  const gen = ++playGen;
  playSources(kind, id, vodExtensions(ext), gen).catch((error) => {
    if (gen === playGen) {
      showBanner(error.message, "bad");
    }
  });
}

function onCastSessionStart(session) {
  if (tvCast.session === session) {
    return;
  }
  // Read the tab's own position before vodClock() switches to the TV clock.
  const localClock = isVodPlay() ? vodClock() : 0;
  tvCast.session = session;
  tvCast.liveRetries = 0;
  showBanner("");
  paintCastUi();
  setPlayerChrome();
  paintBufferButtons();
  if (playing && state.playingItem) {
    restartCurrent(localClock);
  }
}

function onCastSessionEnd() {
  if (!tvCast.session) {
    return;
  }
  const clock = isVodPlay() ? Math.max(tvCast.lastClock, vodSeekOffset) : 0;
  clearCastLiveRetry();
  tvCast.session = null;
  tvCast.loadId += 1;
  tvCast.loadedKind = "";
  tvCast.loadedId = "";
  tvCast.pending = false;
  showWatchSpinner(false);
  paintCastUi();
  setPlayerChrome();
  paintBufferButtons();
  if (playing && state.playingItem) {
    restartCurrent(clock);
  }
}

function onCastFinished() {
  if (tvCast.loadedKind === "live") {
    retryCastLive();
    return;
  }
  if (!isVodPlay()) {
    return;
  }
  lastSeenWrite = 0;
  markVodProgress();
  paintVodPlayBtn();
  if (state.playingKind === "series") {
    const next = currentEpisodeOffset(1);
    if (next) {
      showUpNext(next);
    }
    showVodChrome();
  }
}

function retryCastLive() {
  const id = tvCast.loadedId;
  if (!castOn() || !id || state.playingKind !== "live" || tvCast.liveRetryTimer) {
    return;
  }
  if (tvCast.liveRetries >= CAST_LIVE_RETRIES) {
    showWatchSpinner(false);
    showBanner("The live stream on the TV dropped. Click the channel again.", "bad");
    return;
  }
  tvCast.liveRetries += 1;
  const gen = playGen;
  showWatchSpinner(true);
  tvCast.liveRetryTimer = window.setTimeout(() => {
    tvCast.liveRetryTimer = 0;
    if (!castOn() || gen !== playGen || state.playingKind !== "live" || playingStreamId() !== id) {
      return;
    }
    castPlay("live", id, gen).catch((error) => {
      if (gen === playGen) {
        showBanner(error.message, "bad");
      }
    });
  }, 1500 * tvCast.liveRetries);
}

function onCastPlayerState() {
  if (!castOn()) {
    return;
  }
  const states = chrome.cast.media.PlayerState;
  const now = tvCast.player.playerState;
  if (now === states.PLAYING || now === states.PAUSED) {
    showWatchSpinner(false);
    if (now === states.PLAYING && !tvCast.playingSince) {
      tvCast.playingSince = performance.now();
    }
  } else if (now === states.BUFFERING) {
    showWatchSpinner(true);
  } else if (now === states.IDLE && tvCast.loadedKind) {
    let reason = "";
    try {
      reason = tvCast.session.getMediaSession()?.idleReason || "";
    } catch {
      reason = "";
    }
    const reasons = chrome.cast.media.IdleReason;
    if (reason === reasons.FINISHED) {
      showWatchSpinner(false);
      onCastFinished();
    } else if (reason === reasons.ERROR) {
      showWatchSpinner(false);
      if (tvCast.loadedKind === "live" && tvCast.playingSince) {
        retryCastLive();
      } else {
        showBanner(castErrorText(tvCast.loadedKind), "bad");
      }
    }
  }
  paintVodPlayBtn();
}

function onCastTime() {
  // While a seek reloads the TV, its clock still belongs to the old media.
  if (!castOn() || !tvCast.loadedKind || tvCast.pending || vodSeeking) {
    return;
  }
  const t = castTime();
  if (t > 0 && isVodPlay()) {
    tvCast.lastClock = vodSeekOffset + t;
  }
  if (tvCast.playingSince && performance.now() - tvCast.playingSince > 30000) {
    tvCast.liveRetries = 0;
  }
  paintVodRuntime();
  if (isVodPlay()) {
    markVodProgress();
  }
}

function onCastVolume() {
  if (!castOn()) {
    return;
  }
  if (vodVol) {
    vodVol.value = String(castMuted() ? 0 : castVolume());
  }
  paintVodMuteBtn();
}

function initCastSdk() {
  const framework = window.cast?.framework;
  if (!framework || !window.chrome?.cast) {
    return;
  }
  const context = framework.CastContext.getInstance();
  context.setOptions({
    receiverApplicationId: chrome.cast.media.DEFAULT_MEDIA_RECEIVER_APP_ID,
    autoJoinPolicy: chrome.cast.AutoJoinPolicy.ORIGIN_SCOPED,
  });
  tvCast.player = new framework.RemotePlayer();
  tvCast.controller = new framework.RemotePlayerController(tvCast.player);
  const events = framework.RemotePlayerEventType;
  tvCast.controller.addEventListener(events.PLAYER_STATE_CHANGED, onCastPlayerState);
  tvCast.controller.addEventListener(events.IS_PAUSED_CHANGED, () => {
    paintVodPlayBtn();
    showVodChrome();
  });
  tvCast.controller.addEventListener(events.CURRENT_TIME_CHANGED, onCastTime);
  tvCast.controller.addEventListener(events.IS_MUTED_CHANGED, onCastVolume);
  tvCast.controller.addEventListener(events.VOLUME_LEVEL_CHANGED, onCastVolume);
  context.addEventListener(framework.CastContextEventType.CAST_STATE_CHANGED, (event) => {
    tvCast.devices = event.castState !== framework.CastState.NO_DEVICES_AVAILABLE;
    paintCastUi();
  });
  context.addEventListener(framework.CastContextEventType.SESSION_STATE_CHANGED, (event) => {
    const S = framework.SessionState;
    if (event.sessionState === S.SESSION_STARTED || event.sessionState === S.SESSION_RESUMED) {
      const session = context.getCurrentSession();
      if (session) {
        onCastSessionStart(session);
      }
    } else if (event.sessionState === S.SESSION_ENDED) {
      onCastSessionEnd();
    }
  });
  tvCast.sdk = true;
  tvCast.devices = context.getCastState() !== framework.CastState.NO_DEVICES_AVAILABLE;
  const existing = context.getCurrentSession();
  if (existing) {
    onCastSessionStart(existing);
  }
  paintCastUi();
}

function loadCastSdk() {
  const ua = navigator.userAgent || "";
  // Cast Web Sender only works in Chrome (desktop and Android). Skip Safari/iOS/Firefox.
  if (!window.chrome || /iPhone|iPad|iPod|CriOS|FxiOS|Firefox/i.test(ua) || isAppleHlsClient()) {
    return;
  }
  window.__onGCastApiAvailable = (available) => {
    if (available) {
      try {
        initCastSdk();
      } catch {
        /* Cast unavailable; AirPlay / local playback unaffected */
      }
    }
  };
  const script = document.createElement("script");
  script.src = CAST_SDK_URL;
  script.async = true;
  document.head.appendChild(script);
}

function onAirplayWirelessChange() {
  const on = Boolean(video.webkitCurrentPlaybackTargetIsWireless);
  if (on === tvCast.airplayWireless) {
    return;
  }
  tvCast.airplayWireless = on;
  paintCastUi();
  // Live on desktop Safari is MSE; swap to native HLS so the TV can pull it, and back afterwards.
  if (playing && state.playingKind === "live" && state.playingItem && canPlayMpegTs()) {
    playLive(state.playingItem);
  }
}

function initAirplay() {
  if (!window.WebKitPlaybackTargetAvailabilityEvent || !video.webkitShowPlaybackTargetPicker) {
    return;
  }
  video.setAttribute("x-webkit-airplay", "allow");
  video.addEventListener("webkitplaybacktargetavailabilitychanged", (event) => {
    tvCast.airplayAvailable = event.availability === "available";
    paintCastUi();
  });
  video.addEventListener("webkitcurrentplaybacktargetiswirelesschanged", onAirplayWirelessChange);
}

function paintCastUi() {
  const button = document.getElementById("cast-btn");
  const overlay = document.getElementById("cast-overlay");
  const name = document.getElementById("cast-overlay-name");
  const casting = castOn();
  const chromecast = tvCast.sdk && (tvCast.devices || casting);
  const airplay = tvCast.airplayAvailable || tvCast.airplayWireless;
  if (button) {
    button.hidden = !(chromecast || airplay);
    const active = casting || tvCast.airplayWireless;
    button.classList.toggle("is-on", active);
    let label = "Cast to TV";
    if (casting) {
      label = `Stop casting to ${castDeviceName()}`;
    } else if (!chromecast && airplay) {
      label = tvCast.airplayWireless ? "AirPlay devices" : "AirPlay to TV";
    }
    button.title = label;
    button.setAttribute("aria-label", label);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  }
  if (overlay) {
    overlay.hidden = !casting;
  }
  if (name) {
    name.textContent = castDeviceName();
  }
  if (videoWrap) {
    videoWrap.classList.toggle("is-casting", casting);
  }
}

function onCastButton() {
  if (tvCast.sdk) {
    const context = window.cast.framework.CastContext.getInstance();
    if (tvCast.session) {
      context.endCurrentSession(true);
      return;
    }
    context.requestSession().catch(() => {
      /* closed the device picker */
    });
    return;
  }
  if (video.webkitShowPlaybackTargetPicker) {
    video.webkitShowPlaybackTargetPicker();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const button = document.getElementById("cast-btn");
  if (button) {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      onCastButton();
    });
  }
  initAirplay();
  loadCastSdk();
  paintCastUi();
});
