import logging
from datetime import datetime

import discord
import httpx
from discord.ext import commands, tasks
from scp_jp.api import MemberManagementAPIClient

from core import get_settings
from db.connection import db_session
from db.models.privilege_management import PrivilegeRemoveQueue
from ui.views.privilege_management import GetPrivilegeButton, PrivilegeRemoveButton


class PrivilegeManagement(commands.Cog):
    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.settings = get_settings()
        self.logger = logging.getLogger("discord")

    # ==============================
    # イベントハンドラ
    # ==============================
    @commands.Cog.listener()
    async def on_ready(self):
        # viewの登録
        self.bot.add_view(GetPrivilegeButton())
        self.bot.add_view(PrivilegeRemoveButton())

        # タスクの開始
        self.privilege_remover.start()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.privilege_remover.is_running():
            self.privilege_remover.start()

    # ==============================
    # Cog全体のサブコマンド
    # ==============================

    group_privilege = discord.SlashCommandGroup(
        "privilege", "スタッフの権限昇格を管理するコマンド群"
    )

    # ==============================
    # 承認処理の追加
    # ==============================

    @group_privilege.command(
        name="send_panel", description="スタッフの権限昇格を管理するパネルを表示します"
    )
    async def send_panel(self, ctx: discord.ApplicationContext):
        await ctx.respond(
            "\n".join(
                [
                    "## 権限昇格管理パネル",
                    "Wiki上で権限を取得する場合は、以下のボタンを押してください。",
                    "",
                    "- 権限は、システム上の権限レベルに合わせてAdmin/Moderatorが自動的に選択されます",
                    "- 権限の取得・剥奪は記録されます",
                    "- 権限は1時間後に自動的に剥奪されます",
                    "",
                    "- **この作業を実施することについてスタッフ合意を取っていない場合は、まずリアクション投票による合意形成を行ってください**",
                ]
            ),
            view=GetPrivilegeButton(),
        )

    # ==============================
    # タスク
    # ==============================

    @tasks.loop(minutes=1)
    async def privilege_remover(self):
        with db_session() as session:
            # expired_atが過ぎた権限剥奪リクエストを取得
            expired_queues = (
                session.query(PrivilegeRemoveQueue)
                .filter(PrivilegeRemoveQueue.expired_at <= datetime.now())
                .all()
            )

            c_manage = MemberManagementAPIClient(
                self.settings.MEMBER_MANAGEMENT_API_URL,
                self.settings.MEMBER_MANAGEMENT_API_KEY,
            )

            for queue in expired_queues:
                try:
                    # get instances
                    user = self.bot.get_user(queue.dc_user_id)
                    guild = self.bot.get_guild(queue.notify_guild_id)
                    channel = guild.get_channel(queue.notify_channel_id)
                    message = await channel.fetch_message(queue.notify_message_id)

                    # remove privilege
                    await c_manage.change_site_member_privilege(
                        site_id=queue.wd_site_id,
                        user_id=queue.wd_user_id,
                        action="remove_" + queue.permission_level,
                    )
                except httpx.HTTPStatusError as e:
                    json = e.response.json()
                    if "User is not moderator/admin:" in json["message"]:
                        pass

                finally:
                    # notify message
                    await message.reply(
                        f"{user.mention} 権限を削除しました",
                        delete_after=5,
                    )
                    # delete message
                    await message.delete(delay=5)

                    # delete queue
                    session.delete(queue)
                    session.commit()


def setup(bot):
    return bot.add_cog(PrivilegeManagement(bot))
