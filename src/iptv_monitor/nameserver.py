"""Find which DNS company hosts a portal, and whether Cloudflare is proxying it.

Cloudflare nameservers look like ada.ns.cloudflare.com (real first names).
Orange-cloud / proxied hosts resolve to Cloudflare anycast IPs from their
published ranges: https://www.cloudflare.com/ips/
"""

from __future__ import annotations

import ipaddress
import logging
import time

import dns.asyncresolver
import dns.exception
import dns.resolver

logger = logging.getLogger("iptv_monitor.nameserver")

# Orange-cloud IPTV blocks happen on these proxy ranges, not merely "NS is Cloudflare".
_CLOUDFLARE_NETWORKS = [
    ipaddress.ip_network(cidr)
    for cidr in (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
]

# Substring match against NS hostnames, first match wins.
_NS_PROVIDERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cloudflare", ("ns.cloudflare.com", "cloudflare-dns.com")),
    ("aws", ("awsdns", "amazonaws.com")),
    ("google", ("googledomains", "ns.google.com", "ns-cloud-")),
    ("azure", ("azure-dns", "azure-dns.org")),
    ("godaddy", ("domaincontrol.com",)),
    ("namecheap", ("registrar-servers.com",)),
    ("cloudns", ("cloudns.net", "cloudns.eu")),
)

# Successes stay cached 10 minutes; empty results only 30s so a blip can recover.
_NS_CACHE: dict[str, tuple[float, list[str]]] = {}
_NS_CACHE_TTL = 600.0
_NS_CACHE_EMPTY_TTL = 30.0


def ip_is_cloudflare(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in network for network in _CLOUDFLARE_NETWORKS)


def classify_ns_hosts(hosts: list[str]) -> str | None:
    """Map NS hostnames to a short provider name, or 'other'."""
    blob = " ".join(host.lower() for host in hosts)
    if not blob:
        return None
    for name, needles in _NS_PROVIDERS:
        if any(needle in blob for needle in needles):
            return name
    return "other"


async def lookup_ns_hosts(host: str, timeout: float) -> list[str]:
    """Walk cf.example.com → example.com until an NS record answers."""
    if not host or host.endswith(".invalid"):
        return []
    key = host.rstrip(".").lower()
    cached = _NS_CACHE.get(key)
    now = time.monotonic()
    if cached is not None:
        expires_at, hosts = cached
        if now < expires_at:
            return list(hosts)

    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = timeout
    resolver.timeout = timeout
    labels = key.split(".")
    if len(labels) < 2:
        return []
    found: list[str] = []
    for start in range(0, len(labels) - 1):
        zone = ".".join(labels[start:])
        try:
            answer = await resolver.resolve(zone, "NS")
            found = sorted({str(item.target).rstrip(".").lower() for item in answer})
            break
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            continue
        except dns.exception.Timeout:
            logger.debug("NS lookup timed out for %s", zone)
            break
        except Exception as exc:  # noqa: BLE001
            logger.debug("NS lookup failed for %s: %s", zone, exc)
            break
    ttl = _NS_CACHE_TTL if found else _NS_CACHE_EMPTY_TTL
    _NS_CACHE[key] = (now + ttl, found)
    return list(found)
