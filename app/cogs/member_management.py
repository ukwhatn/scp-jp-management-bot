import logging

import discord
from discord.ext import commands, tasks
from httpx import HTTPStatusError
from scp_jp.api import LinkerAPIClient
from scp_jp.api.member_management import (
    MemberManagementAPIClient,
    BatchStatusesResponseSchema,
    Status,
)

from core import get_settings
from db import db_session
from db.models import SiteApplicationNotifyChannel, SiteApplication
from ui.views import member_management as views


class MemberManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings = get_settings()
        self.logger = logging.getLogger("discord")

        # API Client
        self.linker_api = LinkerAPIClient(
            self.settings.LINKER_API_URL,
            self.settings.LINKER_API_KEY,
        )
        self.member_api = MemberManagementAPIClient(
            self.settings.MEMBER_MANAGEMENT_API_URL,
            self.settings.MEMBER_MANAGEMENT_API_KEY,
        )

    # ==============================
    # イベントハンドラ
    # ==============================

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(views.ApplicationActionButtons())
        self.bot.add_view(views.ApplicationAcceptConfirmationButtons())
        self.bot.add_view(views.ApplicationHandlingStatusButtons())
        self.check_site_applications.start()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.check_site_applications.is_running():
            self.check_site_applications.start()

    # ==============================
    # Cog全体のサブコマンド
    # ==============================

    group_management = discord.SlashCommandGroup("member", "メンバー管理関連のコマンド")

    # ==============================
    # バッチ処理の管理（systemエンドポイント系）
    # ==============================

    group_system = group_management.create_subgroup("system", "システム系のコマンド")

    @group_system.command(
        name="batch_status", description="バッチ処理のステータスを確認します"
    )
    @commands.is_owner()
    async def batch_status(self, ctx: discord.ApplicationContext):
        await ctx.response.defer(ephemeral=True)
        result: BatchStatusesResponseSchema = await self.member_api.get_batch_status()
        msg = "\n".join(
            f"{status.name}: {status.next_run_time.strftime('%Y-%m-%d %H:%M:%S')}"
            for status in result.statuses
        )
        await ctx.followup.send(msg)

    @group_system.command(name="run_batch", description="バッチ処理を強制実行します")
    @commands.is_owner()
    async def run_batch(
        self, ctx: discord.ApplicationContext, batch_name: discord.Option(str, "処理名")
    ):
        await ctx.response.defer(ephemeral=True)
        try:
            await self.member_api.force_start_batch(batch_name)
        except HTTPStatusError as e:
            if e.response.status_code == 404:
                await ctx.respond(":x: バッチ処理が見つかりません")
                return
            raise
        await ctx.followup.send(
            f":white_check_mark: バッチ処理 {batch_name} の強制実行リクエストを送信しました"
        )

    # ==============================
    # 参加申請管理系
    # ==============================

    group_application = group_management.create_subgroup(
        "application", "参加申請関連のコマンド"
    )

    # ===== 通知先チャンネルの設定 =====

    async def _autocomplete_sites(self, ctx: discord.AutocompleteContext):
        sites = await self.member_api.get_sites()
        return [f"{site.id}: {site.name}" for site in sites if ctx.value in site.name]

    @group_application.command(
        name="add_notify_channel",
        description="このチャンネルを参加申請の通知先チャンネルとして追加/削除します",
    )
    @commands.is_owner()
    async def toggle_notify_channel(
        self,
        ctx: discord.ApplicationContext,
        site: discord.Option(str, "サイト名", autocomplete=_autocomplete_sites),
    ):
        await ctx.response.defer(ephemeral=True)

        # ctx.guildまたはctx.channelがない場合はエラー
        if ctx.guild is None or ctx.channel is None:
            await ctx.followup.send(
                ":x: サーバーチャンネル内で実行してください", ephemeral=True
            )
            return

        site_id = int(site.split(":")[0])

        # サイト存在チェック
        srv_sites = await self.member_api.get_sites()
        if site_id not in [_s.id for _s in srv_sites]:
            await ctx.followup.send(":x: サイトが見つかりません", ephemeral=True)
            return

        # 既存のエントリ確認
        with db_session() as session:
            exist_entry = (
                session.query(SiteApplicationNotifyChannel)
                .filter_by(
                    guild_id=ctx.guild.id,
                    channel_id=ctx.channel.id,
                    site_id=site_id,
                )
                .first()
            )

            if exist_entry is None:
                # 新規作成
                session.add(
                    SiteApplicationNotifyChannel(
                        guild_id=ctx.guild.id,
                        channel_id=ctx.channel.id,
                        site_id=site_id,
                    )
                )
                session.commit()
                await ctx.followup.send(
                    f":white_check_mark: このチャンネルをサイト {site} の通知先チャンネルに追加しました",
                    ephemeral=True,
                )

            else:
                # 削除
                session.delete(exist_entry)
                session.commit()
                await ctx.followup.send(
                    f":white_check_mark: このチャンネルをサイト {site} の通知先チャンネルから削除しました",
                    ephemeral=True,
                )

    @group_application.command(
        name="list_notify_channels",
        description="参加申請の通知先チャンネルの一覧を表示します",
    )
    @commands.is_owner()
    async def list_notify_channels(self, ctx: discord.ApplicationContext):
        await ctx.response.defer(ephemeral=True)

        srv_sites = {site.id: site for site in await self.member_api.get_sites()}

        with db_session() as session:
            channels = (
                session.query(SiteApplicationNotifyChannel)
                .filter_by(guild_id=ctx.guild.id)
                .all()
            )
            msg = "\n".join(
                [
                    f"{ctx.guild.get_channel(channel.channel_id).mention} : {srv_sites[channel.site_id].name}"
                    for channel in channels
                ]
            )
            await ctx.followup.send(msg, ephemeral=True)

    # ===== 参加申請の処理系 =====
    @tasks.loop(minutes=10)
    async def check_site_applications(self):
        """
        参加申請を監視し、新しい申請があれば通知します
        """
        with db_session() as session:
            channels = session.query(SiteApplicationNotifyChannel).all()
            for channel in channels:
                site_id = channel.site_id
                pending_applications = await self.member_api.get_application_requests(
                    site_id=site_id, statuses=[Status.PENDING]
                )

                for pending in pending_applications:
                    # original_idで検索
                    exist_entry = (
                        session.query(SiteApplication)
                        .filter_by(
                            original_id=pending.id,
                            site_id=site_id,
                        )
                        .first()
                    )
                    if exist_entry is None:
                        # メッセージ送信
                        guild_obj = self.bot.get_guild(channel.guild_id)
                        channel_obj = guild_obj.get_channel(channel.channel_id)
                        application_text = pending.text
                        if (
                            application_text is not None
                            and pending.password is not None
                        ):
                            application_text.replace(
                                pending.password, f"**`{pending.password}`**"
                            )

                        await channel_obj.send(
                            f"### 【{pending.site['name']}】参加申請を受け取りました",
                            embed=discord.Embed(
                                title="参加申請", color=discord.Color.yellow()
                            )
                            .set_author(
                                name=pending.user["name"],
                                url=f"https://www.wikidot.com/user:info/{pending.user['unix_name']}",
                                icon_url=pending.user["avatar_url"],
                            )
                            .set_footer(text=f"{pending.id}")
                            .add_field(
                                name="メッセージ",
                                value=application_text or "（メッセージなし）",
                                inline=False,
                            )
                            .add_field(
                                name="合言葉",
                                value=pending.password or "（不明）",
                                inline=False,
                            ),
                            view=views.ApplicationActionButtons(),
                        )

                        # DBに登録
                        session.add(
                            SiteApplication(
                                original_id=pending.id,
                                site_id=site_id,
                            )
                        )
                        session.commit()

    @check_site_applications.before_loop
    async def before_check_site_applications(self):
        await self.bot.wait_until_ready()

    @group_application.command(
        name="force_check", description="参加申請の強制チェックを行います"
    )
    @commands.is_owner()
    async def force_check_site_applications(self, ctx: discord.ApplicationContext):
        await ctx.response.defer(ephemeral=True)
        self.check_site_applications.restart()
        await ctx.followup.send(
            ":white_check_mark: 強制チェックを開始します", ephemeral=True
        )


def setup(bot):
    return bot.add_cog(MemberManagement(bot))
