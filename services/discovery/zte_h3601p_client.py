from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import json
import logging
import os
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Sequence

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    HAVE_CRYPTOGRAPHY = True
except ImportError:
    HAVE_CRYPTOGRAPHY = False

from services.discovery.zte_h3601p_parser import (
    ZTEDHCPClient,
    ZTEMeshClient,
    parse_dhcp_clients_xml,
    parse_mesh_topology,
)

logger = logging.getLogger("sentinel.services.discovery.zte_h3601p_client")


def _sanitize_log_message(msg: str) -> str:
    """Sanitize sensitive information from log messages."""
    if not msg:
        return ""
    # Mask passwords, tokens, and cookies
    msg = re.sub(r"(Password=)[^&]*", r"\1[REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"(_sessionTOKEN[=:\s]+)[^\s&\"']*", r"\1[REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"(sess_token[=:\s\"]+)[^\s&\"']*", r"\1[REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"(SID(_HTTPS)?=)[^;&\s]*", r"\1[REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"(Cookie:\s*)[^\r\n]*", r"\1[REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"(Authorization:\s*)[^\r\n]*", r"\1[REDACTED]", msg, flags=re.IGNORECASE)
    return msg


def rsa_encrypt_pkcs1v15(pub_key_pem: str, plaintext: str) -> str:
    """Encrypt plaintext using RSA public key with PKCS#1 v1.5 padding matching JSEncrypt."""
    if not HAVE_CRYPTOGRAPHY:
        raise RuntimeError("cryptography package is required for RSA encryption")
    
    clean_pem = pub_key_pem.replace("\\n", "\n").strip()
    pem_bytes = clean_pem.encode("utf-8")
    if not pem_bytes.startswith(b"-----BEGIN"):
        pem_bytes = (
            b"-----BEGIN PUBLIC KEY-----\n" +
            pem_bytes +
            b"\n-----END PUBLIC KEY-----"
        )
    public_key = serialization.load_pem_public_key(pem_bytes)
    encrypted = public_key.encrypt(
        plaintext.encode("utf-8"),
        padding.PKCS1v15()
    )
    return base64.b64encode(encrypted).decode("utf-8")


def default_password_transform(
    password: str,
    token: str,
    algo: str = "sha256_concat",
    username: Optional[str] = None,
    rsa_public_key: Optional[str] = None,
) -> str:
    """Transform raw password and session token into credential-derived value.
    
    ZTE H3601P g_loginToken implementation:
    var SHA256Password = sha256(Password + xmlObj);
    where xmlObj is the token text from GET login_token XML response.
    
    Supported algorithms:
    - 'sha256_concat': SHA256(password + token) lowercase hex (ZTE H3601P default)
    - 'sha256_concat_upper': SHA256(password + token) UPPERCASE hex
    - 'sha256_double': SHA256(SHA256(password) + token) lowercase hex
    - 'sha256_double_upper': SHA256(SHA256(password) + token) UPPERCASE hex
    - 'rsa_pkcs1v15_concat': RSA PKCS#1 v1.5 encrypt(password + token)
    """
    uname = username or ""
    pub_key = rsa_public_key or os.getenv("ZTE_RSA_PUBLIC_KEY")

    if algo == "sha256_concat":
        return hashlib.sha256((password + token).encode("utf-8")).hexdigest()
    elif algo == "rsa_pkcs1v15_concat":
        if not pub_key:
            raise ValueError("RSA public key is required for rsa_pkcs1v15_concat (specify rsa_public_key or ZTE_RSA_PUBLIC_KEY env var)")
        return rsa_encrypt_pkcs1v15(pub_key, password + token)
    elif algo == "rsa_pkcs1v15_plain":
        if not pub_key:
            raise ValueError("RSA public key is required for rsa_pkcs1v15_plain (specify rsa_public_key or ZTE_RSA_PUBLIC_KEY env var)")
        return rsa_encrypt_pkcs1v15(pub_key, password)
    elif algo == "rsa_pkcs1v15_sha256":
        if not pub_key:
            raise ValueError("RSA public key is required for rsa_pkcs1v15_sha256 (specify rsa_public_key or ZTE_RSA_PUBLIC_KEY env var)")
        sha_val = hashlib.sha256((password + token).encode("utf-8")).hexdigest()
        return rsa_encrypt_pkcs1v15(pub_key, sha_val)
    elif algo == "sha256_concat_upper":
        return hashlib.sha256((password + token).encode("utf-8")).hexdigest().upper()
    elif algo == "sha256_double":
        first = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hashlib.sha256((first + token).encode("utf-8")).hexdigest()
    elif algo == "sha256_double_upper":
        first = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hashlib.sha256((first + token).encode("utf-8")).hexdigest().upper()
    elif algo == "sha256_double_step1_upper":
        first = hashlib.sha256(password.encode("utf-8")).hexdigest().upper()
        return hashlib.sha256((first + token).encode("utf-8")).hexdigest().upper()
    elif algo == "sha256_token_concat":
        return hashlib.sha256((token + password).encode("utf-8")).hexdigest()
    elif algo == "sha256_token_concat_upper":
        return hashlib.sha256((token + password).encode("utf-8")).hexdigest().upper()
    elif algo == "sha256_user_pass_token":
        return hashlib.sha256((uname + password + token).encode("utf-8")).hexdigest().upper()
    elif algo == "sha256_pass_user_token":
        return hashlib.sha256((password + uname + token).encode("utf-8")).hexdigest().upper()
    elif algo == "sha256_plain":
        return hashlib.sha256(password.encode("utf-8")).hexdigest()
    elif algo == "sha256_plain_upper":
        return hashlib.sha256(password.encode("utf-8")).hexdigest().upper()
    elif algo == "md5_concat":
        return hashlib.md5((password + token).encode("utf-8")).hexdigest()
    elif algo == "md5_concat_upper":
        return hashlib.md5((password + token).encode("utf-8")).hexdigest().upper()
    else:
        # Default: sha256_concat
        return hashlib.sha256((password + token).encode("utf-8")).hexdigest()


class ZTEH3601PClient:
    """Authenticated client for ZTE H3601P V9.0 (firmware V9.0.0P2_VN1) router."""

    def __init__(
        self,
        url: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify_tls: bool = False,
        timeout: float = 10.0,
        max_retries: int = 3,
        password_transform: Optional[Callable[[str, str], str]] = None,
        password_algorithm: str = "sha256_concat",
        rsa_public_key: Optional[str] = None,
    ):
        self.url = (url or os.getenv("ZTE_ROUTER_URL") or "").rstrip("/")
        self.username = username or os.getenv("ZTE_USERNAME")
        self.password = password or os.getenv("ZTE_PASSWORD")
        self.verify_tls = verify_tls
        self.timeout = timeout
        self.max_retries = max_retries
        self.password_transform = password_transform
        self.password_algorithm = password_algorithm
        self.rsa_public_key = rsa_public_key or os.getenv("ZTE_RSA_PUBLIC_KEY")

        if not self.url:
            raise ValueError("ZTE router URL is required (specify url parameter or ZTE_ROUTER_URL env var)")
        if not self.username:
            raise ValueError("ZTE username is required (specify username parameter or ZTE_USERNAME env var)")
        if not self.password:
            raise ValueError("ZTE password is required (specify password parameter or ZTE_PASSWORD env var)")

        self.cookie_jar = http.cookiejar.CookieJar()
        self._is_authenticated = False
        self._session_token: Optional[str] = None
        self._page_session_token: Optional[str] = None
        self._missing_menu_views: set[str] = set()
        self._missing_menu_data: set[str] = set()
        self._menu_context_ready = False

        self._init_opener()

    def _init_opener(self):
        """Initialize urllib OpenerDirector with cookie jar and SSL options."""
        handlers: list[urllib.request.BaseHandler] = [
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        ]

        if self.url.startswith("https"):
            ssl_context = ssl.create_default_context()
            if not self.verify_tls:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=ssl_context))

        self._opener = urllib.request.build_opener(*handlers)

    def __repr__(self) -> str:
        return (
            f"ZTEH3601PClient(url={self.url!r}, username={self.username!r}, "
            f"authenticated={self._is_authenticated}, verify_tls={self.verify_tls})"
        )

    def __str__(self) -> str:
        return f"ZTEH3601PClient({self.url}, authenticated={self._is_authenticated})"

    def _make_request(
        self,
        endpoint_path: str,
        method: str = "GET",
        params: Optional[Dict[str, str]] = None,
        data: Optional[Dict[str, str]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> str:
        """Make an HTTP request with retry logic and non-sensitive logging."""
        full_url = f"{self.url}/{endpoint_path.lstrip('/')}"
        if params:
            query_str = urllib.parse.urlencode(params)
            full_url = f"{full_url}?{query_str}" if "?" not in full_url else f"{full_url}&{query_str}"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, application/xml, text/xml, */*; q=0.01",
            "Referer": f"{self.url}/",
        }
        if extra_headers:
            headers.update(extra_headers)

        encoded_data = None
        if data is not None:
            encoded_data = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"

        req = urllib.request.Request(full_url, data=encoded_data, headers=headers, method=method)

        last_exception = None
        for attempt in range(1, self.max_retries + 1):
            try:
                log_url = _sanitize_log_message(full_url)
                logger.debug("Request attempt %d/%d to %s", attempt, self.max_retries, log_url)

                with self._opener.open(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    return body
            except urllib.error.HTTPError as exc:
                last_exception = exc
                sanitized_exc = _sanitize_log_message(str(exc))
                # Permanent 4xx: no retry, keep logs quiet for expected missing tags.
                if exc.code in (404, 400, 401, 403, 405, 410):
                    logger.debug("Request failed with HTTP %s: %s", exc.code, sanitized_exc)
                    break
                logger.warning(
                    "Request attempt %d/%d failed: %s",
                    attempt,
                    self.max_retries,
                    sanitized_exc,
                )
                if attempt < self.max_retries:
                    time.sleep(0.2 * (2 ** (attempt - 1)))
            except Exception as exc:
                last_exception = exc
                sanitized_exc = _sanitize_log_message(str(exc))
                logger.warning(
                    "Request attempt %d/%d failed: %s",
                    attempt,
                    self.max_retries,
                    sanitized_exc,
                )
                if attempt < self.max_retries:
                    time.sleep(0.2 * (2 ** (attempt - 1)))

        raise RuntimeError(f"HTTP request to ZTE router failed after {self.max_retries} attempts: {last_exception}")

    def init_session(self):
        """Fetch main page GET / to establish session cookies and extract initial page token."""
        logger.info("Initializing session with GET /")
        try:
            html_body = self._make_request("/", method="GET")
            match = re.search(r'id=["\']_sessionTOKEN["\']\s+value=["\']([^"\'\s]+)["\']', html_body, re.IGNORECASE)
            if not match:
                match = re.search(r'name=["\']_sessionTOKEN["\']\s+value=["\']([^"\'\s]+)["\']', html_body, re.IGNORECASE)
            if match:
                self._page_session_token = match.group(1)
                logger.debug("Extracted _sessionTOKEN from initial page HTML")
        except Exception as exc:
            logger.warning("Session initialization GET / failed: %s", _sanitize_log_message(str(exc)))

    def get_session_token(self) -> str:
        """Obtain CSRF/session token from GET login_entry (required for login POST).

        ZTE firmwares expose ``sess_token`` via ``/?_type=loginData&_tag=login_entry``.
        This value is distinct from the login challenge token used for password hashing.
        """
        logger.info("Retrieving session token from login_entry")
        response_body = self._make_request(
            "/",
            method="GET",
            params={"_type": "loginData", "_tag": "login_entry"},
        )
        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Failed to parse login_entry session token response") from exc

        if not isinstance(parsed, dict):
            raise RuntimeError("Unexpected login_entry response format")

        locking_time = self._as_int(parsed.get("lockingTime"), default=0)
        if locking_time != 0:
            raise RuntimeError(
                f"Router login is locked for {locking_time} seconds "
                "(too many failed login attempts). Wait and retry."
            )

        sess_token = parsed.get("sess_token")
        if not sess_token:
            raise RuntimeError("Session token unavailable from login_entry response")

        self._page_session_token = str(sess_token)
        return self._page_session_token

    @staticmethod
    def _as_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def get_login_token(self) -> str:
        """Step 1: Obtain login challenge token from router (used for password hashing)."""
        timestamp = int(time.time() * 1000)
        params = {
            "_type": "loginData",
            "_tag": "login_token",
            "_": str(timestamp),
        }
        logger.info("Retrieving login token from router")
        response_body = self._make_request("/", method="GET", params=params)

        token = None

        # 1. Primary: XML parsing (<ajax_response_xml_root>TOKEN</ajax_response_xml_root>)
        if response_body and response_body.strip().startswith("<"):
            try:
                root = ET.fromstring(response_body)
                tag_name = root.tag.rsplit("}", 1)[-1]
                if tag_name == "ajax_response_xml_root":
                    if root.text and root.text.strip():
                        token = root.text.strip()
            except ET.ParseError:
                pass

        # 2. Fallback: JSON parsing for backward compatibility with alternative formats
        if not token:
            try:
                parsed = json.loads(response_body)
                if isinstance(parsed, dict):
                    token = parsed.get("_sessionTOKEN") or parsed.get("sessionTOKEN") or parsed.get("token")
            except json.JSONDecodeError:
                pass

        # 3. Fallback: Regex extraction
        if not token:
            match = re.search(r'["\']?_sessionTOKEN["\']?\s*[:=]\s*["\']([^"\'\s]+)["\']', response_body)
            if match:
                token = match.group(1)

        if not token:
            raise RuntimeError("Failed to extract session token from login_token response")

        self._session_token = token
        return token

    def _transform_password(self, password: str, token: str) -> str:
        """Apply password transformation function."""
        if self.password_transform:
            return self.password_transform(password, token)
        return default_password_transform(
            password,
            token,
            self.password_algorithm,
            self.username,
            rsa_public_key=self.rsa_public_key,
        )

    def login(self) -> bool:
        """Authenticate session with ZTE H3601P router.

        Correct token usage:
        - ``sess_token`` from GET ``login_entry`` -> form field ``_sessionTOKEN``
        - challenge from GET ``login_token`` -> password hash input
        """
        logger.info("Starting authentication flow for user %s", self.username)

        # Reset cookie jar so a previous anonymous/locked session cannot poison login.
        self.cookie_jar.clear()
        self._init_opener()
        self._is_authenticated = False
        self._session_token = None
        self._page_session_token = None
        self._menu_context_ready = False

        self.init_session()
        post_session_token = self.get_session_token()
        challenge_token = self.get_login_token()
        derived_password = self._transform_password(self.password, challenge_token)

        params = {
            "_type": "loginData",
            "_tag": "login_entry",
        }
        form_data = {
            "Username": self.username,
            "Password": derived_password,
            "_sessionTOKEN": post_session_token,
            "action": "login",
        }

        response_body = self._make_request("/", method="POST", params=params, data=form_data)

        body_success = False
        login_err_msg = ""
        need_refresh = False
        locking_time = 0
        prompt_msg = ""

        try:
            parsed = json.loads(response_body)
            if isinstance(parsed, dict):
                new_sess_token = parsed.get("sess_token")
                if new_sess_token:
                    self._session_token = str(new_sess_token)
                    self._page_session_token = str(new_sess_token)

                login_need_refresh = parsed.get("login_need_refresh")
                login_err_msg = str(parsed.get("loginErrMsg") or "")
                prompt_msg = str(parsed.get("promptMsg") or "")
                locking_time = self._as_int(parsed.get("lockingTime"), default=0)

                if locking_time != 0:
                    body_success = False
                elif login_err_msg:
                    body_success = False
                elif "fail" in prompt_msg.lower() and login_need_refresh not in (True, "true", 1, "1"):
                    body_success = False
                elif login_need_refresh in (True, "true", 1, "1"):
                    body_success = True
                    need_refresh = True
                elif login_need_refresh in (False, "false", 0, "0") and new_sess_token:
                    # Some firmwares return refresh=false on success.
                    body_success = True
                    need_refresh = True
                elif new_sess_token and not login_err_msg and "lockingTime" not in parsed:
                    body_success = True
                    need_refresh = True
        except json.JSONDecodeError:
            if response_body and response_body.strip().startswith("<"):
                try:
                    root = ET.fromstring(response_body)
                    tag_name = root.tag.rsplit("}", 1)[-1]
                    root_text = (root.text or "").strip().lower()
                    if tag_name == "ajax_response_xml_root":
                        if root_text in ("success", "0", "ok", "true"):
                            body_success = True
                            need_refresh = True
                        elif root_text in ("fail", "error", "1001", "1002", "invalid", "unauthorized", "login"):
                            body_success = False
                except ET.ParseError:
                    pass

        has_session_cookie = any(
            cookie.name in ("SID", "SID_HTTPS", "SID_HTTPS_", "_sessionTOKEN", "sessionID")
            or cookie.name.startswith("SID")
            for cookie in self.cookie_jar
        )

        if body_success and (has_session_cookie or self._session_token):
            self._is_authenticated = True
            logger.info("Authentication successful for user %s", self.username)
            if need_refresh:
                logger.info("Login requires page refresh, performing session reload")
                self._post_login_refresh()
            return True

        self._is_authenticated = False
        if locking_time != 0:
            detail = f"router locked for {locking_time} seconds"
        else:
            detail = login_err_msg or prompt_msg or "authentication rejected"
        logger.error("Authentication failed for user %s (Error: %s)", self.username, detail)
        raise RuntimeError(f"Login failed: Router rejected credentials ({detail})")

    def _post_login_refresh(self):
        """Replicate browser page reload after login_need_refresh.
        
        The ZTE g_loginToken JS does: top.location.href = top.location.href
        This full page reload re-establishes the session context needed for
        subsequent menuData AJAX requests (DHCP, mesh, etc.).
        """
        try:
            html_body = self._make_request("/", method="GET")
            # Extract updated _sessionTOKEN from refreshed page
            match = re.search(
                r'id=["\']_sessionTOKEN["\']\s+value=["\']([^"\'\s]+)["\']',
                html_body,
                re.IGNORECASE,
            )
            if not match:
                match = re.search(
                    r'name=["\']_sessionTOKEN["\']\s+value=["\']([^"\'\s]+)["\']',
                    html_body,
                    re.IGNORECASE,
                )
            if match:
                self._page_session_token = match.group(1)
                logger.debug("Updated page session token after login refresh")
        except Exception as exc:
            logger.warning(
                "Post-login page refresh failed: %s",
                _sanitize_log_message(str(exc)),
            )

    def _is_session_expired(self, response_body: str) -> bool:
        """Check if response indicates an expired or unauthenticated session."""
        if not response_body or not response_body.strip():
            return False

        lower_body = response_body.lower()
        if "session expired" in lower_body or "sessiontimeout" in lower_body or "err_code_1001" in lower_body:
            return True
        if "<if_errorstr>" in lower_body and "unauthorized" in lower_body:
            return True

        try:
            root = ET.fromstring(response_body)
            tag_name = root.tag.rsplit("}", 1)[-1]
            if tag_name == "ajax_response_xml_root":
                root_text = (root.text or "").strip().lower()
                if root_text in ("login", "1001", "unauthorized", "fail", "error", "sessiontimeout"):
                    return True
                error_str = root.findtext("IF_ERRORSTR") or root.findtext(".//IF_ERRORSTR")
                if error_str and error_str.strip().lower() in ("sessiontimeout", "login", "unauthorized", "fail"):
                    return True
        except ET.ParseError:
            pass

        try:
            parsed = json.loads(response_body)
            if isinstance(parsed, dict):
                if parsed.get("prompt") == "login" or parsed.get("error") in (401, 1001):
                    return True
                if parsed.get("loginErrMsg"):
                    return True
        except json.JSONDecodeError:
            pass

        return False

    # ZTE web UI requires a menuView page context before menuData returns
    # real payload. H3601P V9 uses localNetStatus; mmTopology/topo_lua.lua 404.
    _MENU_DATA_VIEWS: Dict[str, Dict[str, Any]] = {
        "dhcp4s_dhcphostinfo_m.lua": {
            "view_tag": "localNetStatus",
            "alt_view_tags": (),
        },
        "accessdev_landevs_lua.lua": {
            "view_tag": "localNetStatus",
            "alt_view_tags": (),
        },
        "accessdev_ssiddev_lua.lua": {
            "view_tag": "localNetStatus",
            "alt_view_tags": (),
        },
        "topo_lua.lua": {
            "view_tag": "mmTopology",
            "view_params": {"Menu3Location": "0"},
            "alt_view_tags": (),
        },
    }

    def _prime_menu_view(
        self,
        view_tag: str,
        extra_params: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Navigate to a menu page context. Returns False if the view tag is missing (404)."""
        if view_tag in self._missing_menu_views:
            return False
        timestamp = int(time.time() * 1000)
        params: Dict[str, str] = {
            "_type": "menuView",
            "_tag": view_tag,
            "_": str(timestamp),
        }
        if extra_params:
            params.update(extra_params)
        logger.debug("Priming menuView context with tag %s", view_tag)
        try:
            self._make_request("/", method="GET", params=params)
            return True
        except RuntimeError as exc:
            if "404" in str(exc):
                self._missing_menu_views.add(view_tag)
                logger.debug("menuView tag %s not found (404)", view_tag)
                return False
            raise

    def _ensure_local_net_context(self) -> None:
        """Prime localNetStatus once per authenticated session."""
        if self._menu_context_ready or "localNetStatus" in self._missing_menu_views:
            return
        if self._prime_menu_view("localNetStatus"):
            self._menu_context_ready = True

    def _execute_authenticated_request(
        self,
        endpoint_tag: str,
        view_tag: Optional[str] = None,
        view_params: Optional[Dict[str, str]] = None,
    ) -> str:
        """Execute menuData request, optionally after menuView priming, with auto re-auth."""
        if not self._is_authenticated:
            self.login()

        def _fetch() -> str:
            if view_tag == "localNetStatus":
                self._ensure_local_net_context()
            elif view_tag:
                self._prime_menu_view(view_tag, view_params)
            timestamp = int(time.time() * 1000)
            params = {
                "_type": "menuData",
                "_tag": endpoint_tag,
                "_": str(timestamp),
            }
            return self._make_request("/", method="GET", params=params)

        try:
            body = _fetch()
            if self._is_session_expired(body):
                logger.info("Session expired for tag %s, re-authenticating...", endpoint_tag)
                self.login()
                body = _fetch()
            return body
        except Exception as exc:
            message = _sanitize_log_message(str(exc))
            if "404" in message:
                self._missing_menu_data.add(endpoint_tag)
                raise
            logger.warning(
                "Error querying tag %s, attempting re-authentication: %s",
                endpoint_tag,
                message,
            )
            self.login()
            return _fetch()

    def _fetch_menu_data_with_views(self, endpoint_tag: str) -> str:
        """Fetch menuData trying primary then alternate menuView page contexts."""
        view_cfg = self._MENU_DATA_VIEWS.get(endpoint_tag, {})
        view_tag = view_cfg.get("view_tag")
        view_params = view_cfg.get("view_params")
        alt_views = tuple(view_cfg.get("alt_view_tags") or ())

        body = self._execute_authenticated_request(
            endpoint_tag,
            view_tag=view_tag,
            view_params=view_params,
        )
        if not self._looks_like_empty_menu_payload(body) or not alt_views:
            return body

        for alt_tag in alt_views:
            logger.info(
                "Primary menuView %s yielded empty payload for %s; trying %s",
                view_tag,
                endpoint_tag,
                alt_tag,
            )
            body = self._execute_authenticated_request(
                endpoint_tag,
                view_tag=alt_tag,
                view_params=view_params,
            )
            if not self._looks_like_empty_menu_payload(body):
                return body
        return body

    @staticmethod
    def _looks_like_empty_menu_payload(body: str) -> bool:
        """Return True when menuData response has no usable host/mesh content."""
        if not body or not body.strip():
            return True
        lower = body.lower()
        if "obj_dhcphostinfo_id" in lower or "obj_accessdev_id" in lower:
            return False
        if any(token in lower for token in ('"ad"', "<ad>", "<master>", '"master"', "<slave>", '"slave"')):
            return False
        if "sessiontimeout" in lower or lower.strip() in (
            "<ajax_response_xml_root></ajax_response_xml_root>",
            "<ajax_response_xml_root/>",
        ):
            return True
        if body.strip().startswith("<") and "instance" not in lower and "paraname" not in lower:
            return True
        return False

    @staticmethod
    def _is_usable_host(ip_address: Optional[str], mac_address: Optional[str]) -> bool:
        """Drop placeholder/invalid router host rows (e.g. 0.0.0.0)."""
        ip = (ip_address or "").strip()
        mac = (mac_address or "").strip()
        if not mac and (not ip or ip in ("0.0.0.0", "::")):
            return False
        if ip in ("0.0.0.0", "::"):
            return False
        return bool(ip or mac)

    def get_dhcp_clients(self) -> List[ZTEDHCPClient]:
        """Fetch and parse DHCP/LAN clients from the best available endpoint."""
        logger.info("Fetching DHCP/LAN clients from ZTE router")
        endpoint_candidates = (
            ("dhcp4s_dhcphostinfo_m.lua", ("OBJ_DHCPHOSTINFO_ID",)),
            ("accessdev_landevs_lua.lua", ("OBJ_ACCESSDEV_ID", "OBJ_DHCPHOSTINFO_ID")),
            ("accessdev_ssiddev_lua.lua", ("OBJ_ACCESSDEV_ID", "OBJ_WLAN_AD_ID")),
        )
        last_error: Optional[Exception] = None
        for endpoint_tag, object_ids in endpoint_candidates:
            if endpoint_tag in self._missing_menu_data:
                continue
            try:
                raw_xml = self._fetch_menu_data_with_views(endpoint_tag)
                if self._is_session_expired(raw_xml):
                    last_error = RuntimeError(f"{endpoint_tag} returned SessionTimeout")
                    continue
                return [
                    client
                    for client in parse_dhcp_clients_xml(raw_xml, object_ids=object_ids)
                    if self._is_usable_host(client.ip_address, client.mac_address)
                ]
            except Exception as exc:
                last_error = exc
                if "404" in str(exc):
                    self._missing_menu_data.add(endpoint_tag)
                    logger.debug(
                        "DHCP candidate %s not present (404)",
                        endpoint_tag,
                    )
                    continue
                logger.warning(
                    "DHCP candidate %s failed: %s",
                    endpoint_tag,
                    _sanitize_log_message(str(exc)),
                )
        raise RuntimeError(
            f"Unable to fetch DHCP/LAN clients from router: {_sanitize_log_message(str(last_error))}"
        )

    def get_mesh_topology(self) -> List[ZTEMeshClient]:
        """Fetch and parse Mesh topology, falling back to LAN/Wi-Fi client lists if needed."""
        logger.info("Fetching Mesh topology from ZTE router")
        if "topo_lua.lua" not in self._missing_menu_data:
            try:
                raw_payload = self._execute_authenticated_request("topo_lua.lua")
                if not self._is_session_expired(raw_payload) and not self._looks_like_empty_menu_payload(raw_payload):
                    return parse_mesh_topology(raw_payload)
                self._missing_menu_data.add("topo_lua.lua")
            except Exception as exc:
                if "404" in str(exc):
                    self._missing_menu_data.add("topo_lua.lua")
                logger.debug(
                    "topo_lua.lua unavailable (%s); using access-device endpoints",
                    _sanitize_log_message(str(exc)),
                )

        # Fallback: synthesize topology-like records from LAN + Wi-Fi device lists.
        # H3601P V9 commonly exposes clients here instead of topo_lua.lua.
        clients: List[ZTEMeshClient] = []
        seen_macs: set[str] = set()
        for endpoint_tag, object_ids, node_name in (
            ("accessdev_landevs_lua.lua", ("OBJ_ACCESSDEV_ID",), "lan"),
            ("accessdev_ssiddev_lua.lua", ("OBJ_ACCESSDEV_ID", "OBJ_WLAN_AD_ID"), "wlan"),
        ):
            try:
                raw_xml = self._fetch_menu_data_with_views(endpoint_tag)
                if self._is_session_expired(raw_xml):
                    continue
                for device in parse_dhcp_clients_xml(raw_xml, object_ids=object_ids):
                    if not self._is_usable_host(device.ip_address, device.mac_address):
                        continue
                    mac_key = (device.mac_address or "").lower()
                    if mac_key and mac_key in seen_macs:
                        continue
                    if mac_key:
                        seen_macs.add(mac_key)
                    clients.append(
                        ZTEMeshClient(
                            ip_address=device.ip_address,
                            mac_address=device.mac_address,
                            hostname=device.hostname,
                            node_name=node_name,
                            connection_type=device.interface or node_name.upper(),
                            parent_mac=None,
                            rssi=None,
                            raw=device.raw,
                        )
                    )
            except Exception as exc:
                logger.debug(
                    "Mesh fallback candidate %s failed: %s",
                    endpoint_tag,
                    _sanitize_log_message(str(exc)),
                )
        if clients:
            return clients
        raise RuntimeError("Unable to fetch mesh/topology data from router")

