import os
from datetime import datetime

import discord

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
OWNER_ID = os.environ.get("DISCORD_OWNER_ID")

SENTRY_DSN = os.environ.get("SENTRY_DSN")

LINKER_API_KEY = os.environ.get("LINKER_API_KEY")
LINKER_API_URL = os.environ.get("LINKER_API_URL")


async def NOTIFY_TO_OWNER(bot, message: str):
    owner = await bot.fetch_user(OWNER_ID)
    dmCh = await owner.create_dm()
    await dmCh.send(
        content="Bot Status Notification",
        embed=discord.Embed()
        .add_field(name="Status", value=message)
        .set_footer(text=str(datetime.now())),
    )
