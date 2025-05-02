from datetime import datetime

import discord

from db.connection import db_session
from db.models.staff_request import (
    StaffRequest,
    StaffRequestUser,
    StaffRequestStatus,
)
from utils.temporary_memory import TemporaryMemory

# インメモリキャッシュのインスタンス
temp_memory = TemporaryMemory()


class CommonFunctions:
    @staticmethod
    def create_summary_embed(
        staff_request: StaffRequest,
        guild: discord.Guild,
        title: str = "スタッフへの確認依頼",
        color: discord.Color = discord.Color.teal(),
    ):
        # created_by_idからユーザ取得
        created_by = guild.get_member(staff_request.created_by_id)

        # Embed作成
        embed = (
            discord.Embed(
                color=color,
                title=title,
                timestamp=datetime.now(),
            )
            .add_field(name="タイトル", value=staff_request.title, inline=False)
            .add_field(name="説明", value=staff_request.description, inline=False)
            .add_field(name="URL", value=staff_request.url, inline=False)
            .add_field(
                name="期限",
                value=staff_request.due_date.strftime("%Y/%m/%d")
                if staff_request.due_date
                else "未設定",
                inline=False,
            )
        )

        if created_by:
            embed.set_author(
                name=created_by.display_name,
                icon_url=created_by.display_avatar.url,
            )

        # ステータスを順に追加
        for status in StaffRequestStatus:
            users = getattr(staff_request, f"{status.name.lower()}_users")
            if not users:
                continue

            discord_users = []
            for user in users:
                discord_user = guild.get_member(user.user_id)
                if discord_user:
                    discord_users.append(discord_user)
                    continue

            embed.add_field(
                name=f"ステータス: {StaffRequestStatus.name_ja(status)} -> {len(users)}名",
                value=" ".join([_du.mention for _du in discord_users])
                if len(users) > 0
                else "なし",
                inline=False,
            )

        return embed


class Flow1TargetSelector(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(
        select_type=discord.ComponentType.mentionable_select,
        custom_id="staff_request_flow1_target_selector_select_targets",
        placeholder="依頼対象を選択してください",
        min_values=1,
        max_values=25,
        disabled=False,
    )
    async def select_targets(
        self, _: discord.ui.Select, interaction: discord.Interaction
    ):
        # defer
        await interaction.response.defer()

        # メッセージを取得
        message = interaction.message

        # インメモリキャッシュからデータを取得
        data = temp_memory.get(message.id)

        # データが存在しない場合はエラー
        if data is None:
            await interaction.followup.send(
                "データが見つかりませんでした。", ephemeral=True
            )
            return

        # 入力値を取得
        raw_targets: list[str] = interaction.data["values"]

        # 入力値変換
        targets: list[discord.User | discord.Member] = []
        target_ids: list[int] = []
        for target_id in raw_targets:
            # roleから取得
            target = message.guild.get_role(int(target_id))
            if target:
                for m in target.members:
                    if m.id in target_ids:
                        continue
                    if m.bot:
                        continue
                    targets.append(m)
                    target_ids.append(m.id)
                continue

            # 引っかからなかったらuserを取得
            target = message.guild.get_member(int(target_id))
            if target:
                if target.id in target_ids:
                    continue
                if target.bot:
                    continue

                targets.append(target)
                target_ids.append(target.id)
                continue

            # userが見つからない場合はエラー
            await interaction.followup.send(
                f"ID: {target_id} に対応するユーザが見つかりませんでした。",
                ephemeral=True,
            )

        # インメモリキャッシュに保存
        data["targets"] = targets

        # original messageのembedに追加
        embed = message.embeds[0]
        embed.add_field(
            name="依頼対象",
            value=" ".join([target.mention for target in targets]),
            inline=False,
        )

        # 更新
        await interaction.followup.edit_message(
            message_id=interaction.message.id, embed=embed, view=Flow2ConfirmView()
        )

        # インメモリキャッシュに保存
        temp_memory.set(message.id, data)


class Flow2ConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="続行",
        custom_id="staff_request_flow2_confirm_button",
        style=discord.ButtonStyle.primary,
    )
    async def confirm_btn(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        # defer
        await interaction.response.defer()

        message = interaction.message

        # インメモリキャッシュからデータを取得
        data = temp_memory.get(message.id)

        # データが存在しない場合はエラー
        if data is None:
            await interaction.followup.send(
                "データが見つかりませんでした。", ephemeral=True
            )
            return

        # ---- サマリメッセージの作成 ----

        staff_request = StaffRequest(
            summary_message_guild_id=interaction.message.guild.id,
            summary_message_channel_id=interaction.message.channel.id,
            created_by_id=interaction.user.id,
            title=data["title"],
            description=data["description"],
            url=data["url"],
            due_date=data["due_date"],
        )

        summary_msg = await interaction.followup.send(
            embed=CommonFunctions.create_summary_embed(
                staff_request, interaction.message.guild
            ).add_field(
                name=f"ステータス: 未対応 -> {len(data['targets'])}名",
                value=" ".join([target.mention for target in data["targets"]])
                if len(data["targets"]) > 0
                else "なし",
                inline=False,
            ),
            view=RequestSummaryController(),
        )

        staff_request.summary_message_id = summary_msg.id

        with db_session() as db:
            # ---- 稟議の登録 ----
            db.add(staff_request)
            db.flush()

            # ---- 稟議ユーザの登録 ----
            sent_user_ids = []
            for target in data["targets"]:
                if target.id in sent_user_ids:
                    continue

                # DM送信
                dm = await target.create_dm()
                dm_message_embed = (
                    discord.Embed(
                        title="確認依頼",
                        description=f"{interaction.user.mention} さんから確認依頼が届いています。",
                        color=discord.Color.orange(),
                        url=summary_msg.jump_url,
                    )
                    .add_field(name="タイトル", value=staff_request.title, inline=False)
                    .add_field(
                        name="説明", value=staff_request.description, inline=False
                    )
                    .add_field(name="URL", value=staff_request.url, inline=False)
                    .add_field(
                        name="期限",
                        value=staff_request.due_date.strftime("%Y/%m/%d")
                        if staff_request.due_date
                        else "未設定",
                        inline=False,
                    )
                )

                dm_message = await dm.send(
                    embed=dm_message_embed, view=RequestDMController()
                )

                staff_request_user = StaffRequestUser(
                    user_id=target.id,
                    dm_message_id=dm_message.id,
                    status=StaffRequestStatus.PENDING,
                )
                staff_request.users.append(staff_request_user)
                db.add(staff_request_user)

                sent_user_ids.append(target.id)

        db.commit()

        # ---- 元メッセージの削除 ----
        await interaction.followup.delete_message(message_id=message.id)


class RequestDMController(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="対応しました",
        custom_id="request_dm_ctl_status_change_to_done",
        style=discord.ButtonStyle.success,
    )
    async def status_change_to_done(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        await interaction.response.defer()

        with db_session() as db:
            # 稟議ユーザの取得
            staff_request_user = (
                db.query(StaffRequestUser)
                .filter(StaffRequestUser.dm_message_id == interaction.message.id)
                .one_or_none()
            )

            # 稟議ユーザが存在しない場合はエラー
            if staff_request_user is None:
                await interaction.followup.send(
                    "DBエントリが見つかりませんでした。", ephemeral=True
                )
                return

            # ステータスの変更
            staff_request_user.status = StaffRequestStatus.DONE
            db.commit()
            db.refresh(staff_request_user)

            # DMメッセージを更新
            dm_embed = interaction.message.embeds[0]
            dm_embed.colour = discord.Color.green()
            dm_embed.set_footer(text="対応済")

            await interaction.message.edit(
                embed=dm_embed, view=RequestDMControllerIsDone()
            )

            # 元メッセージを更新
            summary_guild_id = staff_request_user.staff_request.summary_message_guild_id
            summary_channel_id = (
                staff_request_user.staff_request.summary_message_channel_id
            )
            summary_message_id = staff_request_user.staff_request.summary_message_id

            summary_guild = interaction.client.get_guild(summary_guild_id)

            if summary_guild is None:
                summary_guild = await interaction.client.fetch_guild(summary_guild_id)

            summary_channel = summary_guild.get_channel(summary_channel_id)

            if summary_channel is None:
                summary_channel = await summary_guild.fetch_channel(summary_channel_id)

            summary_message = await summary_channel.fetch_message(summary_message_id)

            await summary_message.edit(
                embed=CommonFunctions.create_summary_embed(
                    staff_request_user.staff_request, summary_guild
                ),
                view=RequestSummaryController(),
            )

            # pendingが居なくなった場合、通知する
            if len(staff_request_user.staff_request.pending_users) == 0:
                await summary_message.reply(
                    f"<@{staff_request_user.staff_request.created_by_id}> 全ての依頼者の対応が完了しました"
                )


class RequestDMControllerIsDone(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="未対応に戻す",
        custom_id="request_dm_ctl_status_change_to_pending",
        style=discord.ButtonStyle.secondary,
    )
    async def status_change_to_pending(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        await interaction.response.defer()

        with db_session() as db:
            # 稟議ユーザの取得
            staff_request_user = (
                db.query(StaffRequestUser)
                .filter(StaffRequestUser.dm_message_id == interaction.message.id)
                .one_or_none()
            )

            # 稟議ユーザが存在しない場合はエラー
            if staff_request_user is None:
                await interaction.followup.send(
                    "DBエントリが見つかりませんでした。", ephemeral=True
                )
                return

            # ステータスの変更
            staff_request_user.status = StaffRequestStatus.PENDING
            db.commit()
            db.refresh(staff_request_user)

            # DMメッセージを更新
            dm_embed = interaction.message.embeds[0]
            dm_embed.colour = discord.Color.orange()
            dm_embed.set_footer(text="未対応")

            await interaction.message.edit(embed=dm_embed, view=RequestDMController())

            # 元メッセージを更新
            summary_guild_id = staff_request_user.staff_request.summary_message_guild_id
            summary_channel_id = (
                staff_request_user.staff_request.summary_message_channel_id
            )
            summary_message_id = staff_request_user.staff_request.summary_message_id

            summary_guild = interaction.client.get_guild(summary_guild_id)
            summary_channel = summary_guild.get_channel(summary_channel_id)
            summary_message = await summary_channel.fetch_message(summary_message_id)

            await summary_message.edit(
                embed=CommonFunctions.create_summary_embed(
                    staff_request_user.staff_request, summary_guild
                ),
                view=RequestSummaryController(),
            )


class RequestSummaryController(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="終了（締切またはキャンセル）",
        custom_id="application_summary_controller_finish",
        style=discord.ButtonStyle.danger,
    )
    async def finish(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.edit_message(view=RequestSummaryFinishController())


class RequestSummaryFinishController(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="締切",
        custom_id="application_summary_controller_finish_due_date",
        style=discord.ButtonStyle.success,
    )
    async def finish_due_date(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        await interaction.response.defer()

        with db_session() as db:
            # 稟議の取得
            staff_request = (
                db.query(StaffRequest)
                .filter(StaffRequest.summary_message_id == interaction.message.id)
                .one_or_none()
            )

            # 稟議が存在しない場合はエラー
            if staff_request is None:
                await interaction.followup.send(
                    "DBエントリが見つかりませんでした。", ephemeral=True
                )
                return

            # DMメッセージを更新
            for user in staff_request.pending_users:
                _du = interaction.guild.get_member(user.user_id)
                if _du is None:
                    continue

                _dm = await _du.create_dm()

                dm_message = await _dm.fetch_message(user.dm_message_id)

                if not dm_message:
                    continue

                dm_embed = dm_message.embeds[0]
                dm_embed.colour = discord.Color.red()
                dm_embed.set_footer(text="締め切られました")
                await dm_message.edit(embed=dm_embed, view=None)

                user.status = StaffRequestStatus.EXPIRED

            db.commit()
            db.refresh(staff_request)

            # サマリメッセージを更新
            await interaction.message.edit(
                embed=CommonFunctions.create_summary_embed(
                    staff_request,
                    interaction.guild,
                    title="[締切]スタッフへの確認依頼",
                    color=discord.Color.light_gray(),
                ),
                view=None,
            )

    @discord.ui.button(
        label="キャンセル",
        custom_id="application_summary_controller_finish_cancel",
        style=discord.ButtonStyle.danger,
    )
    async def finish_cancel(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        await interaction.response.defer()

        with db_session() as db:
            # 稟議の取得
            staff_request = (
                db.query(StaffRequest)
                .filter(StaffRequest.summary_message_id == interaction.message.id)
                .one_or_none()
            )

            # 稟議が存在しない場合はエラー
            if staff_request is None:
                await interaction.followup.send(
                    "DBエントリが見つかりませんでした。", ephemeral=True
                )
                return

            # DMメッセージを更新
            for user in staff_request.pending_users:
                _du = interaction.guild.get_member(user.user_id)
                if _du is None:
                    continue

                _dm = await _du.create_dm()

                dm_message = await _dm.fetch_message(user.dm_message_id)

                if not dm_message:
                    continue

                dm_embed = dm_message.embeds[0]
                dm_embed.colour = discord.Color.red()
                dm_embed.set_footer(text="キャンセルされました")
                await dm_message.edit(embed=dm_embed, view=None)

                user.status = StaffRequestStatus.CANCELED_BY_REQUESTER

            db.commit()
            db.refresh(staff_request)

            # サマリメッセージを更新
            await interaction.message.edit(
                embed=CommonFunctions.create_summary_embed(
                    staff_request,
                    interaction.guild,
                    title="[キャンセル]スタッフへの確認依頼",
                    color=discord.Color.dark_red(),
                ),
                view=None,
            )

    @discord.ui.button(
        label="戻る",
        custom_id="application_summary_controller_finish_back",
        style=discord.ButtonStyle.secondary,
    )
    async def finish_back(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        # viewを戻す
        await interaction.response.edit_message(view=RequestSummaryController())


class DetailsInputModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs, title="確認依頼作成")

        self.add_item(
            discord.ui.InputText(
                style=discord.InputTextStyle.short,
                custom_id="staff_request_title_input",
                label="タイトル",
                placeholder="タイトルを入力してください",
                required=True,
            )
        )

        self.add_item(
            discord.ui.InputText(
                style=discord.InputTextStyle.long,
                custom_id="staff_request_description_input",
                label="説明(任意)",
                placeholder="タスクの説明・詳細を入力してください(任意)",
                required=False,
            )
        )

        self.add_item(
            discord.ui.InputText(
                style=discord.InputTextStyle.short,
                custom_id="staff_request_url_input",
                label="URL(任意)",
                placeholder="関連URLを入力してください(任意)",
                required=False,
            )
        )

        self.add_item(
            discord.ui.InputText(
                style=discord.InputTextStyle.short,
                custom_id="staff_request_due_date_input",
                label="期限(任意)",
                placeholder="期限日があれば、YYYY/MM/DD形式で入力してください(任意)",
                required=False,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        # defer
        await interaction.response.defer()

        # 各値を取得
        title = self.children[0].value
        description = self.children[1].value
        url = self.children[2].value
        due_date_str = self.children[3].value

        # guild channel/thread以外での実行を禁止
        if not interaction.guild:
            await interaction.followup.send(
                "このコマンドはサーバー内でのみ実行可能です。", ephemeral=True
            )
            return

        # due_dateの変換
        due_date = None
        if due_date_str:
            try:
                due_date = datetime.strptime(due_date_str, "%Y/%m/%d").date()
            except ValueError:
                await interaction.followup.send(
                    "\n".join(
                        [
                            "期限日の形式が正しくありません。YYYY/MM/DD形式で入力してください。",
                            "入力値(コピー用): ",
                            "```",
                            title or "未入力",
                            "```",
                            "```",
                            description or "未入力",
                            "```",
                            "```",
                            url or "未入力",
                            "```",
                            "```",
                            due_date_str or "未入力",
                            "```",
                        ]
                    ),
                    ephemeral=True,
                )
                return

        # Embed作成
        embed = discord.Embed(
            color=discord.Color.blue(),
            title="スタッフへの確認依頼",
            description="確認依頼の作成はまだ完了していません、引き続き入力を実施してください。",
        )
        embed.add_field(name="タイトル", value=title or "未入力", inline=False)
        embed.add_field(name="説明", value=description or "未入力", inline=False)
        embed.add_field(name="URL", value=url or "未入力", inline=False)
        embed.add_field(name="期限", value=due_date_str or "未入力", inline=False)

        # 送信
        message = await interaction.followup.send(
            embed=embed, ephemeral=True, view=Flow1TargetSelector()
        )

        # インメモリキャッシュに保存
        temp_memory.set(
            message.id,
            {
                "title": title,
                "description": description,
                "url": url,
                "due_date": due_date,
                "message": message,
            },
        )
