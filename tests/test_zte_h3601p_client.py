from __future__ import annotations

import base64
import hashlib
import http.cookiejar
import io
import json
import logging
import os
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from services.discovery.zte_h3601p_client import (
    ZTEH3601PClient,
    _sanitize_log_message,
    default_password_transform,
)
from services.discovery.zte_h3601p_parser import (
    ZTEDHCPClient,
    ZTEMeshClient,
    parse_dhcp_clients_xml,
    parse_mesh_topology,
)


SAMPLE_DHCP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ajax_response_xml_root>
  <OBJ_DHCPHOSTINFO_ID>
    <Instance>
      <ParaName>OBJ_DHCPHOSTINFO_ID.IPAddr</ParaName>
      <ParaValue>192.168.2.13</ParaValue>
    </Instance>
    <Instance>
      <ParaName>OBJ_DHCPHOSTINFO_ID.MACAddr</ParaName>
      <ParaValue>AA:BB:CC:DD:EE:FF</ParaValue>
    </Instance>
    <Instance>
      <ParaName>OBJ_DHCPHOSTINFO_ID.HostName</ParaName>
      <ParaValue>OPPO-Reno8</ParaValue>
    </Instance>
    <Instance>
      <ParaName>OBJ_DHCPHOSTINFO_ID.RemainLeaseTime</ParaName>
      <ParaValue>86400</ParaValue>
    </Instance>
  </OBJ_DHCPHOSTINFO_ID>
</ajax_response_xml_root>
"""

SAMPLE_EMPTY_DHCP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ajax_response_xml_root>
  <OBJ_DHCPHOSTINFO_ID/>
</ajax_response_xml_root>
"""

SAMPLE_MESH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ajax_response_xml_root>
  <master>
    <HostName>ZTE-Router</HostName>
    <MacAddr>74:6F:88:FF:F0:0B</MacAddr>
    <IpAddr>192.168.2.253</IpAddr>
    <AccessType>Ethernet</AccessType>
  </master>
  <slave>
    <HostName>OPPO-Reno8</HostName>
    <MacAddr>AA:BB:CC:DD:EE:FF</MacAddr>
    <IpAddr>192.168.2.13</IpAddr>
    <parent>74:6F:88:FF:F0:0B</parent>
    <AccessType>Wi-Fi 5G</AccessType>
    <RSSI>-55</RSSI>
  </slave>
  <ad>
    <HostName>Tran-Trung-Kien</HostName>
    <MacAddr>11:22:33:44:55:66</MacAddr>
    <IpAddr>192.168.2.11</IpAddr>
    <parent>74:6F:88:FF:F0:0B</parent>
    <AccessType>Wi-Fi 2.4G</AccessType>
    <RSSI>-62</RSSI>
  </ad>
</ajax_response_xml_root>
"""

SAMPLE_MESH_JSON = """{
  "master": {
    "instID": "MESH.CONTROLLER",
    "DeviceName": "ZTE-Router",
    "MacAddr": "74:6F:88:FF:F0:0B",
    "IpAddr": "192.168.2.253"
  },
  "slave": [
    {
      "instID": "MESH.AGENT1",
      "DeviceName": "Agent-1",
      "MacAddr": "AA:BB:CC:DD:EE:01",
      "IpAddr": "192.168.2.2"
    }
  ],
  "ad": {
    "1": {
      "parent": "MESH.CONTROLLER",
      "MacAddr": "11:22:33:44:55:66",
      "IpAddr": "192.168.2.11",
      "HostName": "Tran-Trung-Kien",
      "AccessType": "1"
    },
    "2": {
      "parent": "MESH.AGENT1",
      "MacAddr": "AA:BB:CC:DD:EE:FF",
      "IpAddr": "192.168.2.13",
      "HostName": "OPPO-Reno8",
      "AccessType": "2"
    },
    "MGET_INST_NUM": 2
  }
}"""

SAMPLE_DHCP_MULTIFIELD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<ajax_response_xml_root>
  <OBJ_DHCPHOSTINFO_ID>
    <Instance>
      <ParaName>IPAddr</ParaName>
      <ParaValue>192.168.2.13</ParaValue>
      <ParaName>MACAddr</ParaName>
      <ParaValue>AA:BB:CC:DD:EE:FF</ParaValue>
      <ParaName>HostName</ParaName>
      <ParaValue>OPPO-Reno8</ParaValue>
    </Instance>
    <Instance>
      <ParaName>IPAddr</ParaName>
      <ParaValue>192.168.2.11</ParaValue>
      <ParaName>MACAddr</ParaName>
      <ParaValue>11:22:33:44:55:66</ParaValue>
      <ParaName>HostName</ParaName>
      <ParaValue>Tran-Trung-Kien</ParaValue>
    </Instance>
  </OBJ_DHCPHOSTINFO_ID>
</ajax_response_xml_root>
"""


class TestZTEH3601PClient(unittest.TestCase):

    def test_missing_credentials_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                ZTEH3601PClient(url="", username="admin", password="password")
            with self.assertRaises(ValueError):
                ZTEH3601PClient(url="https://192.168.2.253", username="", password="password")
            with self.assertRaises(ValueError):
                ZTEH3601PClient(url="https://192.168.2.253", username="admin", password="")

    def test_credentials_from_env(self):
        env = {
            "ZTE_ROUTER_URL": "https://192.168.2.253",
            "ZTE_USERNAME": "envuser",
            "ZTE_PASSWORD": "envpassword",
        }
        with patch.dict(os.environ, env):
            client = ZTEH3601PClient()
            self.assertEqual(client.url, "https://192.168.2.253")
            self.assertEqual(client.username, "envuser")
            self.assertEqual(client.password, "envpassword")

    def test_secret_redaction_and_string_representation(self):
        client = ZTEH3601PClient(
            url="https://192.168.2.253",
            username="testuser",
            password="secretpassword123",
        )
        repr_str = repr(client)
        str_str = str(client)
        self.assertNotIn("secretpassword123", repr_str)
        self.assertNotIn("secretpassword123", str_str)

        sensitive_msg = (
            "POST Password=secret123&_sessionTOKEN=99887766 "
            "Cookie: SID=abc123xyz; SID_HTTPS=def456uvw "
            "Authorization: Bearer token123"
        )
        sanitized = _sanitize_log_message(sensitive_msg)
        self.assertNotIn("secret123", sanitized)
        self.assertNotIn("99887766", sanitized)
        self.assertNotIn("abc123xyz", sanitized)
        self.assertNotIn("def456uvw", sanitized)
        self.assertNotIn("token123", sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_synthetic_password_transformations(self):
        pass_plain = "TestPassword123!"
        token = "123456789"

        # sha256_concat
        res1 = default_password_transform(pass_plain, token, "sha256_concat")
        self.assertEqual(res1, "74207967f277f4fecacf5407ad646a98c4b593baf0bf9f27f72c0f6536ab5cea")

        # sha256_concat_upper
        res2 = default_password_transform(pass_plain, token, "sha256_concat_upper")
        self.assertEqual(res2, "74207967F277F4FECACF5407AD646A98C4B593BAF0BF9F27F72C0F6536AB5CEA")

        # sha256_double
        res3 = default_password_transform(pass_plain, token, "sha256_double")
        self.assertEqual(res3, "40eca725baa416e0747014e8298a7d31c36d916ef8ab0ba92d4f1094f6d27fae")

        # sha256_double_upper
        res4 = default_password_transform(pass_plain, token, "sha256_double_upper")
        self.assertEqual(res4, "40ECA725BAA416E0747014E8298A7D31C36D916EF8AB0BA92D4F1094F6D27FAE")

    def test_rsa_pkcs1v15_password_transformation(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub_pem = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode("utf-8")

        pass_plain = "TestPassword123!"
        token = "123456789"

        # rsa_pkcs1v15_concat
        b64_enc = default_password_transform(
            pass_plain, token, algo="rsa_pkcs1v15_concat", rsa_public_key=pub_pem
        )
        decrypted = key.decrypt(
            base64.b64decode(b64_enc),
            padding.PKCS1v15()
        ).decode("utf-8")
        self.assertEqual(decrypted, "TestPassword123!123456789")

        # rsa_pkcs1v15_plain
        b64_plain = default_password_transform(
            pass_plain, token, algo="rsa_pkcs1v15_plain", rsa_public_key=pub_pem
        )
        decrypted_plain = key.decrypt(
            base64.b64decode(b64_plain),
            padding.PKCS1v15()
        ).decode("utf-8")
        self.assertEqual(decrypted_plain, "TestPassword123!")

    @patch("services.discovery.zte_h3601p_client.urllib.request.OpenerDirector.open")
    def test_get_login_token_xml_format(self, mock_open):
        mock_resp = io.BytesIO(b"<ajax_response_xml_root>123456789</ajax_response_xml_root>")
        mock_open.return_value.__enter__.return_value = mock_resp

        client = ZTEH3601PClient(
            url="https://192.168.2.253",
            username="admin",
            password="pass",
        )
        token = client.get_login_token()
        self.assertEqual(token, "123456789")

    @patch("services.discovery.zte_h3601p_client.urllib.request.OpenerDirector.open")
    def test_login_http_200_auth_failure(self, mock_open):
        init_resp = io.BytesIO(b"<html></html>")
        session_entry = io.BytesIO(b'{"lockingTime":0,"sess_token":"SESSIONTOKEN123","loginErrMsg":""}')
        token_resp = io.BytesIO(b"<ajax_response_xml_root>123456789</ajax_response_xml_root>")
        login_fail_resp = io.BytesIO(b'{"loginErrMsg": "Invalid Username or Password", "login_need_refresh": false}')

        mock_open.return_value.__enter__.side_effect = [init_resp, session_entry, token_resp, login_fail_resp]

        client = ZTEH3601PClient(
            url="https://192.168.2.253",
            username="admin",
            password="wrongpassword",
        )

        with self.assertRaises(RuntimeError):
            client.login()
        self.assertFalse(client._is_authenticated)

    @patch("services.discovery.zte_h3601p_client.urllib.request.OpenerDirector.open")
    def test_login_rejects_locking_time(self, mock_open):
        init_resp = io.BytesIO(b"<html></html>")
        session_entry = io.BytesIO(b'{"lockingTime":0,"sess_token":"SESSIONTOKEN123","loginErrMsg":""}')
        token_resp = io.BytesIO(b"<ajax_response_xml_root>123456789</ajax_response_xml_root>")
        login_locked = io.BytesIO(
            b'{"lockingTime":21,"loginErrMsg":"","promptMsg":"You have login failed for {0} times continuously. ","sess_token":"367454881845108165153912"}'
        )
        mock_open.return_value.__enter__.side_effect = [init_resp, session_entry, token_resp, login_locked]

        client = ZTEH3601PClient(
            url="https://192.168.2.253",
            username="admin",
            password="pass",
        )
        with self.assertRaises(RuntimeError) as ctx:
            client.login()
        self.assertIn("locked", str(ctx.exception).lower())
        self.assertFalse(client._is_authenticated)

    @patch("services.discovery.zte_h3601p_client.urllib.request.OpenerDirector.open")
    def test_g_logintoken_json_success(self, mock_open):
        init_resp = io.BytesIO(b"<html></html>")
        token_resp = io.BytesIO(b"<ajax_response_xml_root>123456789</ajax_response_xml_root>")
        login_resp = io.BytesIO(b'{"sess_token": "987654321", "login_need_refresh": true, "loginErrMsg": "", "promptMsg": ""}')
        refresh_resp = io.BytesIO(b'<html><input id="_sessionTOKEN" value="NEWTOKEN123"></html>')

        session_entry = io.BytesIO(b'{"lockingTime":0,"sess_token":"SESSIONTOKEN123","loginErrMsg":""}')
        # login() clears cookies, so set cookie via side effect after login by including Set-Cookie isn't needed;
        # success path accepts sess_token without requiring pre-set cookie.
        mock_open.return_value.__enter__.side_effect = [init_resp, session_entry, token_resp, login_resp, refresh_resp]

        client = ZTEH3601PClient(
            url="https://192.168.2.253",
            username="admin",
            password="pass",
        )

        success = client.login()
        self.assertTrue(success)
        self.assertTrue(client._is_authenticated)
        self.assertEqual(client._session_token, "987654321")
        self.assertEqual(client._page_session_token, "NEWTOKEN123")

    @patch("services.discovery.zte_h3601p_client.urllib.request.OpenerDirector.open")
    def test_login_success(self, mock_open):
        init_resp = io.BytesIO(b"<html></html>")
        token_resp = io.BytesIO(b"<ajax_response_xml_root>123456789</ajax_response_xml_root>")
        login_resp = io.BytesIO(b"<ajax_response_xml_root>success</ajax_response_xml_root>")

        session_entry = io.BytesIO(b'{"lockingTime":0,"sess_token":"SESSIONTOKEN123","loginErrMsg":""}')
        refresh_resp = io.BytesIO(b'<html><input id="_sessionTOKEN" value="NEWTOKEN123"></html>')
        mock_open.return_value.__enter__.side_effect = [init_resp, session_entry, token_resp, login_resp, refresh_resp]

        client = ZTEH3601PClient(
            url="https://192.168.2.253",
            username="admin",
            password="pass",
        )

        success = client.login()
        self.assertTrue(success)
        self.assertTrue(client._is_authenticated)

    @patch("services.discovery.zte_h3601p_client.urllib.request.OpenerDirector.open")
    def test_get_dhcp_clients_success(self, mock_open):
        init_resp = io.BytesIO(b"<html></html>")
        token_resp = io.BytesIO(b"<ajax_response_xml_root>123456789</ajax_response_xml_root>")
        login_resp = io.BytesIO(b"<ajax_response_xml_root>success</ajax_response_xml_root>")
        dhcp_resp = io.BytesIO(SAMPLE_DHCP_XML.encode("utf-8"))

        session_entry = io.BytesIO(b'{"lockingTime":0,"sess_token":"SESSIONTOKEN123","loginErrMsg":""}')
        refresh_resp = io.BytesIO(b'<html><input id="_sessionTOKEN" value="NEWTOKEN123"></html>')
        menu_view_resp = io.BytesIO(b"<html>localNetStatus</html>")
        mock_open.return_value.__enter__.side_effect = [
            init_resp, session_entry, token_resp, login_resp, refresh_resp, menu_view_resp, dhcp_resp
        ]

        client = ZTEH3601PClient(
            url="https://192.168.2.253",
            username="admin",
            password="pass",
        )
        cookie = http.cookiejar.Cookie(
            version=0, name="SID", value="mocked_sid_cookie", port=None, port_specified=False,
            domain="192.168.2.253", domain_specified=True, domain_initial_dot=False, path="/",
            path_specified=True, secure=True, expires=None, discard=True, comment=None,
            comment_url=None, rest={}, rfc2109=False
        )
        client.cookie_jar.set_cookie(cookie)

        clients = client.get_dhcp_clients()
        self.assertEqual(len(clients), 1)
        self.assertEqual(clients[0].ip_address, "192.168.2.13")
        self.assertEqual(clients[0].hostname, "OPPO-Reno8")

        requested_urls = [call.args[0].full_url for call in mock_open.call_args_list]
        self.assertTrue(any("_type=menuView" in url and "localNetStatus" in url for url in requested_urls))
        self.assertTrue(any("_type=menuData" in url and "dhcp4s_dhcphostinfo_m.lua" in url for url in requested_urls))

    def test_empty_dhcp_response(self):
        clients = parse_dhcp_clients_xml(SAMPLE_EMPTY_DHCP_XML)
        self.assertEqual(clients, [])

    def test_dhcp_multifield_instances(self):
        clients = parse_dhcp_clients_xml(SAMPLE_DHCP_MULTIFIELD_XML)
        self.assertEqual(len(clients), 2)
        self.assertEqual(clients[0].hostname, "OPPO-Reno8")
        self.assertEqual(clients[1].ip_address, "192.168.2.11")

    def test_dhcp_unauthenticated_or_error_response_raises(self):
        unauth_xml = "<ajax_response_xml_root>1001</ajax_response_xml_root>"
        with self.assertRaises(RuntimeError):
            parse_dhcp_clients_xml(unauth_xml)

    def test_mesh_topology_parsing(self):
        nodes = parse_mesh_topology(SAMPLE_MESH_XML)
        self.assertEqual(len(nodes), 3)
        self.assertEqual(nodes[0].node_name, "master")
        self.assertEqual(nodes[0].ip_address, "192.168.2.253")
        self.assertEqual(nodes[1].node_name, "slave")
        self.assertEqual(nodes[1].hostname, "OPPO-Reno8")
        self.assertEqual(nodes[1].parent_mac, "74:6F:88:FF:F0:0B")
        self.assertEqual(nodes[2].hostname, "Tran-Trung-Kien")

    def test_mesh_topology_json_parsing(self):
        nodes = parse_mesh_topology(SAMPLE_MESH_JSON)
        self.assertEqual(len(nodes), 4)
        self.assertEqual(nodes[0].node_name, "master")
        self.assertEqual(nodes[0].hostname, "ZTE-Router")
        self.assertEqual(nodes[1].node_name, "slave")
        self.assertEqual(nodes[2].connection_type, "Wi-Fi 2.4G")
        self.assertEqual(nodes[3].hostname, "OPPO-Reno8")
        self.assertEqual(nodes[3].connection_type, "Wi-Fi 5G")

    @patch("services.discovery.zte_h3601p_client.urllib.request.OpenerDirector.open")
    def test_get_mesh_topology_uses_topo_menu_data(self, mock_open):
        init_resp = io.BytesIO(b"<html></html>")
        token_resp = io.BytesIO(b"<ajax_response_xml_root>123456789</ajax_response_xml_root>")
        login_resp = io.BytesIO(b"<ajax_response_xml_root>success</ajax_response_xml_root>")
        topo_resp = io.BytesIO(SAMPLE_MESH_JSON.encode("utf-8"))

        session_entry = io.BytesIO(b'{"lockingTime":0,"sess_token":"SESSIONTOKEN123","loginErrMsg":""}')
        refresh_resp = io.BytesIO(b'<html><input id="_sessionTOKEN" value="NEWTOKEN123"></html>')
        mock_open.return_value.__enter__.side_effect = [
            init_resp, session_entry, token_resp, login_resp, refresh_resp, topo_resp
        ]

        client = ZTEH3601PClient(
            url="https://192.168.2.253",
            username="admin",
            password="pass",
        )
        cookie = http.cookiejar.Cookie(
            version=0, name="SID", value="mocked_sid_cookie", port=None, port_specified=False,
            domain="192.168.2.253", domain_specified=True, domain_initial_dot=False, path="/",
            path_specified=True, secure=True, expires=None, discard=True, comment=None,
            comment_url=None, rest={}, rfc2109=False
        )
        client.cookie_jar.set_cookie(cookie)

        nodes = client.get_mesh_topology()
        self.assertEqual(len(nodes), 4)
        requested_urls = [call.args[0].full_url for call in mock_open.call_args_list]
        self.assertTrue(any("_type=menuData" in url and "topo_lua.lua" in url for url in requested_urls))

    @patch("services.discovery.zte_h3601p_client.urllib.request.OpenerDirector.open")
    def test_session_expired_response(self, mock_open):
        init1 = io.BytesIO(b"<html></html>")
        token1 = io.BytesIO(b"<ajax_response_xml_root>123456789</ajax_response_xml_root>")
        login1 = io.BytesIO(b"<ajax_response_xml_root>success</ajax_response_xml_root>")
        expired_resp = io.BytesIO(b"<ajax_response_xml_root>1001</ajax_response_xml_root>")
        init2 = io.BytesIO(b"<html></html>")
        token2 = io.BytesIO(b"<ajax_response_xml_root>987654321</ajax_response_xml_root>")
        login2 = io.BytesIO(b"<ajax_response_xml_root>success</ajax_response_xml_root>")
        dhcp_resp = io.BytesIO(SAMPLE_DHCP_XML.encode("utf-8"))

        session1 = io.BytesIO(b'{"lockingTime":0,"sess_token":"SESSIONTOKEN123","loginErrMsg":""}')
        refresh1 = io.BytesIO(b'<html><input id="_sessionTOKEN" value="NEWTOKEN123"></html>')
        session2 = io.BytesIO(b'{"lockingTime":0,"sess_token":"SESSIONTOKEN456","loginErrMsg":""}')
        refresh2 = io.BytesIO(b'<html><input id="_sessionTOKEN" value="NEWTOKEN456"></html>')
        menu_view1 = io.BytesIO(b"<html>localNetStatus</html>")
        menu_view2 = io.BytesIO(b"<html>localNetStatus</html>")
        mock_open.return_value.__enter__.side_effect = [
            init1, session1, token1, login1, refresh1, menu_view1, expired_resp,
            init2, session2, token2, login2, refresh2, menu_view2, dhcp_resp,
        ]

        client = ZTEH3601PClient(
            url="https://192.168.2.253",
            username="admin",
            password="pass",
        )
        cookie = http.cookiejar.Cookie(
            version=0, name="SID", value="mocked_sid_cookie", port=None, port_specified=False,
            domain="192.168.2.253", domain_specified=True, domain_initial_dot=False, path="/",
            path_specified=True, secure=True, expires=None, discard=True, comment=None,
            comment_url=None, rest={}, rfc2109=False
        )
        client.cookie_jar.set_cookie(cookie)

        clients = client.get_dhcp_clients()
        self.assertEqual(len(clients), 1)

    def test_wrong_endpoint_response_raises(self):
        wrong_xml = "<wrong_root><item>test</item></wrong_root>"
        with self.assertRaises(RuntimeError):
            parse_dhcp_clients_xml(wrong_xml)

    def test_malformed_xml_raises(self):
        malformed = "<ajax_response_xml_root>incomplete"
        with self.assertRaises(RuntimeError):
            parse_dhcp_clients_xml(malformed)
        with self.assertRaises(RuntimeError):
            parse_mesh_topology(malformed)


if __name__ == "__main__":
    unittest.main()
