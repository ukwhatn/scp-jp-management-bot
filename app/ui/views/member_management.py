from typing import Optional

import discord
from httpx import HTTPStatusError

from core import get_settings
from db import db_session
from db.models import SiteApplication
from utils.panopticon_client import PanopticonClient
from utils.temporary_memory import TemporaryMemory

# インメモリキャッシュのインスタンス
temp_memory = TemporaryMemory()


def _get_panopticon_client() -> Optional[PanopticonClient]:
    settings = get_settings()
    if settings.PANOPTICON_API_URL and settings.PANOPTICON_API_KEY:
        return PanopticonClient(
            settings.PANOPTICON_API_URL,
            settings.PANOPTICON_API_KEY,
        )
    return None


async def _handle_request(
    interaction: discord.Interaction,
    accept: bool,
    decline_reason_type: Optional[int] = None,
    decline_reason: Optional[str] = None,
    original_message_id: Optional[int] = None,
):
    await interaction.response.defer(invisible=True)

    # 処理開始時のview変更
    await interaction.followup.edit_message(
        view=ApplicationHandlingStatusButtons(),
        message_id=interaction.message.id
        if original_message_id is None
        else original_message_id,
    )

    # Panopticon APIクライアントを初期化
    panopticon = _get_panopticon_client()
    if panopticon is None:
        return await interaction.followup.send(
            "APIが設定されていません。", ephemeral=True
        )

    # 処理開始
    with db_session() as session:
        # 元メッセージのembed[0]のfooter(=SiteApplication.id)を取得
        original_message = (
            interaction.message
            if original_message_id is None
            else await interaction.channel.fetch_message(original_message_id)
        )

        application_id = int(original_message.embeds[0].footer.text)

        db_application: Optional[SiteApplication] = (
            session.query(SiteApplication)
            .filter(SiteApplication.original_id == application_id)
            .first()
        )

        if not db_application:
            return await interaction.followup.send(
                "対象の参加申請が見つかりませんでした。", ephemeral=True
            )

        site_unix_name = db_application.site_unix_name

        # ボタン押下者のWikidotユーザ情報をPanopticonから取得
        try:
            bulk_result = await panopticon.link_bulk([str(interaction.user.id)])
        except Exception as e:
            return await interaction.followup.send(
                f"連携情報の取得に失敗しました: {e}", ephemeral=True
            )

        if not bulk_result or not bulk_result[0].linked or bulk_result[0].account is None:
            return await interaction.followup.send(
                "アカウント連携を完了してください。", ephemeral=True
            )

        wikidot_user_id = bulk_result[0].account.user.id
        wikidot_username = bulk_result[0].account.user.name

        # WikidotユーザがADMINパーミッションを持っているか確認する
        try:
            user_info = await panopticon.get_user(wikidot_user_id)
            has_admin = panopticon.has_admin_permission(
                user_info.permissions, site_unix_name
            )
        except Exception as e:
            return await interaction.followup.send(
                f"権限確認に失敗しました: {e}", ephemeral=True
            )

        if not has_admin:
            return await interaction.followup.send(
                "対象サイトのADMINパーミッションを持っていません。",
                ephemeral=True,
            )

        # 処理開始
        try:
            if accept:
                await panopticon.approve_application(
                    site_unix_name=site_unix_name,
                    app_id=application_id,
                )
            else:
                await panopticon.decline_application(
                    site_unix_name=site_unix_name,
                    app_id=application_id,
                    reason_type=decline_reason_type or 9,  # 9 = その他
                    reason_detail=decline_reason,
                )

            # 処理完了後:
            # - 元メッセージのviewを削除
            # - embedsにinline=Falseのフィールドを追加して処理完了と処理者を表示
            original_embed = original_message.embeds[0]
            new_embed = (
                discord.Embed(
                    title=original_embed.title,
                    description=original_embed.description,
                    color=discord.Color.green() if accept else discord.Color.red(),
                    author=original_embed.author,
                    fields=original_embed.fields,
                    timestamp=original_embed.timestamp,
                )
                .add_field(
                    name="ステータス",
                    value="承認済み" if accept else "却下済み",
                    inline=False,
                )
                .add_field(
                    name="処理者",
                    value=f"{interaction.user.mention} (as {wikidot_username})",
                    inline=False,
                )
            )

            if not accept:
                # 却下理由タイプの名前を取得
                reason_types = await panopticon.get_decline_reason_types()
                reason_type_name = next(
                    (rt.name for rt in reason_types if rt.id == decline_reason_type),
                    "不明"
                )
                new_embed.add_field(
                    name="却下理由",
                    value=reason_type_name,
                    inline=False,
                )
                new_embed.add_field(
                    name="却下理由詳細", value=decline_reason or "なし", inline=True
                )

            await interaction.followup.edit_message(
                view=None,
                embed=new_embed,
                message_id=interaction.message.id,
            )

        except HTTPStatusError as e:
            await interaction.followup.send(
                f"エラーが発生しました: {e.response.text}", ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"エラーが発生しました: {e}", ephemeral=True
            )


class ApplicationActionButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="承認",
        custom_id="application_action_btn_accept",
        style=discord.ButtonStyle.primary,
    )
    async def accept(self, _: discord.ui.Button, interaction: discord.Interaction):
        # 元メッセージのviewをApplicationAcceptConfirmationButtonsに変更
        await interaction.response.edit_message(
            view=ApplicationAcceptConfirmationButtons()
        )

    @discord.ui.button(
        label="却下",
        custom_id="application_action_btn_decline",
        style=discord.ButtonStyle.danger,
    )
    async def decline(self, _: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        # DeclineReasonTypeSelectorに変更
        panopticon = _get_panopticon_client()
        if panopticon is None:
            return await interaction.followup.send(
                "APIが設定されていません。", ephemeral=True
            )

        try:
            reason_types = await panopticon.get_decline_reason_types()
            # dict形式に変換（id -> name）
            reason_types_dict = {str(rt.id): rt.name for rt in reason_types}
        except Exception as e:
            return await interaction.followup.send(
                f"却下理由の取得に失敗しました: {e}", ephemeral=True
            )

        await interaction.followup.edit_message(
            view=DeclineReasonTypeSelector(reason_types_dict),
            message_id=interaction.message.id,
        )


class ApplicationAcceptConfirmationButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="承認処理を開始",
        custom_id="application_accept_confirm_btn",
        style=discord.ButtonStyle.success,
    )
    async def accept(self, button: discord.ui.Button, interaction: discord.Interaction):
        await _handle_request(interaction, accept=True)

    @discord.ui.button(
        label="キャンセル",
        custom_id="application_accept_cancel_btn",
        style=discord.ButtonStyle.secondary,
    )
    async def cancel(self, _: discord.ui.Button, interaction: discord.Interaction):
        # 元メッセージのviewをApplicationActionButtonsに変更
        await interaction.response.edit_message(view=ApplicationActionButtons())


class ApplicationDeclineReasonInputModal(discord.ui.Modal):
    def __init__(self, original_message_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_message_id = original_message_id

        self.add_item(
            discord.ui.InputText(
                label="却下理由詳細",
                placeholder="却下理由を入力してください（任意）",
                required=False,
                style=discord.InputTextStyle.long,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        original_message_id = self.original_message_id
        decline_reason = self.children[0].value or ""

        # インメモリキャッシュから却下理由タイプを取得
        decline_reason_type = temp_memory.get(original_message_id)

        # 処理開始
        await _handle_request(
            interaction,
            accept=False,
            decline_reason_type=int(decline_reason_type),
            decline_reason=decline_reason,
            original_message_id=original_message_id,
        )

        # インメモリキャッシュから削除
        temp_memory.delete(original_message_id)


class ApplicationHandlingStatusButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="処理中......",
        custom_id="application_handling_status_btn_processing",
        style=discord.ButtonStyle.primary,
        disabled=True,
    )
    async def processing(self, _: discord.ui.Button, interaction: discord.Interaction):
        pass

    @discord.ui.button(
        label="リセット(異常時用)",
        custom_id="application_handling_status_btn_reset",
        style=discord.ButtonStyle.secondary,
    )
    async def reset(self, _: discord.ui.Button, interaction: discord.Interaction):
        # 元メッセージのviewをApplicationActionButtonsに変更
        await interaction.response.edit_message(view=ApplicationActionButtons())


class DeclineReasonTypeSelector(discord.ui.View):
    """persistentではない"""

    def __init__(self, types: dict[str, str]):
        super().__init__(timeout=None)
        self.types = types

        self.options = [
            discord.SelectOption(
                label=_value,
                value=_key_str,
            )
            for _key_str, _value in self.types.items()
        ]
        self.select = discord.ui.Select(
            placeholder="却下理由を選択",
            options=self.options,
            custom_id="decline_reason_type_selector",
            min_values=1,
            max_values=1,
        )
        self.select.callback = self._select_callback
        self.add_item(self.select)

    async def _select_callback(self, interaction: discord.Interaction):
        selected_option = self.select.values[0]
        original_message = interaction.message
        # インメモリキャッシュに保存
        temp_memory.set(original_message.id, selected_option)

        # modalを展開
        await interaction.response.send_modal(
            ApplicationDeclineReasonInputModal(
                original_message_id=original_message.id,
                title="却下理由を入力",
            )
        )

    @discord.ui.button(
        label="リセット(間違えたとき)",
        custom_id="application_handling_status_btn_reset",
        style=discord.ButtonStyle.secondary,
    )
    async def reset(self, _: discord.ui.Button, interaction: discord.Interaction):
        # 元メッセージのviewをApplicationActionButtonsに変更
        await interaction.response.edit_message(view=ApplicationActionButtons())
