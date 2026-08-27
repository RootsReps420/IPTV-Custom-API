# Portal Player (Android)

Sideloadable IPTV app for Shield, Google TV Streamer, Fire TV, phones, and tablets. You add an **Xtream** login or an **M3U URL** on the device. Magnum / panel passwords are **not** compiled into the APK.

Live MPEG-TS uses ExoPlayer with the same reconnect policy as Watch: network/EOF errors, frozen clock (~4s), stall buffering (4.5s), 0.97× when the cushion thins, at most 6 reconnects. Video goes **straight to the portal**, not through the VPS.

## Build

Install [Android Studio](https://developer.android.com/studio) (JDK 17 is bundled). Open the `android/` folder as a project, or from this directory:

```powershell
cd android
.\gradlew.bat assembleDebug
```

Debug APK: `android/app/build/outputs/apk/debug/app-debug.apk`

Release (sideload this one):

```powershell
.\gradlew.bat assembleRelease
```

Create a keystore **once** (not in git):

```powershell
keytool -genkey -v -keystore "$env:USERPROFILE\portal-player.jks" -keyalg RSA -keysize 2048 -validity 10000 -alias portal
```

Then either use Android Studio **Generate Signed Bundle / APK**, or add `android/keystore.properties` (gitignored if you keep the JKS out of the repo) and wire `signingConfigs` later. Until then, `assembleRelease` uses the debug key unless you configure signing in Studio.

## Sideload with Downloader

1. Host the **signed** APK on HTTPS (GitHub Release, or a static file on your own server). Do not put panel credentials in that URL.
2. On a phone/PC, open [Downloader](https://aftvnews.com/downloader/) and create a code that points at the APK URL.
3. On the TV: install **Downloader** from Amazon (Fire TV) or Play Store → allow **Install unknown apps** for Downloader → enter the code → install.

Shield and Google TV Streamer also accept the APK via USB/`adb install`. Fire Stick is the usual Downloader path.

Bump `versionCode` in `app/build.gradle.kts` for each new APK. Downloader does not auto-update; share a new code or the same URL with a new file.

## Playlists

- **Xtream:** server URL (`http://host` or `http://host:port`), username, password. Live, movies, and series come from `player_api.php`. Live plays `/live/user/pass/id.ts`.
- **M3U:** playlist URL, optional XMLTV EPG URL (or `url-tvg` in the M3U header).

Several playlists can be stored. They sit in EncryptedSharedPreferences on the device.

Portals often use HTTP or invalid TLS. The app allows cleartext HTTP and a permissive trust manager for those hosts — same class of compromise as other IPTV APKs. Do not enter banking passwords here.

## Devices

`minSdk 26` (Android 8). One APK registers both `LAUNCHER` (phone) and `LEANBACK_LAUNCHER` (TV row). D-pad works; touch works. Optimize testing on Shield / Streamer; Fire Stick is supported but weaker.
