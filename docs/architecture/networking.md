# Networking

Sentinel opens no inbound HTTP listener or fixed application service port.

| Path | Network use |
| --- | --- |
| ICMP discovery | System ping to selected addresses |
| ARP discovery | Scapy raw packets on the local link |
| Hostname enrichment | PTR, Windows NetBIOS, mDNS; no implemented LLMNR reverse query |
| ZTE collection | Requests to `ZTE_ROUTER_URL` |
| Discord notifications/commands | Outbound webhook HTTPS, Gateway, application-command API |
| Telegram notifications/commands | Outbound Bot API HTTPS and `getUpdates` long polling |
| PostgreSQL | Outbound database connection when selected |

ARP needs packet access and cannot discover across routers; Windows may require a suitable packet-capture driver. ICMP can be blocked. Hostname enrichment is opt-in. SQLite needs no database network service.

The integrated ZTE client currently sets `verify_tls=False`; TLS verification is not exposed as a runtime environment option. Keep this implementation detail in mind when selecting the router connection.

Only one Telegram polling consumer should use a token. Discord/Telegram adapters share the monitoring process and normally work behind NAT. There is no REST ingress, reverse-proxy configuration, traffic forwarding, IDS, or firewall enforcement in this implementation.
