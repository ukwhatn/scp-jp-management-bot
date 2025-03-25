import logging

import discord
from discord.ext import commands

from core import get_settings
from ui.views.staff_request import (
    DetailsInputModal,
    Flow1TargetSelector,
    Flow2ConfirmView,
    RequestDMController,
    RequestDMControllerIsDone,
    RequestSummaryController,
    RequestSummaryFinishController,
)


class StaffRequest(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings = get_settings()
        self.logger = logging.getLogger("discord")

    # ==============================
    # イベントハンドラ
    # ==============================
    @commands.Cog.listener()
    async def on_ready(self):
        # viewの登録
        self.bot.add_view(Flow1TargetSelector())
        self.bot.add_view(Flow2ConfirmView())
        self.bot.add_view(RequestDMController())
        self.bot.add_view(RequestDMControllerIsDone())
        self.bot.add_view(RequestSummaryController())
        self.bot.add_view(RequestSummaryFinishController())

    # ==============================
    # Cog全体のサブコマンド
    # ==============================

    group_request = discord.SlashCommandGroup(
        "request", "スタッフへの確認依頼を管理するコマンド群"
    )

    # ==============================
    # 承認処理の追加
    # ==============================

    @group_request.command(name="add", description="スタッフへの確認依頼を追加します")
    async def request_add(self, ctx: discord.ApplicationContext):
        await ctx.send_modal(DetailsInputModal())


def setup(bot):
    return bot.add_cog(StaffRequest(bot))
