from __future__ import annotations

import html
from datetime import datetime
from typing import Any

from .models import CommandResponse


def _status_icon(state: str) -> str:
    return {"ONLINE": "🟢", "OFFLINE": "🔴"}.get(state.upper(), "⚪")


def _severity_icon(severity: str) -> str:
    return {"INFO": "🟢", "WARNING": "🟡", "CRITICAL": "🔴"}.get(severity.upper(), "⚪")


def _format_time(value: str | None) -> str:
    if not value:
        return "N/A"
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%d %b %Y %H:%M")
    except ValueError:
        return value


def render_telegram(response: CommandResponse) -> tuple[str, str | None]:
    """Return Telegram HTML and parse mode without depending on Telegram types."""
    data = response.data
    if not data:
        return html.escape(response.text), "HTML"

    command = response.command
    if command == "help":
        return (
            "<b>Sentinel Commands</b>\n\n"
            "<b>Monitoring</b>\n\n"
            "/devices — Show discovered devices\n"
            "/status — Show Sentinel status\n"
            "/alerts — Show recent alerts\n"
            "/events — Show historical device events\n"
            "/alert-history — Show historical alerts\n\n"
            "<b>General</b>\n\n/help — Show this help",
            "HTML",
        )
    if command == "devices":
        lines = ["<b>Sentinel Devices</b>", ""]
        devices = data["devices"]
        if not devices:
            lines.extend(["⚪ No devices currently known to Sentinel.", "", "The monitor may still be starting up."])
        else:
            for device in devices:
                name = html.escape(device["hostname"] or "Unknown hostname")
                ip = html.escape(device["ip"] or "unknown")
                mac = html.escape(device["mac"] or "unknown")
                state = html.escape(device["state"])
                lines.extend([f"{_status_icon(device['state'])} <b>{name}</b>", f"   State: <b>{state}</b>", f"   IP: <code>{ip}</code>", f"   MAC: <code>{mac}</code>", ""])
            lines.extend(["━━━━━━━━━━━━━━━━", f"Total: <b>{data['total']}</b>", f"🟢 Online: {data['online']}", f"🔴 Offline: {data['offline']}", f"⚪ Unknown: {data['unknown']}"])
        return "\n".join(lines), "HTML"
    if command == "status":
        return ("\n".join([
            "<b>Sentinel Status</b>", "", f"🟢 Monitor: <b>{html.escape(data['monitor'])}</b>", "",
            "<b>Devices</b>", f"🟢 Online: {data['online']}", f"🔴 Offline: {data['offline']}", f"⚪ Unknown: {data['unknown']}", f"\nTotal: <b>{data['total']}</b>", "", "Last update:", f"<code>{html.escape(_format_time(data.get('last_update')))}</code>",
        ]), "HTML")
    if command == "alerts":
        lines = ["<b>Sentinel Alerts</b>", ""]
        if not data["alerts"]:
            lines.append("🟢 No recent alerts.")
        else:
            for alert in data["alerts"]:
                lines.extend([
                    f"{_severity_icon(alert['severity'])} <b>{html.escape(alert['title'])}</b>",
                    html.escape(alert["message"]),
                    f"IP: <code>{html.escape(alert['ip'])}</code>",
                    f"MAC: <code>{html.escape(alert['mac'])}</code>",
                    f"Time: <code>{html.escape(_format_time(alert['timestamp']))}</code>", "",
                ])
        return "\n".join(lines).rstrip(), "HTML"
    if command == "events":
        lines = ["<b>Historical Sentinel Events</b>", ""]
        if not data["events"]:
            lines.append("No historical events found.")
        else:
            for event in data["events"][:20]:
                lines.extend([
                    f"<b>{html.escape(event['event_type'])}</b>",
                    f"{html.escape(event['device'])} · IP: <code>{html.escape(event['ip'])}</code>",
                    f"Time: <code>{html.escape(_format_time(event['timestamp']))}</code>", "",
                ])
            if len(data["events"]) > 20:
                lines.append("Showing the first 20 results.")
        return "\n".join(lines).rstrip(), "HTML"
    if command == "alert-history":
        lines = ["<b>Historical Sentinel Alerts</b>", ""]
        if not data["alerts"]:
            lines.append("No historical alerts found.")
        else:
            for alert in data["alerts"][:20]:
                lines.extend([
                    f"{_severity_icon(alert['severity'])} <b>{html.escape(alert['alert_type'])}</b>",
                    html.escape(alert["title"]), html.escape(alert["message"]),
                    f"Device: <code>{html.escape(alert['device'])}</code>",
                    f"Time: <code>{html.escape(_format_time(alert['timestamp']))}</code>", "",
                ])
            if len(data["alerts"]) > 20:
                lines.append("Showing the first 20 results.")
        return "\n".join(lines).rstrip(), "HTML"
    return html.escape(response.text), "HTML"


def render_discord(response: CommandResponse, discord_module=None):
    """Build a Discord embed lazily so core command code has no SDK dependency."""
    discord = discord_module
    if discord is None:
        import discord as discord_module
        discord = discord_module

    data = response.data
    if not data:
        return None
    command = response.command
    if command == "help":
        embed = discord.Embed(title="Sentinel Commands", color=0x2F80ED)
        embed.add_field(name="Monitoring", value="`/devices`  Show discovered devices\n`/status`   Show Sentinel status\n`/alerts`   Show recent alerts\n`/events`   Show historical events\n`/alert-history`   Show historical alerts", inline=False)
        embed.add_field(name="General", value="`/help`     Show this help", inline=False)
        return embed
    if command == "devices":
        embed = discord.Embed(title="Sentinel Devices", color=0x2F80ED)
        if not data["devices"]:
            embed.description = "⚪ **No devices currently known to Sentinel.**\n\nThe monitor may still be starting up."
        else:
            for device in data["devices"][:23]:
                state = device["state"]
                embed.add_field(
                    name=f"{_status_icon(state)} {device['hostname'] or 'Unknown hostname'} · {state}",
                    value=f"IP: `{device['ip'] or 'unknown'}`\nMAC: `{device['mac'] or 'unknown'}`",
                    inline=False,
                )
            embed.add_field(name="Summary", value=f"Total **{data['total']}** · 🟢 **{data['online']}** online · 🔴 **{data['offline']}** offline · ⚪ **{data['unknown']}** unknown", inline=False)
        return embed
    if command == "status":
        embed = discord.Embed(title="Sentinel Status", color=0x2F80ED)
        embed.add_field(name="🟢 Monitor", value=f"**{data['monitor']}**", inline=True)
        embed.add_field(name="Devices", value=f"**{data['total']}**", inline=True)
        embed.add_field(name="🟢 Online", value=str(data["online"]), inline=True)
        embed.add_field(name="🔴 Offline", value=str(data["offline"]), inline=True)
        embed.add_field(name="⚪ Unknown", value=str(data["unknown"]), inline=True)
        embed.add_field(name="Last update", value=f"`{_format_time(data.get('last_update'))}`", inline=False)
        return embed
    if command == "alerts":
        embed = discord.Embed(title="Sentinel Alerts", color=0x2F80ED)
        if not data["alerts"]:
            embed.description = "🟢 **No recent alerts.**"
        else:
            for alert in data["alerts"][:23]:
                embed.add_field(name=f"{_severity_icon(alert['severity'])} {alert['title']}", value=f"{alert['message']}\nIP: `{alert['ip']}` · MAC: `{alert['mac']}`\nTime: `{_format_time(alert['timestamp'])}`", inline=False)
        return embed
    if command == "events":
        embed = discord.Embed(title="Historical Sentinel Events", color=0x2F80ED)
        if not data["events"]:
            embed.description = "No historical events found."
        else:
            for event in data["events"][:23]:
                embed.add_field(
                    name=f"{event['event_type']} · {event['device']}",
                    value=f"IP: `{event['ip']}`\nTime: `{_format_time(event['timestamp'])}`",
                    inline=False,
                )
            if len(data["events"]) > 23:
                embed.set_footer(text="Showing the first 23 results.")
        return embed
    if command == "alert-history":
        embed = discord.Embed(title="Historical Sentinel Alerts", color=0x2F80ED)
        if not data["alerts"]:
            embed.description = "No historical alerts found."
        else:
            for alert in data["alerts"][:23]:
                embed.add_field(
                    name=f"{_severity_icon(alert['severity'])} {alert['alert_type']} · {alert['title']}",
                    value=f"{alert['message']}\nDevice: `{alert['device']}`\nTime: `{_format_time(alert['timestamp'])}`",
                    inline=False,
                )
            if len(data["alerts"]) > 23:
                embed.set_footer(text="Showing the first 23 results.")
        return embed
    return None
