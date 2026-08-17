from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

import dns.asyncresolver
import dns.exception
import dns.resolver
import httpx

from iptv_monitor.config import Settings
from iptv_monitor.nameserver import classify_ns_hosts, ip_is_cloudflare, lookup_ns_hosts

logger = logging.getLogger("iptv_monitor.health")


@dataclass
class HealthResult:
    url: str
    host: str
    port: int
    dns_ok: bool
    tcp_ok: bool
    http_ok: bool | None
    resolved_ips: list[str] = field(default_factory=list)
    nameserver: str | None = None
    nameserver_hosts: list[str] = field(default_factory=list)
    cloudflare_proxied: bool = False
    fail_reason: str | None = None
    healthy: bool = False
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error_detail: str | None = None


def normalize_url(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValueError("Empty URL")
    if "://" not in value:
        value = f"http://{value}"
    return value


def parse_endpoint(raw: str) -> tuple[str, str, int]:
    url = normalize_url(raw)
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        raise ValueError(f"URL has no hostname: {raw}")
    if parsed.port:
        port = parsed.port
    elif parsed.scheme == "https":
        port = 443
    else:
        port = 80
    return url, host, port


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _prefer_ipv4(ips: list[str]) -> list[str]:
    v4 = [ip for ip in ips if ":" not in ip]
    v6 = [ip for ip in ips if ":" in ip]
    return v4 + v6


async def _resolve_dns(host: str, timeout: float) -> tuple[bool, list[str], str | None, str | None]:
    if _is_ip(host):
        return True, [host], None, None

    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = timeout
    resolver.timeout = timeout
    ips: list[str] = []
    try:
        for rdtype in ("A", "AAAA"):
            try:
                answer = await resolver.resolve(host, rdtype)
                ips.extend(str(item) for item in answer)
            except dns.resolver.NoAnswer:
                continue
            except dns.resolver.NXDOMAIN:
                return False, [], "dns_nxdomain", None
        if not ips:
            return False, [], "dns_no_records", None
        return True, _prefer_ipv4(ips), None, None
    except dns.exception.Timeout:
        return False, [], "dns_timeout", None
    except dns.resolver.NXDOMAIN:
        return False, [], "dns_nxdomain", None
    except dns.resolver.NoNameservers as exc:
        return False, [], "dns_no_nameservers", str(exc)
    except Exception as exc:  # noqa: BLE001 - surface unexpected resolver errors
        logger.warning("DNS lookup failed for %s: %s", host, exc)
        return False, [], "dns_error", str(exc)


async def _check_tcp(ips: list[str], host: str, port: int, timeout: float) -> tuple[bool, str | None, str | None]:
    targets = ips or [host]
    last_reason = "tcp_error"
    last_detail: str | None = None
    for target in targets:
        try:
            conn = asyncio.open_connection(target, port)
            _reader, writer = await asyncio.wait_for(conn, timeout=timeout)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
            return True, None, None
        except asyncio.TimeoutError:
            last_reason = "tcp_timeout"
            last_detail = f"{target}:{port}"
        except ConnectionRefusedError:
            last_reason = "tcp_refused"
            last_detail = f"{target}:{port}"
        except OSError as exc:
            last_reason = "tcp_error"
            last_detail = f"{target}:{port} {exc}"
    return False, last_reason, last_detail


async def _check_http(url: str, timeout: float, insecure: bool) -> tuple[bool, str | None, str | None]:
    try:
        async with httpx.AsyncClient(
            verify=not insecure,
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            await client.get(url)
            return True, None, None
    except httpx.TimeoutException:
        return False, "http_timeout", None
    except httpx.RequestError as exc:
        return False, "http_error", str(exc)


async def check_url(raw_url: str, settings: Settings) -> HealthResult:
    try:
        url, host, port = parse_endpoint(raw_url)
    except ValueError as exc:
        return HealthResult(
            url=raw_url,
            host="",
            port=0,
            dns_ok=False,
            tcp_ok=False,
            http_ok=None,
            fail_reason="bad_url",
            healthy=False,
            error_detail=str(exc),
        )

    dns_ok = True
    tcp_ok = True
    http_ok: bool | None = None
    resolved_ips: list[str] = []
    fail_reason: str | None = None
    error_detail: str | None = None
    ns_task = None
    if host and not _is_ip(host):
        ns_task = asyncio.create_task(lookup_ns_hosts(host, settings.dns_timeout_seconds))

    try:
        if settings.dns_check_enabled:
            dns_ok, resolved_ips, fail_reason, error_detail = await _resolve_dns(
                host, settings.dns_timeout_seconds
            )
        elif _is_ip(host):
            resolved_ips = [host]

        if fail_reason is not None:
            tcp_ok = False
        elif settings.tcp_check_enabled:
            tcp_ok, tcp_reason, tcp_detail = await _check_tcp(
                resolved_ips, host, port, settings.tcp_timeout_seconds
            )
            if not tcp_ok:
                fail_reason = tcp_reason
                error_detail = tcp_detail

        if fail_reason is None and settings.http_check_enabled:
            http_ok, http_reason, http_detail = await _check_http(
                url, settings.http_timeout_seconds, settings.allow_insecure_tls
            )
            if not http_ok:
                fail_reason = http_reason
                error_detail = http_detail
    finally:
        nameserver_hosts: list[str] = []
        if ns_task is not None:
            try:
                nameserver_hosts = await ns_task
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.debug("NS lookup failed for %s: %s", host, exc)

    nameserver = classify_ns_hosts(nameserver_hosts)
    cloudflare_proxied = any(ip_is_cloudflare(ip) for ip in resolved_ips)
    if cloudflare_proxied and nameserver is None:
        nameserver = "cloudflare"

    return HealthResult(
        url=url,
        host=host,
        port=port,
        dns_ok=dns_ok,
        tcp_ok=tcp_ok,
        http_ok=http_ok,
        resolved_ips=resolved_ips,
        nameserver=nameserver,
        nameserver_hosts=nameserver_hosts,
        cloudflare_proxied=cloudflare_proxied,
        fail_reason=fail_reason,
        healthy=fail_reason is None,
        error_detail=error_detail,
    )


async def check_urls(urls: list[str], settings: Settings) -> dict[str, HealthResult]:
    unique: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        try:
            key = normalize_url(raw)
        except ValueError:
            key = raw
        if key not in seen:
            seen.add(key)
            unique.append(raw)

    results = await asyncio.gather(
        *(check_url(url, settings) for url in unique),
        return_exceptions=True,
    )
    mapped: dict[str, HealthResult] = {}
    for raw, result in zip(unique, results, strict=True):
        if isinstance(result, Exception):
            logger.exception("Health check crashed for %s: %s", raw, result)
            try:
                key = normalize_url(raw)
            except ValueError:
                key = raw
            mapped[key] = HealthResult(
                url=raw,
                host="",
                port=0,
                dns_ok=False,
                tcp_ok=False,
                http_ok=None,
                fail_reason="check_error",
                healthy=False,
                error_detail=str(result),
            )
        else:
            mapped[result.url] = result
    return mapped
