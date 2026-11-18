from __future__ import annotations

import asyncio
import logging
import os
import threading
from shlex import quote

from .handler import CommandHandler
from .renderers import render_discord

logger = logging.getLogger(__name__)


class DiscordCommandBot:
    """Discord Gateway adapter. Command policy lives in CommandHandler."""

    name = "discord"

    def __init__(self, token: str, handler: CommandHandler):
        self.token = token
        self.handler = handler
        self._thread: threading.Thread | None = None
        self._client = None
        self._loop = None

    def _guild_id(self) -> int | None:
        value = os.getenv("DISCORD_GUILD_ID")
        if not value:
            return None
        try:
            return int(value)
        except ValueError as exc:
            raise RuntimeError("DISCORD_GUILD_ID must be numeric") from exc

    def _build_client(self, discord):
        intents = discord.Intents.default()
        client = discord.Client(intents=intents)
        tree = discord.app_commands.CommandTree(client)
        self._client = client

        async def respond(interaction, command_name: str, args=None):
            response = self.handler.handle(
            " ".join([f"/{command_name}"] + (args or [])),
                platform="discord",
                user_id=str(interaction.user.id),
            )
            embed = render_discord(response, discord)
            if embed is not None:
                await interaction.response.send_message(embed=embed)
            else:
                await interaction.response.send_message(response.text)

        @tree.command(name="help", description="Show available Sentinel commands")
        async def help_command(interaction):
            await respond(interaction, "help")

        @tree.command(name="devices", description="Show discovered devices")
        async def devices_command(interaction):
            await respond(interaction, "devices")

        @tree.command(name="status", description="Show Sentinel status")
        async def status_command(interaction):
            await respond(interaction, "status")

        @tree.command(name="alerts", description="Show recent Sentinel alerts")
        async def alerts_command(interaction):
            await respond(interaction, "alerts")

        @tree.command(name="findings", description="Show detection findings")
        async def findings_command(interaction, limit: int | None = None, status: str | None = None, before: str | None = None):
            args = []
            if limit is not None:
                args.extend(["--limit", str(limit)])
            if status is not None:
                args.extend(["--status", status])
            if before is not None:
                args.extend(["--before", before])
            await respond(interaction, "findings", args)

        @tree.command(name="finding", description="Inspect a detection finding")
        async def finding_command(interaction, finding_id: str):
            await respond(interaction, "finding", [finding_id])

        @tree.command(name="acknowledge_finding", description="Acknowledge a finding with an audited reason")
        async def acknowledge_finding_command(interaction, finding_id: str, reason: str):
            await respond(interaction, "acknowledge-finding", [quote(finding_id), quote(reason)])

        @tree.command(name="resolve_finding", description="Resolve a finding with an audited reason")
        async def resolve_finding_command(interaction, finding_id: str, reason: str):
            await respond(interaction, "resolve-finding", [quote(finding_id), quote(reason)])

        @tree.command(name="create_incident", description="Create an investigation case")
        async def create_incident_command(interaction, case_key: str, title: str):
            await respond(interaction, "create-incident", [quote(case_key), quote(title)])

        @tree.command(name="link_finding", description="Link a finding to an investigation")
        async def link_finding_command(interaction, incident_id: str, finding_id: str, reason: str):
            await respond(interaction, "link-finding", [quote(incident_id), quote(finding_id), quote(reason)])

        @tree.command(name="incident_note", description="Add an audited investigation note")
        async def incident_note_command(interaction, incident_id: str, note_key: str, note: str):
            await respond(interaction, "incident-note", [quote(incident_id), quote(note_key), quote(note)])

        @tree.command(name="resolve_incident", description="Close an investigation case")
        async def resolve_incident_command(interaction, incident_id: str, reason: str):
            await respond(interaction, "resolve-incident", [quote(incident_id), quote(reason)])

        @tree.command(name="incidents", description="List investigation cases")
        async def incidents_command(interaction, limit: int | None = None, status: str | None = None, before: str | None = None):
            args = []
            for flag, value in (("--limit", limit), ("--status", status), ("--before", before)):
                if value is not None:
                    args.extend([flag, quote(str(value))])
            await respond(interaction, "incidents", args)

        @tree.command(name="incident", description="Inspect an investigation timeline")
        async def incident_command(interaction, incident_id: str, before: str | None = None):
            args = [quote(incident_id)] + (["--before", quote(before)] if before is not None else [])
            await respond(interaction, "incident", args)

        @tree.command(name="deliveries", description="List notification send-attempt history")
        async def deliveries_command(interaction, limit: int | None = None, status: str | None = None,
                                     provider: str | None = None, alert: str | None = None, before: str | None = None):
            args = []
            for flag, value in (("--limit", limit), ("--status", status), ("--provider", provider),
                                ("--alert", alert), ("--before", before)):
                if value is not None:
                    args.extend([flag, quote(str(value))])
            await respond(interaction, "deliveries", args)

        @tree.command(name="delivery", description="Inspect one notification send attempt")
        async def delivery_command(interaction, attempt_id: str):
            await respond(interaction, "delivery", [quote(attempt_id)])

        @tree.command(name="events", description="Show historical device events")
        async def events_command(interaction, limit: int | None = None, device: str | None = None, type: str | None = None):
            args = []
            if limit is not None:
                args.extend(["--limit", str(limit)])
            if device:
                args.extend(["--device", device])
            if type:
                args.extend(["--type", type])
            await respond(interaction, "events", args)

        @tree.command(name="alert_history", description="Show historical alerts")
        async def alert_history_command(interaction, limit: int | None = None, device: str | None = None, severity: str | None = None, type: str | None = None):
            args = []
            if limit is not None:
                args.extend(["--limit", str(limit)])
            if device:
                args.extend(["--device", device])
            if severity:
                args.extend(["--severity", severity])
            if type:
                args.extend(["--type", type])
            await respond(interaction, "alert-history", args)

        @client.event
        async def on_ready():
            self._loop = asyncio.get_running_loop()
            logger.info("Discord command bot connected as %s", client.user)

        @client.event
        async def setup_hook():
            guild_id = self._guild_id()
            if guild_id is not None:
                guild = discord.Object(id=guild_id)
                tree.copy_global_to(guild=guild)
                synced = await tree.sync(guild=guild)
                logger.info("Discord application commands synced: %d", len(synced))
            else:
                synced = await tree.sync()
                logger.info("Discord application commands synced: %d", len(synced))

        return client

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run, name="sentinel-discord-commands", daemon=True)
        self._thread.start()

    def run(self) -> None:
        try:
            import discord
        except ImportError as exc:
            logger.error("Discord command support unavailable: install the discord.py dependency")
            return

        client = self._build_client(discord)

        try:
            logger.info("Discord: connecting...")
            client.run(self.token, log_handler=None)
        except Exception:
            logger.exception("Discord command bot stopped unexpectedly")

    def stop(self) -> None:
        if self._client and self._loop and not self._loop.is_closed():
            future = asyncio.run_coroutine_threadsafe(self._client.close(), self._loop)
            try:
                future.result(timeout=10)
            except Exception:
                logger.exception("Discord command bot shutdown failed")
        if self._thread:
            self._thread.join(timeout=10)
            if self._thread.is_alive():
                logger.warning("Discord command bot did not stop before timeout")
