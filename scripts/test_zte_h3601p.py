#!/usr/bin/env python3
"""Safe real-router integration test script for ZTE H3601P authentication & collection.

Usage:
  python scripts/test_zte_h3601p.py --debug-login-token
  python scripts/test_zte_h3601p.py --debug-response --algo rsa_pkcs1v15_concat
  python scripts/test_zte_h3601p.py --algo sha256_concat

Configuration:
  Copy .env.example to .env and fill in your values:
    ZTE_ROUTER_URL      (e.g. https://192.168.2.253)
    ZTE_USERNAME        (e.g. admin)
    ZTE_PASSWORD        (e.g. your_router_password)
    ZTE_RSA_PUBLIC_KEY  (e.g. -----BEGIN PUBLIC KEY-----\\n...)

  Environment variables override .env values.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import os
import pathlib
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

# Ensure services package is importable when executed directly
repo_root = pathlib.Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from services.discovery.zte_h3601p_client import (
    ZTEH3601PClient,
    _sanitize_log_message,
    default_password_transform,
)


def load_dotenv(env_path: pathlib.Path | None = None) -> None:
    """Load variables from a .env file into os.environ.

    Existing environment variables are NOT overwritten, so real env vars
    always take precedence over .env values.
    """
    if env_path is None:
        env_path = repo_root / ".env"
    if not env_path.is_file():
        return

    with open(env_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            # Skip comments and blank lines
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Remove surrounding quotes if present
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            # Convert literal \n to real newlines (for RSA keys etc.)
            value = value.replace("\\n", "\n")
            # Don't overwrite existing env vars
            if key not in os.environ:
                os.environ[key] = value

ALGO_CHOICES = [
    "unverified",
    "rsa_pkcs1v15_concat",
    "rsa_pkcs1v15_plain",
    "rsa_pkcs1v15_sha256",
    "sha256_concat",
    "sha256_concat_upper",
    "sha256_double",
    "sha256_double_upper",
    "sha256_double_step1_upper",
    "sha256_token_concat",
    "sha256_token_concat_upper",
    "sha256_user_pass_token",
    "sha256_pass_user_token",
    "sha256_plain",
    "sha256_plain_upper",
    "md5_concat",
    "md5_concat_upper",
]


def sanitize_debug_response(body: str) -> str:
    """Sanitize sensitive session tokens and cookie values while preserving structure."""
    if not body:
        return ""
    body = re.sub(r"(<_sessionTOKEN>)(.*?)(</_sessionTOKEN>)", r"\1[REDACTED_TOKEN]\3", body, flags=re.IGNORECASE)
    body = re.sub(r"(<sessionTOKEN>)(.*?)(</sessionTOKEN>)", r"\1[REDACTED_TOKEN]\3", body, flags=re.IGNORECASE)
    body = re.sub(r"(<token>)(.*?)(</token>)", r"\1[REDACTED_TOKEN]\3", body, flags=re.IGNORECASE)

    body = re.sub(r'("_sessionTOKEN"\s*:\s*")([^"]+)(")', r"\1[REDACTED_TOKEN]\3", body, flags=re.IGNORECASE)
    body = re.sub(r'("sessionTOKEN"\s*:\s*")([^"]+)(")', r"\1[REDACTED_TOKEN]\3", body, flags=re.IGNORECASE)
    body = re.sub(r'("token"\s*:\s*")([^"]+)(")', r"\1[REDACTED_TOKEN]\3", body, flags=re.IGNORECASE)

    body = re.sub(r"(_sessionTOKEN=)[^&\s\"']+", r"\1[REDACTED_TOKEN]", body, flags=re.IGNORECASE)
    body = re.sub(r"(Password=)[^&\s\"']+", r"\1[REDACTED_PASSWORD]", body, flags=re.IGNORECASE)

    body = re.sub(r"(SID(_HTTPS)?=)[^;&\s]*", r"\1[REDACTED]", body, flags=re.IGNORECASE)
    body = re.sub(r"(Cookie:\s*)[^\r\n]*", r"\1[REDACTED]", body, flags=re.IGNORECASE)
    body = re.sub(r"(Authorization:\s*)[^\r\n]*", r"\1[REDACTED]", body, flags=re.IGNORECASE)
    return body


def run_debug_login_token(url: str, verify_tls: bool):
    """Perform GET login_token request with headers matching browser and print response diagnostics."""
    print("==================================================")
    print(" ZTE H3601P Debug Login Token Request ")
    print("==================================================")
    print(f"Target URL : {url}")
    print(f"Verify TLS : {verify_tls}")
    print("--------------------------------------------------")

    timestamp = int(time.time() * 1000)
    endpoint = f"/?_type=loginData&_tag=login_token&_={timestamp}"
    full_url = f"{url.rstrip('/')}{endpoint}"

    cookie_jar = http.cookiejar.CookieJar()
    handlers: list[urllib.request.BaseHandler] = [
        urllib.request.HTTPCookieProcessor(cookie_jar)
    ]

    if full_url.startswith("https"):
        ssl_context = ssl.create_default_context()
        if not verify_tls:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context))

    opener = urllib.request.build_opener(*handlers)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Sentinel/1.0",
        "Accept": "application/xml, text/xml, */*; q=0.01",
        "Referer": f"{url.rstrip('/')}/",
        "X-Requested-With": "XMLHttpRequest",
    }

    req = urllib.request.Request(full_url, headers=headers, method="GET")

    try:
        with opener.open(req, timeout=10.0) as resp:
            http_status = getattr(resp, "status", getattr(resp, "code", 200))
            content_type = resp.headers.get("Content-Type", "N/A")
            content_length = resp.headers.get("Content-Length", "N/A")
            final_url = resp.geturl()
            raw_body = resp.read().decode("utf-8", errors="replace")

            print(f"HTTP Status    : {http_status}")
            print(f"Content-Type   : {content_type}")
            print(f"Content-Length : {content_length}")
            print(f"Final URL      : {final_url}")
            print("\nResponse Body:")
            print("--------------------------------------------------")
            print(sanitize_debug_response(raw_body))
            print("--------------------------------------------------")
    except Exception as e:
        print(f"[ERROR] Request failed: {_sanitize_log_message(str(e))}")
        sys.exit(1)


def run_debug_response(url: str, username: str, password: str, algo: str, verify_tls: bool, rsa_public_key: str | None = None):
    """Execute full diagnostic sequence: GET /, get token, POST login_entry, GET dhcp & mesh endpoints."""
    print("==================================================")
    print(" ZTE H3601P Debug Response Diagnostics ")
    print("==================================================")
    print(f"Target URL : {url}")
    print(f"Username   : {username}")
    print(f"Algorithm  : {algo}")
    print(f"Verify TLS : {verify_tls}")
    print("--------------------------------------------------")

    base_url = url.rstrip("/")
    cookie_jar = http.cookiejar.CookieJar()
    handlers: list[urllib.request.BaseHandler] = [
        urllib.request.HTTPCookieProcessor(cookie_jar)
    ]

    if base_url.startswith("https"):
        ssl_context = ssl.create_default_context()
        if not verify_tls:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ssl_context))

    opener = urllib.request.build_opener(*handlers)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Sentinel/1.0",
        "Accept": "application/json, text/javascript, application/xml, text/xml, */*; q=0.01",
        "Referer": f"{base_url}/",
        "X-Requested-With": "XMLHttpRequest",
    }

    # Step 0: GET / (Session Init)
    print("\n--- STEP 0: GET / Session Initialization ---")
    page_session_token = None
    try:
        init_req = urllib.request.Request(f"{base_url}/", headers=headers, method="GET")
        with opener.open(init_req, timeout=10.0) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            match = re.search(r'id=["\']_sessionTOKEN["\']\s+value=["\']([^"\'\s]+)["\']', html, re.IGNORECASE)
            if match:
                page_session_token = match.group(1)
            print(f"Session Cookies: {len(cookie_jar)}")
            print(f"Page Token Found: {'YES' if page_session_token else 'NO'}")
    except Exception as e:
        print(f"[STEP 0 WARNING] Session init failed: {_sanitize_log_message(str(e))}")

    # Step 1a: GET login_entry -> sess_token (CSRF/_sessionTOKEN for POST)
    print("\n--- STEP 1a: GET login_entry (sess_token) ---")
    sess_token = page_session_token
    try:
        entry_url = f"{base_url}/?_type=loginData&_tag=login_entry"
        entry_req = urllib.request.Request(entry_url, headers=headers, method="GET")
        with opener.open(entry_req, timeout=10.0) as resp:
            raw_entry = resp.read().decode("utf-8", errors="replace")
            print("Response Body:")
            print(sanitize_debug_response(raw_entry))
            try:
                import json as _json
                entry_json = _json.loads(raw_entry)
                locking = int(entry_json.get("lockingTime") or 0)
                if locking != 0:
                    print(f"[STEP 1a ERROR] Router login locked for {locking} seconds. Wait and retry.")
                    sys.exit(1)
                if entry_json.get("sess_token"):
                    sess_token = str(entry_json["sess_token"])
            except Exception:
                pass
    except Exception as e:
        print(f"[STEP 1a ERROR] login_entry failed: {_sanitize_log_message(str(e))}")
        sys.exit(1)

    if not sess_token:
        print("[STEP 1a ERROR] Failed to obtain sess_token from login_entry.")
        sys.exit(1)
    print("Step 1a (sess_token) : SUCCESS")

    # Step 1b: GET login_token -> challenge used for password hash
    print("\n--- STEP 1b: GET login_token (challenge) ---")
    timestamp = int(time.time() * 1000)
    token_url = f"{base_url}/?_type=loginData&_tag=login_token&_={timestamp}"
    token_req = urllib.request.Request(token_url, headers=headers, method="GET")

    token_val = None
    try:
        with opener.open(token_req, timeout=10.0) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
            if raw_body.strip().startswith("<"):
                try:
                    root = ET.fromstring(raw_body)
                    if root.text and root.text.strip():
                        token_val = root.text.strip()
                except ET.ParseError:
                    pass
    except Exception as e:
        print(f"[STEP 1b ERROR] Token request failed: {_sanitize_log_message(str(e))}")
        sys.exit(1)

    if not token_val:
        print("[STEP 1b ERROR] Failed to obtain challenge token from router.")
        sys.exit(1)

    print("Step 1b (challenge token) : SUCCESS")

    # Step 2: POST login_entry
    derived_password = default_password_transform(password, token_val, algo, username, rsa_public_key=rsa_public_key)
    post_token = sess_token
    login_url = f"{base_url}/?_type=loginData&_tag=login_entry"
    form_data = {
        "Username": username,
        "Password": derived_password,
        "_sessionTOKEN": post_token,
        "action": "login",
    }
    encoded_data = urllib.parse.urlencode(form_data).encode("utf-8")
    post_headers = dict(headers)
    post_headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

    login_req = urllib.request.Request(login_url, data=encoded_data, headers=post_headers, method="POST")

    print("\n--- STEP 2: POST login_entry Diagnostics ---")
    try:
        with opener.open(login_req, timeout=10.0) as resp:
            status = getattr(resp, "status", getattr(resp, "code", 200))
            ctype = resp.headers.get("Content-Type", "N/A")
            clen = resp.headers.get("Content-Length", str(len(encoded_data)))
            raw_login = resp.read().decode("utf-8", errors="replace")

            print(f"HTTP Status    : {status}")
            print(f"Content-Type   : {ctype}")
            print(f"Content-Length : {clen}")
            print(f"Cookies Count  : {len(cookie_jar)}")
            print("Response Body:")
            print(sanitize_debug_response(raw_login))
    except Exception as e:
        print(f"[STEP 2 ERROR] login_entry failed: {_sanitize_log_message(str(e))}")

    # Step 3: menuView localNetStatus then dhcp4s_dhcphostinfo_m.lua
    print("\n--- STEP 3: menuView + dhcp4s_dhcphostinfo_m.lua Diagnostics ---")
    try:
        view_ts = int(time.time() * 1000)
        view_url = f"{base_url}/?_type=menuView&_tag=localNetStatus&_={view_ts}"
        with opener.open(urllib.request.Request(view_url, headers=headers, method="GET"), timeout=10.0) as resp:
            _ = resp.read()
            print(f"menuView localNetStatus : HTTP {getattr(resp, 'status', getattr(resp, 'code', 200))}")

        dhcp_timestamp = int(time.time() * 1000)
        dhcp_url = f"{base_url}/?_type=menuData&_tag=dhcp4s_dhcphostinfo_m.lua&_={dhcp_timestamp}"
        dhcp_req = urllib.request.Request(dhcp_url, headers=headers, method="GET")
        with opener.open(dhcp_req, timeout=10.0) as resp:
            status = getattr(resp, "status", getattr(resp, "code", 200))
            ctype = resp.headers.get("Content-Type", "N/A")
            clen = resp.headers.get("Content-Length", "N/A")
            raw_dhcp = resp.read().decode("utf-8", errors="replace")

            root_tag = "N/A"
            has_instance = "OBJ_DHCPHOSTINFO_ID" in raw_dhcp or "Instance" in raw_dhcp
            if raw_dhcp.strip().startswith("<"):
                try:
                    root = ET.fromstring(raw_dhcp)
                    root_tag = root.tag
                except ET.ParseError:
                    root_tag = "Malformed XML"

            print(f"HTTP Status    : {status}")
            print(f"Content-Type   : {ctype}")
            print(f"Content-Length : {clen}")
            print(f"Root XML Tag   : {root_tag}")
            print(f"Has Instances  : {has_instance}")
            print("Response Body Snippet (max 500 chars):")
            print(sanitize_debug_response(raw_dhcp[:500]))
    except Exception as e:
        print(f"[STEP 3 ERROR] DHCP request failed: {_sanitize_log_message(str(e))}")

    # Step 4: menuView mmTopology then topo_lua.lua
    print("\n--- STEP 4: menuView + topo_lua.lua Diagnostics ---")
    try:
        view_ts = int(time.time() * 1000)
        view_url = f"{base_url}/?_type=menuView&_tag=mmTopology&Menu3Location=0&_={view_ts}"
        with opener.open(urllib.request.Request(view_url, headers=headers, method="GET"), timeout=10.0) as resp:
            _ = resp.read()
            print(f"menuView mmTopology     : HTTP {getattr(resp, 'status', getattr(resp, 'code', 200))}")

        topo_timestamp = int(time.time() * 1000)
        topo_url = f"{base_url}/?_type=menuData&_tag=topo_lua.lua&_={topo_timestamp}"
        topo_req = urllib.request.Request(topo_url, headers=headers, method="GET")
        with opener.open(topo_req, timeout=10.0) as resp:
            status = getattr(resp, "status", getattr(resp, "code", 200))
            ctype = resp.headers.get("Content-Type", "N/A")
            clen = resp.headers.get("Content-Length", "N/A")
            raw_topo = resp.read().decode("utf-8", errors="replace")

            root_tag = "N/A"
            has_mesh_nodes = "master" in raw_topo or "slave" in raw_topo or "ad" in raw_topo
            if raw_topo.strip().startswith("<"):
                try:
                    root = ET.fromstring(raw_topo)
                    root_tag = root.tag
                except ET.ParseError:
                    root_tag = "Malformed XML"

            print(f"HTTP Status    : {status}")
            print(f"Content-Type   : {ctype}")
            print(f"Content-Length : {clen}")
            print(f"Root XML Tag   : {root_tag}")
            print(f"Has Mesh Nodes : {has_mesh_nodes}")
            print("Response Body Snippet (max 500 chars):")
            print(sanitize_debug_response(raw_topo[:500]))
    except Exception as e:
        print(f"[STEP 4 ERROR] Mesh request failed: {_sanitize_log_message(str(e))}")

    print("\n==================================================")
    print(" Debug Response Diagnostics Completed ")
    print("==================================================")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Integration test script for ZTE H3601P router authentication"
    )
    parser.add_argument(
        "--algo",
        choices=ALGO_CHOICES,
        default="unverified",
        help="Password transformation algorithm candidate (default: unverified)",
    )
    parser.add_argument(
        "--verify-tls",
        action="store_true",
        help="Enable strict TLS certificate verification (default: False for self-signed certificates)",
    )
    parser.add_argument(
        "--debug-login-token",
        action="store_true",
        help="Perform GET login_token request and print response diagnostics without authentication POST",
    )
    parser.add_argument(
        "--debug-response",
        action="store_true",
        help="Execute full diagnostic sequence (token, login_entry, dhcp, mesh) and print sanitized response bodies",
    )
    args = parser.parse_args(argv)

    # Load .env file (real env vars take precedence)
    load_dotenv()

    url = os.getenv("ZTE_ROUTER_URL")
    username = os.getenv("ZTE_USERNAME")
    password = os.getenv("ZTE_PASSWORD")
    rsa_pubkey = os.getenv("ZTE_RSA_PUBLIC_KEY")

    if not url:
        print("[ERROR] ZTE_ROUTER_URL is required. Set it in .env or as an environment variable.")
        print("  Hint: copy .env.example to .env and fill in your values.")
        sys.exit(1)

    if args.debug_login_token:
        run_debug_login_token(url, args.verify_tls)
        sys.exit(0)

    if args.debug_response:
        if not username or not password:
            print("[ERROR] ZTE_USERNAME and ZTE_PASSWORD are required for --debug-response. Set them in .env.")
            sys.exit(1)
        run_debug_response(url, username, password, args.algo, args.verify_tls, rsa_pubkey)
        sys.exit(0)

    if not username or not password:
        print("[ERROR] Missing required credentials. Set them in .env or as environment variables:")
        if not username:
            print("  - ZTE_USERNAME   (e.g., admin)")
        if not password:
            print("  - ZTE_PASSWORD   (e.g., your_password)")
        print("  Hint: copy .env.example to .env and fill in your values.")
        sys.exit(1)

    print("==================================================")
    print(" ZTE H3601P Safe Real-Router Integration Test ")
    print("==================================================")
    print(f"Target URL : {url}")
    print(f"Username   : {username}")
    print(f"Algorithm  : {args.algo}")
    print(f"Verify TLS : {args.verify_tls}")
    print("--------------------------------------------------")

    # Step 1: Reachability & Token Retrieval
    client = None
    try:
        client = ZTEH3601PClient(
            url=url,
            username=username,
            password=password,
            verify_tls=args.verify_tls,
            password_algorithm=args.algo if args.algo != "unverified" else "sha256_concat",
            rsa_public_key=rsa_pubkey,
        )
    except Exception as e:
        print(f"Router reachable   : NO ({_sanitize_log_message(str(e))})")
        print("Token obtained     : NO")
        print("Login succeeded    : NO")
        sys.exit(1)

    token_obtained = False
    try:
        client.get_login_token()
        token_obtained = True
        print("Router reachable   : YES")
        print("Token obtained     : YES")
    except Exception as e:
        print("Router reachable   : YES")
        print(f"Token obtained     : NO ({_sanitize_log_message(str(e))})")
        print("Login succeeded    : NO")
        sys.exit(1)

    if args.algo == "unverified":
        print("\n[NOTICE] Password transformation algorithm is set to 'unverified'.")
        print("Login submission was skipped to avoid sending unverified credentials.")
        print("Specify a candidate algorithm via --algo (e.g. --algo rsa_pkcs1v15_concat or --algo rsa_pkcs1v15_plain) to attempt login.")
        sys.exit(0)

    # Step 2: Attempt Login
    login_succeeded = False
    http_status = "200 OK"
    response_classification = "unknown"

    try:
        login_succeeded = client.login()
        response_classification = "success" if login_succeeded else "auth_failed"
    except Exception as e:
        sanitized_err = _sanitize_log_message(str(e))
        response_classification = f"auth_failed ({sanitized_err})"

    print(f"Login succeeded    : {'YES' if login_succeeded else 'NO'}")
    print(f"HTTP status        : {http_status}")
    print(f"Classification     : {response_classification}")
    print("--------------------------------------------------")

    if not login_succeeded:
        print("\n[DIAGNOSTICS] Authentication failed with algorithm candidate '%s'." % args.algo)
        print("To determine the exact password transformation used by your ZTE H3601P firmware:")
        print("1. Open Chrome DevTools (F12) -> Network tab.")
        print("2. Navigate to %s and submit the login form." % url)
        print("3. Check loaded static JavaScript assets (e.g. login.js, sha256.js).")
        print("4. Locate the Password calculation function (e.g., hex_sha256 or similar).")
        print("5. Re-run this script with the corresponding --algo option once identified.\n")
        sys.exit(1)

    # Step 3: Fetch DHCP & Mesh Data on Successful Login
    print("\nFetching DHCP Clients & Mesh Topology...")

    # Show post-login session state for diagnostics
    print(f"\n[Session State]")
    print(f"  Authenticated   : {client._is_authenticated}")
    print(f"  Cookies         : {len(client.cookie_jar)} cookie(s)")
    for cookie in client.cookie_jar:
        print(f"    - {cookie.name}={cookie.value[:8]}... (domain={cookie.domain}, path={cookie.path})")
    if client._page_session_token:
        print(f"  Page Token      : {client._page_session_token[:8]}... (length={len(client._page_session_token)})")
    if client._session_token:
        print(f"  Session Token   : {client._session_token[:8]}... (length={len(client._session_token)})")

    dhcp_clients = []
    mesh_topology: Any = None

    try:
        dhcp_clients = client.get_dhcp_clients()
        print(f"\n[DHCP Clients] Total Discovered: {len(dhcp_clients)}")
        for idx, device in enumerate(dhcp_clients, 1):
            ip = device.ip_address or "N/A"
            mac = device.mac_address or "N/A"
            hostname = device.hostname or "N/A"
            interface = device.interface or "N/A"
            lease = device.remaining_lease or "N/A"
            print(f"  {idx}. IP: {ip:<15} MAC: {mac:<17} Hostname: {hostname:<20} Interface: {interface:<10} Lease: {lease}")
    except Exception as e:
        print(f"[DHCP Clients Error] {_sanitize_log_message(str(e))}")

    try:
        mesh_topology = client.get_mesh_topology()
        print(f"\n[Mesh Topology] Data:")
        if isinstance(mesh_topology, list):
            print(f"  Total Nodes Discovered: {len(mesh_topology)}")
            for idx, node in enumerate(mesh_topology, 1):
                print(
                    f"  {idx}. [{node.node_name}] IP: {node.ip_address or 'N/A':<15} "
                    f"MAC: {node.mac_address or 'N/A':<17} Hostname: {node.hostname or 'N/A':<20} "
                    f"Parent: {node.parent_mac or 'N/A':<17} Connection: {node.connection_type or 'N/A'}"
                )
        else:
            print(f"  Data: {type(mesh_topology)}")
    except Exception as e:
        print(f"[Mesh Topology Error] {_sanitize_log_message(str(e))}")

    print("\n==================================================")
    print(" Real-Router Integration Test Completed ")
    print("==================================================")


if __name__ == "__main__":
    main()
