# Networking

The current Sentinel runtime is a single Python process. Discovery sends ICMP and/or ARP probes to configured LAN targets. The ZTE client communicates with the configured `ZTE_ROUTER_URL`. Alert providers use outbound HTTPS to Discord webhooks and the Telegram Bot API. Telegram commands use HTTPS long polling; Discord commands use the Discord Gateway and application-command API.

No inbound HTTP listener, REST API, public webhook endpoint, reverse proxy, or fixed Sentinel service port is currently implemented. The command service works behind normal NAT because Telegram uses polling and Discord uses its outbound Gateway connection.

ARP may require raw-network privileges. Credentials and tokens are environment-based and must not be logged. A Telegram bot token should normally have only one active `getUpdates` consumer; competing consumers cause Telegram HTTP 409 conflicts.
