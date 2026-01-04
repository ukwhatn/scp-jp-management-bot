import logging
from typing import Optional

import discord
from discord.ext import commands, tasks

from core import get_settings
from db import db_session
from db.models import SiteApplicationNotifyChannel, SiteApplication
from ui.views import member_management as views
from utils.panopticon_client import PanopticonClient


class MemberManagement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.settings = get_settings()
        self.logger = logging.getLogger("discord")

        # Panopticon API Client
        if self.settings.PANOPTICON_API_URL and self.settings.PANOPTICON_API_KEY:
            self.panopticon = PanopticonClient(
                self.settings.PANOPTICON_API_URL,
                self.settings.PANOPTICON_API_KEY,
            )
        else:
            self.panopticon: Optional[PanopticonClient] = None

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
    # 参加申請管理系
    # ==============================

    group_application = group_management.create_subgroup(
        "application", "参加申請関連のコマンド"
    )

    # ===== 通知先チャンネルの設定 =====

    async def _autocomplete_sites(self, ctx: discord.AutocompleteContext):
        if self.panopticon is None:
            return []
        try:
            sites = await self.panopticon.get_sites()
            return [
                f"{site.unixName}: {site.name}"
                for site in sites
                if ctx.value in site.name or ctx.value in site.unixName
            ]
        except Exception:
            return []

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

        if self.panopticon is None:
            await ctx.followup.send(":x: APIが設定されていません", ephemeral=True)
            return

        # ctx.guildまたはctx.channelがない場合はエラー
        if ctx.guild is None or ctx.channel is None:
            await ctx.followup.send(
                ":x: サーバーチャンネル内で実行してください", ephemeral=True
            )
            return

        site_unix_name = site.split(":")[0]

        # サイト存在チェック
        srv_sites = await self.panopticon.get_sites()
        if site_unix_name not in [_s.unixName for _s in srv_sites]:
            await ctx.followup.send(":x: サイトが見つかりません", ephemeral=True)
            return

        # 既存のエントリ確認
        with db_session() as session:
            exist_entry = (
                session.query(SiteApplicationNotifyChannel)
                .filter_by(
                    guild_id=ctx.guild.id,
                    channel_id=ctx.channel.id,
                    site_unix_name=site_unix_name,
                )
                .first()
            )

            if exist_entry is None:
                # 新規作成
                session.add(
                    SiteApplicationNotifyChannel(
                        guild_id=ctx.guild.id,
                        channel_id=ctx.channel.id,
                        site_unix_name=site_unix_name,
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

        if self.panopticon is None:
            await ctx.followup.send(":x: APIが設定されていません", ephemeral=True)
            return

        srv_sites = {site.unixName: site for site in await self.panopticon.get_sites()}

        with db_session() as session:
            channels = (
                session.query(SiteApplicationNotifyChannel)
                .filter_by(guild_id=ctx.guild.id)
                .all()
            )
            msg = "\n".join(
                [
                    f"{ctx.guild.get_channel(channel.channel_id).mention} : {srv_sites.get(channel.site_unix_name, channel.site_unix_name)}"
                    for channel in channels
                ]
            )
            await ctx.followup.send(
                msg or "通知先チャンネルは登録されていません", ephemeral=True
            )

    # ===== 参加申請の処理系 =====
    @tasks.loop(minutes=10)
    async def check_site_applications(self):
        """
        参加申請を監視し、新しい申請があれば通知します
        """
        if self.panopticon is None:
            return

        with db_session() as session:
            channels = session.query(SiteApplicationNotifyChannel).all()
            for channel in channels:
                site_unix_name = channel.site_unix_name
                try:
                    # status=0 は PENDING
                    pending_applications, _ = await self.panopticon.get_applications(
                        site_unix_name=site_unix_name, status=0
                    )
                except Exception as e:
                    self.logger.error(f"Failed to get applications: {e}")
                    continue

                for pending in pending_applications:
                    # original_idで検索
                    exist_entry = (
                        session.query(SiteApplication)
                        .filter_by(
                            original_id=pending.id,
                            site_unix_name=site_unix_name,
                        )
                        .first()
                    )
                    if exist_entry is None:
                        # メッセージ送信
                        guild_obj = self.bot.get_guild(channel.guild_id)
                        if guild_obj is None:
                            continue
                        channel_obj = guild_obj.get_channel(channel.channel_id)
                        if channel_obj is None:
                            continue

                        application_text = pending.text

                        await channel_obj.send(
                            f"### 【{site_unix_name}】参加申請を受け取りました",
                            embed=discord.Embed(
                                title="参加申請", color=discord.Color.yellow()
                            )
                            .set_author(
                                name=pending.user.name,
                                url=f"https://www.wikidot.com/user:info/{pending.user.unixName}",
                                icon_url=pending.user.avatarUrl or "",
                            )
                            .set_footer(text=f"{pending.id}")
                            .add_field(
                                name="メッセージ",
                                value=application_text or "（メッセージなし）",
                                inline=False,
                            ),
                            view=views.ApplicationActionButtons(),
                        )

                        # DBに登録
                        session.add(
                            SiteApplication(
                                original_id=pending.id,
                                site_unix_name=site_unix_name,
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
