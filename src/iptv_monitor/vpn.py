"""Surfshark / WireGuard split tunnel for Magnum DNS health (not live/VOD).

The VPS default route stays on the public NIC (SSH, Caddy, Discord, Strong 8K,
and Magnum /watch live/VOD). Magnum rejects stream URLs from the VPN exit.
When WireGuard is up, Magnum DNS lookups bind to that address. Status +
speed-test are owner-only. The speed test scores the public NIC as the /watch
path and compares the VPN when it is up.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import socket
import time
from typing import Any

import httpx

logger = logging.getLogger("iptv_monitor.vpn")

_IFACE_HINTS = ("surfshark", "surfshark_wg", "wg-surfshark", "wg0")
_HANDSHAKE_MAX = 180.0
_EXIT_TTL = 45.0
_SNAP_TTL = 8.0
_PROXY_PORT = 18788
_WATCH_STREAMS = 5
_BYTES_EACH = 12_000_000
_SPEED_URLS = (
    "https://speed.cloudflare.com/__down?bytes={bytes}",
    "http://ipv4.download.thinkbroadband.com/20MB.zip",
)
# Aggregate Mbps for 5 concurrent lives (typical bitrate + ~20% overhead).
_SPEED_TIERS = (
    (140.0, "comfortable_4k", "Comfortable for 5 concurrent /watch streams, including 4K."),
    (100.0, "ok_4k", "Enough for 5× 4K if each stays near 20 Mbps."),
    (60.0, "ok_fhd", "Enough for 5× FHD. Five 4K streams would be tight."),
    (35.0, "ok_hd", "Enough for 5× HD. Not enough for five FHD/4K streams."),
    (0.0, "insufficient", "Not enough headroom for 5 concurrent /watch streams."),
)

_CC = {
    "ae": "United Arab Emirates",
    "at": "Austria",
    "au": "Australia",
    "be": "Belgium",
    "br": "Brazil",
    "ca": "Canada",
    "ch": "Switzerland",
    "cz": "Czechia",
    "de": "Germany",
    "dk": "Denmark",
    "es": "Spain",
    "fi": "Finland",
    "fr": "France",
    "gb": "United Kingdom",
    "gr": "Greece",
    "hu": "Hungary",
    "ie": "Ireland",
    "in": "India",
    "it": "Italy",
    "jp": "Japan",
    "mx": "Mexico",
    "nl": "Netherlands",
    "no": "Norway",
    "nz": "New Zealand",
    "pl": "Poland",
    "pt": "Portugal",
    "ro": "Romania",
    "se": "Sweden",
    "sg": "Singapore",
    "tr": "Turkey",
    "uk": "United Kingdom",
    "us": "United States",
    "za": "South Africa",
}
_CITY = {
    "ams": "Amsterdam",
    "ath": "Athens",
    "ber": "Berlin",
    "bru": "Brussels",
    "bud": "Budapest",
    "chi": "Chicago",
    "cph": "Copenhagen",
    "dal": "Dallas",
    "dub": "Dublin",
    "fra": "Frankfurt",
    "hel": "Helsinki",
    "ist": "Istanbul",
    "lax": "Los Angeles",
    "lis": "Lisbon",
    "lon": "London",
    "mad": "Madrid",
    "man": "Manchester",
    "mel": "Melbourne",
    "mia": "Miami",
    "mil": "Milan",
    "mum": "Mumbai",
    "nyc": "New York",
    "osl": "Oslo",
    "par": "Paris",
    "prg": "Prague",
    "rom": "Rome",
    "sao": "Sao Paulo",
    "sjc": "San Jose",
    "sto": "Stockholm",
    "syd": "Sydney",
    "tok": "Tokyo",
    "tor": "Toronto",
    "vie": "Vienna",
    "waw": "Warsaw",
    "zrh": "Zurich",
}

_iface_pref = ""
_exit_cache: tuple[float, str, str] = (0.0, "", "")
_snap_cache: tuple[float, dict[str, Any]] = (0.0, {})
_speed_lock = asyncio.Lock()
_proxy_task: asyncio.Task[None] | None = None


def set_interface_preference(name: str) -> None:
    global _iface_pref
    _iface_pref = (name or "").strip()


def list_wg_interfaces() -> list[str]:
    found: list[str] = []
    try:
        import psutil  # type: ignore
    except Exception:
        psutil = None
    names: list[str] = []
    if psutil is not None:
        names = list(psutil.net_if_addrs().keys())
    else:
        try:
            names = [item[1] for item in socket.if_nameindex()]
        except Exception:
            names = []
    prefer = [_iface_pref] if _iface_pref else []
    ordered = prefer + [hint for hint in _IFACE_HINTS if hint not in prefer]
    for name in ordered:
        if name and name in names:
            found.append(name)
    for name in names:
        low = name.lower()
        if name not in found and ("surfshark" in low or low.startswith("wg")):
            found.append(name)
    return found


def bind_ip(iface: str | None = None) -> str:
    """IPv4 on the VPN interface, or empty if it is down."""
    name = iface or (list_wg_interfaces()[0] if list_wg_interfaces() else "")
    if not name:
        return ""
    try:
        import psutil  # type: ignore

        for addr in psutil.net_if_addrs().get(name) or []:
            if addr.family == socket.AF_INET and addr.address and not addr.address.startswith("127."):
                return addr.address
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(name, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return _ip_from_ip_cmd(name)


def _ip_from_ip_cmd(iface: str) -> str:
    try:
        import subprocess

        raw = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "dev", iface],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return ""
    match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", raw.stdout or "")
    return match.group(1) if match else ""


def magnum_transport(*, sync: bool = False):
    """httpx transport bound to the VPN, or None to use the default NIC."""
    ip = bind_ip()
    if not ip:
        return None
    if sync:
        return httpx.HTTPTransport(local_address=ip)
    return httpx.AsyncHTTPTransport(local_address=ip)


def magnum_client_kwargs(*, sync: bool = False) -> dict[str, Any]:
    transport = magnum_transport(sync=sync)
    return {"transport": transport} if transport is not None else {}


def ffmpeg_env() -> dict[str, str]:
    """Point ffmpeg/ffprobe at the local bind-proxy when the VPN is up."""
    env = dict(os.environ)
    if bind_ip():
        proxy = f"http://127.0.0.1:{_PROXY_PORT}"
        env["http_proxy"] = proxy
        env["HTTP_PROXY"] = proxy
        env["https_proxy"] = proxy
        env["HTTPS_PROXY"] = proxy
        env["no_proxy"] = "127.0.0.1,localhost"
        env["NO_PROXY"] = "127.0.0.1,localhost"
    return env


async def _run_wg_dump() -> str:
    wg = shutil.which("wg")
    if not wg:
        return ""
    for argv in ([wg, "show", "all", "dump"], ["sudo", "-n", wg, "show", "all", "dump"]):
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            continue
        try:
            async with asyncio.timeout(3):
                out, _err = await proc.communicate()
        except TimeoutError:
            proc.kill()
            await proc.wait()
            continue
        if proc.returncode == 0 and out:
            return out.decode("utf-8", "replace")
    return ""


def _location_from_endpoint(endpoint: str) -> str:
    host = (endpoint or "").split(":")[0].strip().lower()
    if not host or re.match(r"^\d+\.\d+\.\d+\.\d+$", host):
        return ""
    label = host.split(".")[0]
    parts = [p for p in label.split("-") if p]
    if len(parts) >= 2:
        cc, city = parts[0], parts[1]
        country = _CC.get(cc, cc.upper())
        place = _CITY.get(city, city.upper())
        return f"{place}, {country}"
    if parts:
        return _CC.get(parts[0], parts[0].upper())
    return host


def _parse_dump(text: str, iface: str) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) < 9:
            continue
        name = cols[0]
        if iface and name != iface:
            continue
        endpoint = cols[3] if cols[3] != "(none)" else ""
        try:
            handshake = int(cols[5])
        except ValueError:
            handshake = 0
        try:
            rx = int(cols[6])
            tx = int(cols[7])
        except ValueError:
            rx = tx = 0
        rows = {
            "interface": name,
            "endpoint": endpoint,
            "handshake": handshake,
            "rx_bytes": rx,
            "tx_bytes": tx,
        }
        if iface and name == iface:
            return rows
    return rows


async def _exit_meta(bind: str) -> tuple[str, str]:
    global _exit_cache
    now = time.monotonic()
    if now - _exit_cache[0] < _EXIT_TTL and _exit_cache[1]:
        return _exit_cache[1], _exit_cache[2]
    ip = ""
    place = ""
    timeout = httpx.Timeout(4.0, connect=3.0)
    transport = httpx.AsyncHTTPTransport(local_address=bind, verify=False)
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=True) as client:
            r = await client.get("https://api.ipify.org")
            if r.status_code == 200:
                ip = r.text.strip()
            if ip:
                geo = await client.get(f"http://ip-api.com/json/{ip}?fields=status,country,city")
                data = geo.json() if geo.status_code == 200 else {}
                if data.get("status") == "success":
                    city = str(data.get("city") or "").strip()
                    country = str(data.get("country") or "").strip()
                    place = ", ".join(p for p in (city, country) if p)
    except Exception as exc:
        logger.debug("VPN exit lookup failed: %s", exc)
    if ip:
        _exit_cache = (now, ip, place)
    return ip, place


async def snapshot() -> dict[str, Any]:
    global _snap_cache
    now = time.monotonic()
    if now - _snap_cache[0] < _SNAP_TTL and _snap_cache[1]:
        return dict(_snap_cache[1])
    ifaces = list_wg_interfaces()
    iface = ifaces[0] if ifaces else ""
    ip = bind_ip(iface) if iface else ""
    dump = await _run_wg_dump() if iface else ""
    peer = _parse_dump(dump, iface) if dump else {}
    handshake = int(peer.get("handshake") or 0)
    age = max(0, int(time.time() - handshake)) if handshake else None
    live = bool(ip) and (age is None or age <= _HANDSHAKE_MAX)
    if handshake == 0 and ip:
        live = True
    endpoint = str(peer.get("endpoint") or "")
    location = _location_from_endpoint(endpoint)
    exit_ip = ""
    if ip:
        exit_ip, geo = await _exit_meta(ip)
        if geo:
            location = geo
    data = {
        "configured": bool(iface),
        "connected": live,
        "interface": iface,
        "bind_ip": ip,
        "endpoint": endpoint,
        "location": location or ("VPN up" if live else ""),
        "exit_ip": exit_ip,
        "handshake_seconds": age,
        "rx_bytes": int(peer.get("rx_bytes") or 0),
        "tx_bytes": int(peer.get("tx_bytes") or 0),
        "watch_via_vpn": bool(ip),
    }
    _snap_cache = (now, data)
    return dict(data)


async def _ping_ms(client: httpx.AsyncClient) -> float | None:
    try:
        t0 = time.perf_counter()
        ping = await client.get("https://www.cloudflare.com/cdn-cgi/trace")
        if ping.status_code == 200:
            return round((time.perf_counter() - t0) * 1000, 1)
    except Exception:
        return None
    return None


async def _pull_bytes(client: httpx.AsyncClient, url: str, want: int) -> dict[str, Any]:
    t0 = time.perf_counter()
    total = 0
    async with client.stream("GET", url) as response:
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}")
        async for chunk in response.aiter_bytes(64 * 1024):
            total += len(chunk)
            if total >= want:
                break
    seconds = max(0.001, time.perf_counter() - t0)
    if total < max(1_000_000, want // 4):
        raise RuntimeError(f"short read ({total} bytes)")
    return {
        "bytes": total,
        "seconds": round(seconds, 2),
        "mbps": round((total * 8) / seconds / 1_000_000, 2),
    }


def _verdict(aggregate_mbps: float) -> tuple[str, str]:
    for floor, key, label in _SPEED_TIERS:
        if aggregate_mbps >= floor:
            return key, label
    return _SPEED_TIERS[-1][1], _SPEED_TIERS[-1][2]


async def _burst(
    *,
    path: str,
    bind: str,
    streams: int,
    want: int,
) -> dict[str, Any]:
    timeout = httpx.Timeout(40.0, connect=8.0)
    kwargs: dict[str, Any] = {
        "timeout": timeout,
        "follow_redirects": True,
        "http2": False,
        "verify": False,
        "headers": {"User-Agent": "iptv-monitor-speedtest", "Accept": "*/*"},
    }
    if bind:
        kwargs["transport"] = httpx.AsyncHTTPTransport(local_address=bind, verify=False)
    last_error = "speed test failed"
    async with httpx.AsyncClient(**kwargs) as client:
        ping_ms = await _ping_ms(client)
        for template in _SPEED_URLS:
            url = template.format(bytes=want)
            try:
                started = time.perf_counter()
                rows = await asyncio.gather(
                    *[_pull_bytes(client, url, want) for _ in range(streams)],
                    return_exceptions=True,
                )
                wall = max(0.001, time.perf_counter() - started)
            except Exception as exc:
                last_error = str(exc)[:160]
                continue
            ok_rows = [row for row in rows if isinstance(row, dict)]
            if not ok_rows:
                err = next((row for row in rows if isinstance(row, Exception)), None)
                last_error = str(err)[:160] if err else "all connections failed"
                continue
            total_bytes = sum(int(row["bytes"]) for row in ok_rows)
            aggregate = round((total_bytes * 8) / wall / 1_000_000, 2)
            per_stream = round(aggregate / max(1, len(ok_rows)), 2)
            min_mbps = min(float(row["mbps"]) for row in ok_rows)
            key, label = _verdict(aggregate)
            return {
                "ok": True,
                "path": path,
                "download_mbps": aggregate,
                "per_stream_mbps": per_stream,
                "min_stream_mbps": min_mbps,
                "connections": len(ok_rows),
                "wanted_connections": streams,
                "bytes": total_bytes,
                "seconds": round(wall, 2),
                "latency_ms": ping_ms,
                "bind_ip": bind,
                "verdict": key,
                "verdict_label": label,
            }
    raise RuntimeError(last_error)


async def speedtest() -> dict[str, Any]:
    """Five parallel downloads on the /watch Magnum path (public NIC)."""
    async with _speed_lock:
        watch = await _burst(
            path="public_nic",
            bind="",
            streams=_WATCH_STREAMS,
            want=_BYTES_EACH,
        )
        vpn_row: dict[str, Any] | None = None
        ip = bind_ip()
        if ip:
            try:
                vpn_row = await _burst(
                    path="vpn",
                    bind=ip,
                    streams=_WATCH_STREAMS,
                    want=_BYTES_EACH,
                )
            except Exception as exc:
                vpn_row = {"ok": False, "path": "vpn", "error": str(exc)[:160], "bind_ip": ip}
        return {
            "ok": True,
            "download_mbps": watch["download_mbps"],
            "per_stream_mbps": watch["per_stream_mbps"],
            "latency_ms": watch["latency_ms"],
            "bytes": watch["bytes"],
            "seconds": watch["seconds"],
            "verdict": watch["verdict"],
            "verdict_label": watch["verdict_label"],
            "watch": watch,
            "vpn": vpn_row,
            "nic": watch,
        }


async def _proxy_handle(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, bind: str
) -> None:
    try:
        header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=12)
    except Exception:
        writer.close()
        return
    line = header.split(b"\r\n", 1)[0].decode("latin1", "replace")
    parts = line.split()
    if len(parts) < 2:
        writer.close()
        return
    method, target = parts[0].upper(), parts[1]
    try:
        if method == "CONNECT":
            host, port_s = target.rsplit(":", 1)
            port = int(port_s)
            remote = socket.create_connection((host, port), timeout=12, source_address=(bind, 0))
            remote.setblocking(False)
            loop = asyncio.get_running_loop()
            r_reader, r_writer = await asyncio.open_connection(sock=remote)
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await writer.drain()
            await _pipe(reader, writer, r_reader, r_writer)
            return
        from urllib.parse import urlsplit

        parsed = urlsplit(target)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        req = header.replace(target.encode("latin1"), path.encode("latin1"), 1)
        remote = socket.create_connection((host, port), timeout=12, source_address=(bind, 0))
        remote.setblocking(False)
        r_reader, r_writer = await asyncio.open_connection(sock=remote)
        r_writer.write(req)
        await r_writer.drain()
        await _pipe(reader, writer, r_reader, r_writer)
    except Exception:
        try:
            writer.close()
        except Exception:
            pass


async def _pipe(
    a_r: asyncio.StreamReader,
    a_w: asyncio.StreamWriter,
    b_r: asyncio.StreamReader,
    b_w: asyncio.StreamWriter,
) -> None:
    async def one(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
        try:
            while True:
                data = await src.read(64 * 1024)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass

    await asyncio.gather(one(a_r, b_w), one(b_r, a_w), return_exceptions=True)


async def run_bind_proxy() -> None:
    """Local HTTP proxy whose outbound sockets bind to the VPN address."""
    server: asyncio.AbstractServer | None = None

    async def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        ip = bind_ip()
        if not ip:
            writer.close()
            return
        await _proxy_handle(reader, writer, ip)

    while True:
        try:
            if server is None:
                server = await asyncio.start_server(accept, "127.0.0.1", _PROXY_PORT)
                logger.info("Watch VPN bind-proxy on 127.0.0.1:%s", _PROXY_PORT)
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            if server is not None:
                server.close()
                await server.wait_closed()
            raise
        except Exception as exc:
            logger.warning("Watch VPN bind-proxy: %s", exc)
            server = None
            await asyncio.sleep(5)


def start_bind_proxy() -> None:
    global _proxy_task
    if _proxy_task is None or _proxy_task.done():
        _proxy_task = asyncio.create_task(run_bind_proxy(), name="watch-vpn-proxy")
