from __future__ import annotations

import ipaddress
import logging
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Set

from .models import DiscoveredDevice

logger = logging.getLogger(__name__)

try:
    from zeroconf import ServiceBrowser, Zeroconf, ZeroconfServiceTypes  # type: ignore

    _ZEROCONF_AVAILABLE = True
except Exception:  # pragma: no cover - exercised via optional import handling
    ServiceBrowser = None
    Zeroconf = None
    ZeroconfServiceTypes = None
    _ZEROCONF_AVAILABLE = False


class HostnameResolver:
    """Resolve hostnames for discovered devices using multiple mechanisms.

    Resolution order:
    1. Reverse DNS / PTR
    2. NetBIOS
    3. mDNS
    4. LLMNR (optional, best-effort fallback)
    """

    def __init__(self, timeout: float = 1.0, concurrency: int = 20):
        self.timeout = float(timeout)
        self.concurrency = max(1, int(concurrency))
        self._mdns_lock = threading.Lock()
        self._mdns_cache: Optional[Dict[str, str]] = None

    def _normalize_hostname(self, hostname: Optional[str]) -> Optional[str]:
        if hostname is None:
            return None

        hostname = str(hostname).strip().rstrip(".")
        return hostname or None

    def _is_valid_hostname(self, hostname: Optional[str], ip: str) -> bool:
        """Return True only when hostname is a real hostname, not the IP."""

        normalized = self._normalize_hostname(hostname)
        if not normalized:
            return False

        if normalized == ip:
            return False

        try:
            ipaddress.ip_address(normalized)
            return False
        except ValueError:
            return True

    def _attempt(self, status: str, hostname: Optional[str] = None, detail: Optional[str] = None) -> Dict[str, Any]:
        return {
            "status": status,
            "hostname": self._normalize_hostname(hostname),
            "detail": detail,
        }

    def _lookup_reverse_dns_detail(self, ip: str) -> Dict[str, Any]:
        previous_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(self.timeout)
            hostname, _, _ = socket.gethostbyaddr(ip)
            hostname = self._normalize_hostname(hostname)

            if not self._is_valid_hostname(hostname, ip):
                logger.debug("reverse DNS returned invalid hostname for %s: %s", ip, hostname)
                return self._attempt("not_found", detail="invalid hostname returned")

            return self._attempt("success", hostname=hostname)
        except (socket.timeout, TimeoutError) as exc:
            logger.debug("reverse DNS lookup timed out for %s: %s", ip, exc)
            return self._attempt("timeout", detail=str(exc))
        except (socket.herror, socket.gaierror) as exc:
            logger.debug("reverse DNS lookup failed for %s: %s", ip, exc)
            return self._attempt("not_found", detail=str(exc))
        except OSError as exc:
            logger.debug("reverse DNS lookup failed for %s: %s", ip, exc)
            return self._attempt("error", detail=str(exc))
        finally:
            socket.setdefaulttimeout(previous_timeout)

    def _lookup_reverse_dns(self, ip: str) -> Optional[str]:
        return self._lookup_reverse_dns_detail(ip)["hostname"]

    def _parse_nbtstat_hostname(self, output: str, ip: str) -> Optional[str]:
        """Extract a workstation/computer name from nbtstat output.

        Prefer `<00>` UNIQUE entries, then `<20>` UNIQUE entries. Ignore group
        and broadcast names.
        """

        fallback: Optional[str] = None

        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line or "<" not in line or ">" not in line:
                continue

            # Format is usually: NAME <00> UNIQUE Registered
            match = re.match(
                r"^(?P<name>\S+)\s+<(?P<suffix>[0-9A-Fa-f]{2})>\s+(?P<kind>\S+)",
                line,
            )
            if not match:
                continue

            name = self._normalize_hostname(match.group("name"))
            suffix = match.group("suffix").upper()
            kind = match.group("kind").upper()

            if not name or name == ip:
                continue

            upper_name = name.upper()
            if upper_name in {"WORKGROUP", "GROUP", "__MSBROWSE__"}:
                continue

            if "GROUP" in kind:
                continue

            if suffix == "00":
                return name

            if suffix == "20" and fallback is None:
                fallback = name

        return fallback

    def _lookup_netbios_detail(self, ip: str) -> Dict[str, Any]:
        if platform.system().lower() != "windows":
            logger.debug("NetBIOS lookup skipped on %s", platform.system())
            return self._attempt("unavailable", detail="unsupported platform")

        if shutil.which("nbtstat") is None:
            logger.warning("nbtstat command not found; skipping NetBIOS lookup")
            return self._attempt("unavailable", detail="nbtstat not found")

        try:
            result = subprocess.run(
                ["nbtstat", "-A", ip],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            output = self._subprocess_timeout_output(exc)
            if self._netbios_output_indicates_not_found(output):
                logger.debug("NetBIOS lookup found no hostname for %s before timeout", ip)
                return self._attempt("not_found", detail="host not found")

            logger.debug("NetBIOS lookup timed out for %s", ip)
            return self._attempt("timeout", detail=output or None)
        except FileNotFoundError:
            logger.warning("nbtstat command not found; skipping NetBIOS lookup")
            return self._attempt("unavailable", detail="nbtstat not found")
        except OSError as exc:
            logger.warning("NetBIOS lookup unavailable for %s: %s", ip, exc)
            return self._attempt("unavailable", detail=str(exc))

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            logger.debug(
                "NetBIOS lookup returned non-zero for %s: %s %s",
                ip,
                stderr,
                stdout,
            )
            return self._attempt("not_found", detail=stderr or stdout or f"exit {result.returncode}")

        hostname = self._parse_nbtstat_hostname(result.stdout or "", ip)
        if self._is_valid_hostname(hostname, ip):
            return self._attempt("success", hostname=hostname)

        logger.debug("NetBIOS lookup found no hostname for %s", ip)
        return self._attempt("not_found")

    def _lookup_netbios(self, ip: str) -> Optional[str]:
        return self._lookup_netbios_detail(ip)["hostname"]

    def _subprocess_timeout_output(self, exc: subprocess.TimeoutExpired) -> str:
        parts = []
        for value in (exc.stdout, exc.stderr):
            if not value:
                continue
            if isinstance(value, bytes):
                parts.append(value.decode(errors="replace"))
            else:
                parts.append(str(value))

        return "\n".join(parts).strip()

    def _netbios_output_indicates_not_found(self, output: str) -> bool:
        normalized = output.lower()
        return "host not found" in normalized or "name not found" in normalized

    def _mdns_service_browser(self, zc: "Zeroconf", service_type: str, callback):
        if ServiceBrowser is None:
            return None

        # Support both common ServiceBrowser signatures.
        try:
            return ServiceBrowser(zc, service_type, handlers=[callback], delay=0)
        except TypeError:
            try:
                return ServiceBrowser(zc, service_type, callback, delay=0)
            except TypeError:
                return ServiceBrowser(zc, service_type, [callback])

    def _service_info_addresses(self, info) -> Set[str]:
        addresses: Set[str] = set()

        parsed_addresses = getattr(info, "parsed_addresses", None)
        if callable(parsed_addresses):
            try:
                addresses.update(str(addr) for addr in parsed_addresses())
            except Exception:
                pass

        raw_addresses = getattr(info, "addresses", None) or []
        for raw in raw_addresses:
            try:
                if isinstance(raw, (bytes, bytearray)):
                    addresses.add(str(ipaddress.ip_address(raw)))
                else:
                    addresses.add(str(raw))
            except Exception:
                continue

        return addresses

    def _service_info_hostname(self, info) -> Optional[str]:
        hostname = getattr(info, "server", None) or getattr(info, "hostname", None)
        return self._normalize_hostname(hostname)

    def _browse_mdns(self, zc: "Zeroconf", service_type: str, timeout: float) -> List[str]:
        names: List[str] = []
        seen: Set[str] = set()
        event = threading.Event()

        def callback(*args, **kwargs):
            name = kwargs.get("name")
            state_change = kwargs.get("state_change")

            if len(args) >= 3 and name is None:
                name = args[2]
            if len(args) >= 4 and state_change is None:
                state_change = args[3]

            if not name or state_change is None:
                return

            state_name = getattr(state_change, "name", str(state_change))
            if state_name != "Added":
                return

            if name not in seen:
                seen.add(name)
                names.append(name)
                event.set()

        browser = self._mdns_service_browser(zc, service_type, callback)
        if browser is None:
            return names

        time.sleep(timeout)
        return names

    def _discover_mdns_hostnames(self) -> Dict[str, str]:
        if not _ZEROCONF_AVAILABLE:
            logger.warning("zeroconf is not installed; skipping mDNS lookup")
            return {}

        hostnames: Dict[str, str] = {}
        deadline = time.monotonic() + self.timeout
        zc = Zeroconf()

        try:
            service_types = []
            if ZeroconfServiceTypes is not None:
                try:
                    service_types = list(ZeroconfServiceTypes.find(zc=zc, timeout=min(self.timeout, 2.0)))
                except Exception as exc:
                    logger.debug("mDNS service type discovery failed: %s", exc)

            if not service_types:
                service_types = self._browse_mdns(zc, "_services._dns-sd._udp.local.", min(self.timeout, 0.5))

            # If no types are immediately available, keep a short bounded wait
            # and return gracefully.
            if not service_types:
                logger.debug("mDNS lookup found no service types")
                return hostnames

            for service_type in service_types:
                if time.monotonic() >= deadline:
                    break

                remaining = max(0.1, deadline - time.monotonic())
                service_names = self._browse_mdns(zc, service_type, min(remaining, self.timeout))

                for service_name in service_names:
                    remaining = max(0.1, deadline - time.monotonic())
                    try:
                        info = zc.get_service_info(service_type, service_name, timeout=min(remaining, self.timeout))
                    except Exception as exc:
                        logger.debug("mDNS service info lookup failed for %s/%s: %s", service_type, service_name, exc)
                        continue

                    if not info:
                        continue

                    addresses = self._service_info_addresses(info)
                    hostname = self._service_info_hostname(info)
                    fallback = self._normalize_hostname(service_name.split(".", 1)[0])

                    for address in addresses:
                        candidate = hostname if self._is_valid_hostname(hostname, address) else fallback
                        if self._is_valid_hostname(candidate, address):
                            hostnames[address] = candidate

            return hostnames
        finally:
            try:
                zc.close()
            except Exception:
                pass

    def _get_mdns_hostnames(self) -> Dict[str, str]:
        with self._mdns_lock:
            if self._mdns_cache is None:
                self._mdns_cache = self._discover_mdns_hostnames()
            return dict(self._mdns_cache)

    def _lookup_mdns_detail(self, ip: str) -> Dict[str, Any]:
        if not _ZEROCONF_AVAILABLE:
            logger.warning("zeroconf is not installed; skipping mDNS lookup")
            return self._attempt("unavailable", detail="zeroconf not installed")

        try:
            hostname = self._get_mdns_hostnames().get(ip)
        except Exception as exc:
            logger.debug("mDNS lookup failed for %s: %s", ip, exc)
            return self._attempt("error", detail=str(exc))

        if self._is_valid_hostname(hostname, ip):
            return self._attempt("success", hostname=hostname)

        logger.debug("mDNS lookup found no hostname for %s", ip)
        return self._attempt("not_found")

    def _lookup_mdns(self, ip: str) -> Optional[str]:
        return self._lookup_mdns_detail(ip)["hostname"]

    def _lookup_dhcp_hostname(self, ip: str) -> Optional[str]:
        logger.debug("DHCP lease hostname lookup not configured for %s", ip)
        return None

    def _lookup_llmnr_detail(self, ip: str) -> Dict[str, Any]:
        detail = (
            "LLMNR is name-to-address oriented; reverse lookup by IP requires "
            "known name candidates or broad enumeration, so it is not attempted"
        )
        logger.debug("LLMNR lookup unavailable for %s: %s", ip, detail)
        return self._attempt("unavailable", detail=detail)

    def _lookup_llmnr(self, ip: str) -> Optional[str]:
        return self._lookup_llmnr_detail(ip)["hostname"]

    def _resolve_hostname(self, ip: str) -> Optional[str]:
        return self.resolve_with_details(ip)["hostname"]

    def resolve_with_details(self, ip: str) -> Dict[str, Any]:
        attempts: Dict[str, Dict[str, Any]] = {
            "reverse_dns": self._attempt("not_attempted"),
            "netbios": self._attempt("not_attempted"),
            "mdns": self._attempt("not_attempted"),
            "llmnr": self._attempt("not_attempted"),
        }
        resolvers = [
            ("reverse_dns", self._lookup_reverse_dns_detail),
            ("netbios", self._lookup_netbios_detail),
            ("mdns", self._lookup_mdns_detail),
            ("llmnr", self._lookup_llmnr_detail),
        ]

        for method, resolver in resolvers:
            resolver_name = getattr(resolver, "__name__", resolver.__class__.__name__)
            try:
                attempt = resolver(ip)
                attempts[method] = attempt
                hostname = attempt.get("hostname")

                if self._is_valid_hostname(hostname, ip):
                    hostname = self._normalize_hostname(hostname)
                    logger.debug("resolved %s -> %s using %s", ip, hostname, resolver_name)
                    self._log_resolution_details(ip, hostname, method, attempts)
                    return {
                        "hostname": hostname,
                        "method": method,
                        "attempts": attempts,
                    }

            except Exception as exc:
                logger.exception("hostname resolver %s failed for %s", resolver_name, ip)
                attempts[method] = self._attempt("error", detail=str(exc))

        logger.debug("no hostname found for %s", ip)
        self._log_resolution_details(ip, None, None, attempts)
        return {
            "hostname": None,
            "method": None,
            "attempts": attempts,
        }

    def _log_resolution_details(
        self,
        ip: str,
        hostname: Optional[str],
        method: Optional[str],
        attempts: Dict[str, Dict[str, Any]],
    ) -> None:
        labels = {
            "reverse_dns": "PTR",
            "netbios": "NetBIOS",
            "mdns": "mDNS",
            "llmnr": "LLMNR",
        }
        lines = [ip]
        for key in ("reverse_dns", "netbios", "mdns", "llmnr"):
            attempt = attempts[key]
            status = attempt["status"]
            value = attempt.get("hostname")
            suffix = f" -> {value}" if value else ""
            lines.append(f"  {labels[key]}: {status}{suffix}")

        if hostname:
            lines.append(f"  result: {hostname} via {method}")
        else:
            lines.append("  result: unresolved")

        logger.debug("\n".join(lines))

    def resolve(self, device: DiscoveredDevice) -> DiscoveredDevice:
        if not device or not getattr(device, "ip_address", None):
            return device

        if self._is_valid_hostname(device.hostname, device.ip_address):
            logger.debug("hostname already present for %s: %s", device.ip_address, device.hostname)
            return device

        if self._normalize_hostname(device.hostname):
            logger.debug("discarding invalid existing hostname for %s: %s", device.ip_address, device.hostname)
            device.hostname = None

        try:
            details = self.resolve_with_details(device.ip_address)
            hostname = details["hostname"]
        except Exception:
            logger.exception("unexpected error resolving hostname for %s", device.ip_address)
            return device

        if self._is_valid_hostname(hostname, device.ip_address):
            device.hostname = hostname

        return device

    def resolve_all(self, devices: Iterable[DiscoveredDevice]) -> List[DiscoveredDevice]:
        devices = list(devices)

        def resolve_one(device: DiscoveredDevice):
            try:
                return self.resolve(device)
            except Exception:
                logger.exception("unexpected error resolving hostname for %s", getattr(device, "ip_address", None))
                return device

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            return list(executor.map(resolve_one, devices))
