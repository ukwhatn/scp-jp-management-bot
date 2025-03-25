import datetime
import logging

import discord
from discord.ext import commands, tasks

from core import get_settings
from db.connection import db_session
from db.models import (
    StaffRequest as DbSr,
)
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
        self.bot.add_view(Flow1TargetSelector())
        self.bot.add_view(Flow2ConfirmView())
        self.bot.add_view(RequestDMController())
        self.bot.add_view(RequestDMControllerIsDone())
        self.bot.add_view(RequestSummaryController())
        self.bot.add_view(RequestSummaryFinishController())

        # リマインダーの開始
        self.remind_watcher.start()
        self.due_date_watcher.start()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.remind_watcher.is_running():
            self.remind_watcher.start()

        if not self.due_date_watcher.is_running():
            self.due_date_watcher.start()

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

    # ==============================
    # タスク
    # ==============================

    @tasks.loop(hours=1)
    async def due_date_watcher(self):
        # due_dateを過ぎたタスクをcreated_by_idに通知する
        with db_session() as db:
            # 親エントリからdue_dateが過ぎた、かつis_due_date_notifiedがFalseなものを取得
            staff_requests = db.query(DbSr).filter(
                DbSr.due_date < datetime.date.today(),
                DbSr.is_due_date_notified.is_(False),
            ).all()

            for sr in staff_requests:
                # pendingなタスクがなければスキップ
                if len(sr.pending_users) == 0:
                    continue

                author = self.bot.get_user(sr.created_by_id)
                original_guild = self.bot.get_guild(sr.summary_message_guild_id)
                original_channel = original_guild.get_channel(sr.summary_message_channel_id)
                original_message = await original_channel.fetch_message(sr.summary_message_id)

                await original_message.reply(
                    f"{author.mention} 依頼の期限が過ぎました\n"
                )

                # is_due_date_notifiedをTrueに更新
                sr.is_due_date_notified = True
                db.commit()

                self.logger.info(f"[Staff Request] {sr.title} の締切超過を通知しました")

    @tasks.loop(hours=1)
    async def remind_watcher(self):
        with db_session() as db:
            # 親エントリを全取得
            staff_requests = db.query(DbSr).all()

            for sr in staff_requests:
                # pendingなタスクがなければスキップ
                if len(sr.pending_users) == 0:
                    continue

                # due_dateを過ぎていればスキップ
                if sr.due_date is not None and sr.due_date < datetime.date.today():
                    continue

                # last_remind_atがNone -> created_atから2日経過
                # last_remind_atがある -> last_remind_atから2日経過
                if sr.last_remind_at is None:
                    remind_time = sr.created_at + datetime.timedelta(days=2)
                else:
                    remind_time = sr.last_remind_at + datetime.timedelta(days=2)

                # 現在時刻を取得（タイムゾーン情報を一致させる）
                now = datetime.datetime.now(datetime.timezone.utc)

                # remind_timeがnaiveの場合はawareに変換
                if remind_time.tzinfo is None:
                    remind_time = remind_time.replace(tzinfo=datetime.timezone.utc)

                # 現在時刻がリマインド時間を過ぎている場合
                if now >= remind_time:
                    # リマインド時間を更新
                    sr.last_remind_at = now
                    db.commit()

                    # リマインドメッセージを送信
                    # 対象のユーザを取得
                    for sr_u in sr.pending_users:
                        # DMを送信
                        _du = self.bot.get_user(sr_u.user_id)
                        if _du is None:
                            self.logger.warning(f"ユーザID {sr_u.user_id} が見つかりません")
                            continue

                        _dm = await _du.create_dm()

                        # メッセージを取得
                        _dm_msg = await _dm.fetch_message(sr_u.dm_message_id)

                        msg_content = "**対応が必要な依頼があります。ご確認ください。**"
                        if sr.due_date is not None:
                            msg_content += f"\n> 期限: {sr.due_date.strftime('%Y/%m/%d')}"

                        # replyでリマインド
                        await _dm_msg.reply(msg_content)

                        self.logger.info(
                            f"[Staff Request] {sr.title} のリマインドを {_du.display_name} に送信しました"
                        )


def setup(bot):
    return bot.add_cog(StaffRequest(bot))
