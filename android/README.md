# Portal Player (Android)

Sideloadable IPTV app for Shield, Google TV Streamer, Fire TV, phones, and tablets. You add an **Xtream** login or an **M3U URL** on the device. Magnum / panel passwords are **not** compiled into the APK.

The browse UI matches Watch: left rail (TV / Movies / Shows / Search), groups, channel list, preview player with now/next EPG. Live MPEG-TS uses ExoPlayer with Watch’s reconnect policy and Small / Medium / Large buffer profiles (0.97× if the cushion thins). Video goes **straight to the portal**, not through the VPS.

Current sideload build: **0.4.0** (`versionCode` 4).

## Build

Install [Android Studio](https://developer.android.com/studio) (JDK 17 is bundled). Open the `android/` folder as a project, or from this directory:

```powershell
cd android
.\gradlew.bat assembleDebug
```

Debug APK: `android/app/build/outputs/apk/debug/app-debug.apk` (also copied to `android/PortalPlayer-debug.apk` after a local build). Application id is `com.iptvmonitor.player.debug`.

Release (sideload this one):

```powershell
.\gradlew.bat assembleRelease
```

Create a keystore **once** (not in git):

```powershell
keytool -genkey -v -keystore "$env:USERPROFILE\portal-player.jks" -keyalg RSA -keysize 2048 -validity 10000 -alias portal
```

Then either use Android Studio **Generate Signed Bundle / APK**, or add `android/keystore.properties` (gitignored if you keep the JKS out of the repo) and wire `signingConfigs` later. Until then, `assembleRelease` uses the debug key unless you configure signing in Studio.

## Sideload on Shield

Unknown sources: Settings → Device Preferences → Security & restrictions → Unknown sources → allow for **Downloader** (or Files).

**USB:** copy `PortalPlayer-debug.apk` onto a stick, open it with Files / Downloader on the Shield.

**PC + adb** (Shield and this machine on the same network, USB debugging on):

```powershell
adb connect SHIELD_IP:5555
adb install -r android\PortalPlayer-debug.apk
```

**Downloader without a phone:** on the Shield, open Downloader and paste an HTTPS URL to the APK. A short code is optional (created in a browser at aftvnews); the app accepts a full URL.

Do not put panel credentials in that URL. Bump `versionCode` in `app/build.gradle.kts` for each new APK.

## Playlists

- **Xtream:** server URL (`http://host` or `http://host:port`), username, password. Live, movies, and series come from `player_api.php`. Live plays `/live/user/pass/id.ts`.
- **M3U:** playlist URL, optional XMLTV EPG URL (or `url-tvg` in the M3U header).

Several playlists can be stored. They sit in EncryptedSharedPreferences on the device.

In **Settings** you can pin a **Live source** (often M3U) and a **Movies & shows** source (often Xtream) so one library uses both. Live buffer Small / Medium / Large is the same as Watch.

On each playlist card: **Sync playlist**, **Sync EPG**, and **Groups** (hide categories you do not want). Live TV is a Watch-style guide: times, now, next, day chips for as far as the XMLTV/xmltv.php feed goes (up to 7 days).

Portals often use HTTP or invalid TLS. The app allows cleartext HTTP and a permissive trust manager for those hosts — same class of compromise as other IPTV APKs. Do not enter banking passwords here.

## Devices

`minSdk 26` (Android 8). One APK registers both `LAUNCHER` (phone) and `LEANBACK_LAUNCHER` (TV row). D-pad works; touch works. Optimize testing on Shield / Streamer; Fire Stick is supported but weaker.
