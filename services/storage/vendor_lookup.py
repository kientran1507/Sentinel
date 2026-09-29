from __future__ import annotations

import re
from typing import Callable, Optional

from mac_vendor_lookup import MacLookup

from .devices import normalize_mac


_NORMALIZED_MAC = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")


class MacVendorResolver:
    """Best-effort vendor lookup backed only by the local OUI cache."""

    def __init__(self, lookup_client: Optional[MacLookup] = None):
        self._lookup_client = lookup_client or MacLookup()
        self._cache: dict[str, Optional[str]] = {}
        self._vendors_loaded = False

    def lookup(self, mac_address: Optional[str]) -> Optional[str]:
        normalized = self._normalize_for_lookup(mac_address)
        if normalized is None:
            return None
        if normalized in self._cache:
            if self._vendors_loaded or not self._lookup_client.find_vendors_list():
                return self._cache[normalized]

        vendor = None
        try:
            if not self._vendors_loaded:
                if not self._lookup_client.find_vendors_list():
                    self._cache[normalized] = None
                    return None
                self._lookup_client.load_vendors()
                self._vendors_loaded = True
            vendor = self._lookup_client.lookup(normalized)
        except Exception:
            vendor = None

        result = vendor.strip() if isinstance(vendor, str) else None
        self._cache[normalized] = result or None
        return self._cache[normalized]

    @staticmethod
    def _normalize_for_lookup(mac_address: Optional[str]) -> Optional[str]:
        normalized = normalize_mac(mac_address)
        if not normalized or not _NORMALIZED_MAC.fullmatch(normalized):
            return None
        first_octet = int(normalized[:2], 16)
        if first_octet & 1 or first_octet & 2:
            return None
        return normalized


VendorLookup = Callable[[Optional[str]], Optional[str]]