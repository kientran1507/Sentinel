from __future__ import annotations

import asyncio
import logging
import os
import threading

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

        async def respond(interaction, command_name: str):
            response = self.handler.handle(
                f"/{command_name}",
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
