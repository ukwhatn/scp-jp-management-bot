import discord
from httpx import HTTPStatusError
from scp_jp.api import MemberManagementAPIClient, LinkerAPIClient
from scp_jp.api.member_management import PermissionLevel, DeclineReasonType

from core import get_settings
from db import db_session
from db.models import SiteApplication


# インメモリキャッシュ
class TemporaryMemory:
    def __init__(self):
        self.memory = {}

    def set(self, key, value):
        self.memory[key] = value

    def get(self, key):
        return self.memory.get(key)

    def delete(self, key):
        del self.memory[key]


# インメモリキャッシュのインスタンス
temp_memory = TemporaryMemory()


async def _handle_request(
    interaction: discord.Interaction,
    accept: bool,
    decline_reason_type: DeclineReasonType | None = None,
    decline_reason: str | None = None,
    original_message_id: int | None = None,
):
    await interaction.response.defer(invisible=True)

    # 処理開始時のview変更
    await interaction.followup.edit_message(
        view=ApplicationHandlingStatusButtons(),
        message_id=interaction.message.id
        if original_message_id is None
        else original_message_id,
    )

    # LinkerAPIとMemberManagementAPIのクライアントを初期化
    settings = get_settings()
    client_l = LinkerAPIClient(
        base_url=settings.LINKER_API_URL,
        api_key=settings.LINKER_API_KEY,
    )
    client_m = MemberManagementAPIClient(
        base_url=settings.MEMBER_MANAGEMENT_API_URL,
        api_key=settings.MEMBER_MANAGEMENT_API_KEY,
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

        db_application: SiteApplication | None = (
            session.query(SiteApplication)
            .filter(SiteApplication.original_id == application_id)
            .first()
        )

        if not db_application:
            return await interaction.followup.send(
                "対象の参加申請が見つかりませんでした。", ephemeral=True
            )

        # ボタン押下者のWikidotユーザ情報をLinkerから取得 -> reviewer_id取得
        linker_data = (await client_l.account_list([interaction.user.id])).result

        if str(interaction.user.id) not in linker_data:
            return await interaction.followup.send(
                "Linkerに登録してください。", ephemeral=True
            )

        wikidot_users = linker_data[str(interaction.user.id)].wikidot

        reviewer = None
        for wikidot_user in wikidot_users:
            # WikidotユーザがADMINパーミッションを持っているか確認する
            _check = await client_m.check_site_member_permission(
                db_application.site_id, wikidot_user.id, PermissionLevel.ADMIN
            )
            if _check:
                reviewer = wikidot_user
                break

        if not reviewer:
            return await interaction.followup.send(
                "ADMINパーミッションを持っているWikidotユーザが見つかりませんでした。",
                ephemeral=True,
            )

        # 処理開始
        try:
            if accept:
                await client_m.approve_application_request(
                    request_id=application_id,
                    reviewer_id=reviewer.id,
                )
            else:
                await client_m.decline_application_request(
                    request_id=application_id,
                    reviewer_id=reviewer.id,
                    decline_reason_type=decline_reason_type,
                    decline_reason_detail=decline_reason,
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
                    value=f"{interaction.user.mention} (as {reviewer.username})",
                    inline=False,
                )
            )

            if not accept:
                reason_types_ja = await client_m.get_decline_reason_types()
                new_embed.add_field(
                    name="却下理由",
                    value=reason_types_ja[str(decline_reason_type.value)],
                    inline=False,
                )
                new_embed.add_field(
                    name="却下理由詳細", value=decline_reason, inline=True
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
        reason_types = await MemberManagementAPIClient(
            base_url=get_settings().MEMBER_MANAGEMENT_API_URL,
            api_key=get_settings().MEMBER_MANAGEMENT_API_KEY,
        ).get_decline_reason_types()
        await interaction.followup.edit_message(
            view=DeclineReasonTypeSelector(reason_types),
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
            decline_reason_type=DeclineReasonType(int(decline_reason_type)),
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
