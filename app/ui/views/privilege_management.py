import datetime

import discord
from httpx import HTTPStatusError
from scp_jp.api import MemberManagementAPIClient, LinkerAPIClient
from scp_jp.api.linker import AccountResponseWikidotBaseSchema
from scp_jp.api.member_management import PermissionLevel, SiteWithMembersCount

from core import get_settings
from db import db_session
from db.models import PrivilegeRemoveQueue


class GetPrivilegeButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Wiki上での権限を取得する",
        custom_id="get_privilege_button",
        style=discord.ButtonStyle.danger,
        emoji="⚠️",
    )
    async def get_privilege_button(
            self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        # defer
        await interaction.response.defer()

        # client
        settings = get_settings()
        c_manage = MemberManagementAPIClient(
            settings.MEMBER_MANAGEMENT_API_URL,
            settings.MEMBER_MANAGEMENT_API_KEY,
        )
        sites = await c_manage.get_sites()

        await interaction.followup.send(
            "権限を取得するサイトを選択してください",
            ephemeral=True,
            view=GetPrivilegeSiteSelector(sites)
        )


class GetPrivilegeSiteSelector(discord.ui.View):
    def __init__(self, sites: list[SiteWithMembersCount]):
        super().__init__(timeout=None)
        self.sites = {site.id: site for site in sites}

        options = [
            discord.SelectOption(
                label=site.name.upper(),
                value=str(site.id),
            )
            for site in sites
        ]

        self.select = discord.ui.Select(
            placeholder="サイトを選択してください",
            options=options,
            custom_id="get_privilege_site_selector",
            max_values=1,
            min_values=1,
        )
        self.select.callback = self._select_callback
        self.add_item(self.select)

    async def _select_callback(self, interaction: discord.Interaction):
        try:
            # defer
            await interaction.response.defer()

            await interaction.followup.edit_message(
                content="処理中です.....",
                view=None,
                message_id=interaction.message.id
            )

            # get selected site
            selected_site_id = int(self.select.values[0])

            # client
            settings = get_settings()
            c_manage = MemberManagementAPIClient(
                settings.MEMBER_MANAGEMENT_API_URL,
                settings.MEMBER_MANAGEMENT_API_KEY,
            )
            c_linker = LinkerAPIClient(
                settings.LINKER_API_URL,
                settings.LINKER_API_KEY,
            )

            # linkerでリンクされたアカウントを取得
            dc_user = interaction.user
            linker_response = await c_linker.account_list([dc_user.id])

            wikidot_accounts = linker_response.result[str(dc_user.id)].wikidot

            if not wikidot_accounts or len(wikidot_accounts) == 0:
                await interaction.followup.send(
                    f"{interaction.user.mention}\nあなたのアカウントはWikiにリンクされていません",
                )
                return

            target_wd_account: AccountResponseWikidotBaseSchema | None = None
            target_permission_level: PermissionLevel | None = None

            # linkerでリンクされたアカウントの中から対象サイトで権限を持っているアカウントを取得
            for wd_acc in wikidot_accounts:
                try:
                    _wd_acc = await c_manage.get_user(wd_acc.id)

                    for _membership in _wd_acc.site_memberships:
                        if _membership["site_id"] == selected_site_id:
                            if _membership["permission_level"] >= PermissionLevel.MODERATOR:
                                target_wd_account = wd_acc
                                target_permission_level = _membership["permission_level"]
                                break
                except HTTPStatusError:
                    continue

            # 権限を持っているアカウントが見つからなかった場合
            if target_wd_account is None:
                await interaction.followup.send(
                    f"{interaction.user.mention}\nあなたのDiscordアカウントにリンクされたWikidotアカウントに、適切な権限を有するものが見つかりませんでした"
                )
                return

            # 権限昇格を実施
            action = "to_admin" if target_permission_level >= PermissionLevel.ADMIN else "to_moderator"
            try:
                await c_manage.change_site_member_privilege(
                    site_id=selected_site_id,
                    user_id=target_wd_account.id,
                    action=action,
                )
                notify_msg_partial = await interaction.followup.send(
                    f"### Wikidotアカウントの権限を昇格しました\n"
                    f"> ユーザ: {interaction.user.name} ({target_wd_account.username})\n"
                    f"> サイト: {self.sites[selected_site_id].name}\n"
                    f"> 権限: {action.removeprefix('to_')}",
                    view=PrivilegeRemoveButton()
                )
            except HTTPStatusError as e:
                await interaction.followup.send(
                    f"{interaction.user.mention} 権限の昇格に失敗しました\n"
                    f"> エラーコード: {e.response.status_code}\n"
                    f"> エラーメッセージ: {e.response.text}",
                )
                return

            with db_session() as session:
                # 権限剥奪キューに追加
                # expired_atは1時間後
                notify_msg = await interaction.channel.fetch_message(notify_msg_partial.id)
                privilege_remove_queue = PrivilegeRemoveQueue(
                    dc_user_id=interaction.user.id,
                    wd_user_id=target_wd_account.id,
                    wd_site_id=selected_site_id,
                    notify_guild_id=notify_msg.guild.id,
                    notify_channel_id=notify_msg.channel.id,
                    notify_message_id=notify_msg.id,
                    permission_level=action.removeprefix("to_").lower(),
                    expired_at=datetime.datetime.now() + datetime.timedelta(hours=1),
                )
                session.add(privilege_remove_queue)
                session.commit()
        finally:
            # selector削除
            await interaction.followup.delete_message(message_id=interaction.message.id)


class PrivilegeRemoveButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="権限を削除する",
        custom_id="remove_privilege_button",
        style=discord.ButtonStyle.success,
        emoji="✅",
    )
    async def remove_privilege_button(
            self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        # defer
        await interaction.response.defer()

        # client
        settings = get_settings()
        c_manage = MemberManagementAPIClient(
            settings.MEMBER_MANAGEMENT_API_URL,
            settings.MEMBER_MANAGEMENT_API_KEY,
        )

        # get queue
        with db_session() as session:
            queue = session.query(PrivilegeRemoveQueue).filter(
                PrivilegeRemoveQueue.notify_guild_id == interaction.guild.id,
                PrivilegeRemoveQueue.notify_channel_id == interaction.channel.id,
                PrivilegeRemoveQueue.notify_message_id == interaction.message.id,
            ).first()

            if queue is None:
                await interaction.followup.send(
                    "権限剥奪キューが見つかりませんでした", ephemeral=True
                )
                return

            # 削除
            settings = get_settings()
            c_manage = MemberManagementAPIClient(
                settings.MEMBER_MANAGEMENT_API_URL,
                settings.MEMBER_MANAGEMENT_API_KEY,
            )
            await c_manage.change_site_member_privilege(
                site_id=queue.wd_site_id,
                user_id=queue.wd_user_id,
                action="remove_" + queue.permission_level,
            )
            # 削除
            session.delete(queue)
            session.commit()

            # notify_messageを削除
            await interaction.message.edit(
                content="権限を削除しました",
                view=None,
            )
            await interaction.message.delete(delay=5)
