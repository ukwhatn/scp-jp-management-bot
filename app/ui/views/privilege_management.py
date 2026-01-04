import datetime
from typing import Optional

import discord
from httpx import HTTPStatusError

from core import get_settings
from db import db_session
from db.models import PrivilegeRemoveQueue
from utils.panopticon_client import PanopticonClient, Site


def _get_panopticon_client() -> Optional[PanopticonClient]:
    settings = get_settings()
    if settings.PANOPTICON_API_URL and settings.PANOPTICON_API_KEY:
        return PanopticonClient(
            settings.PANOPTICON_API_URL,
            settings.PANOPTICON_API_KEY,
        )
    return None


class GetPrivilegeButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Wiki上での権限を取得する",
        custom_id="get_privilege_button",
        style=discord.ButtonStyle.danger,
        emoji="",
    )
    async def get_privilege_button(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        # defer
        await interaction.response.defer()

        # client
        panopticon = _get_panopticon_client()
        if panopticon is None:
            return await interaction.followup.send(
                "APIが設定されていません", ephemeral=True
            )

        try:
            sites = await panopticon.get_sites()
        except Exception as e:
            return await interaction.followup.send(
                f"サイト一覧の取得に失敗しました: {e}", ephemeral=True
            )

        await interaction.followup.send(
            "権限を取得するサイトを選択してください",
            ephemeral=True,
            view=GetPrivilegeSiteSelector(sites),
        )


class GetPrivilegeSiteSelector(discord.ui.View):
    def __init__(self, sites: list[Site]):
        super().__init__(timeout=None)
        self.sites = {site.unixName: site for site in sites}

        options = [
            discord.SelectOption(
                label=site.name.upper(),
                value=site.unixName,
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
                content="処理中です.....", view=None, message_id=interaction.message.id
            )

            # get selected site
            selected_site_unix_name = self.select.values[0]

            # client
            panopticon = _get_panopticon_client()
            if panopticon is None:
                return await interaction.followup.send(
                    "APIが設定されていません", ephemeral=True
                )

            # Panopticonでリンクされたアカウントを取得
            dc_user = interaction.user
            try:
                bulk_result = await panopticon.link_bulk([str(dc_user.id)])
            except Exception as e:
                return await interaction.followup.send(
                    f"連携情報の取得に失敗しました: {e}", ephemeral=True
                )

            if (
                not bulk_result
                or not bulk_result[0].linked
                or bulk_result[0].account is None
            ):
                await interaction.followup.send(
                    f"{interaction.user.mention}\nあなたのアカウントはWikiにリンクされていません",
                )
                return

            wikidot_user_id = bulk_result[0].account.user.id
            wikidot_username = bulk_result[0].account.user.name

            # ユーザーのRBAC権限を確認（admin:{site}またはmoderate:{site}を持っているか）
            try:
                user_info = await panopticon.get_user(wikidot_user_id)
            except Exception as e:
                return await interaction.followup.send(
                    f"ユーザー情報の取得に失敗しました: {e}", ephemeral=True
                )

            has_admin = panopticon.has_admin_permission(
                user_info.permissions, selected_site_unix_name
            )
            has_moderate = panopticon.has_moderate_permission(
                user_info.permissions, selected_site_unix_name
            )

            if not has_moderate:
                await interaction.followup.send(
                    f"{interaction.user.mention}\n対象サイトの権限を有するアカウントが見つかりませんでした"
                )
                return

            # 権限昇格を実施
            # panopticonはgrant/revokeのみで、RBACロールから自動判定
            permission_level = "admin" if has_admin else "moderator"
            try:
                await panopticon.change_privilege(
                    site_unix_name=selected_site_unix_name,
                    user_id=wikidot_user_id,
                    action="grant",
                )
                notify_msg_partial = await interaction.followup.send(
                    f"### Wikidotアカウントの権限を昇格しました\n"
                    f"> ユーザ: {interaction.user.name} ({wikidot_username})\n"
                    f"> サイト: {self.sites[selected_site_unix_name].name}\n"
                    f"> 権限: {permission_level}",
                    view=PrivilegeRemoveButton(),
                )
            except HTTPStatusError as e:
                await interaction.followup.send(
                    f"{interaction.user.mention} 権限の昇格に失敗しました\n"
                    f"> エラーコード: {e.response.status_code}\n"
                    f"> エラーメッセージ: {e.response.text}",
                )
                return
            except Exception as e:
                await interaction.followup.send(
                    f"{interaction.user.mention} 権限の昇格に失敗しました: {e}",
                )
                return

            with db_session() as session:
                # 権限剥奪キューに追加
                # expired_atは1時間後
                notify_msg = await interaction.channel.fetch_message(
                    notify_msg_partial.id
                )
                privilege_remove_queue = PrivilegeRemoveQueue(
                    dc_user_id=interaction.user.id,
                    wd_user_id=wikidot_user_id,
                    wd_site_unix_name=selected_site_unix_name,
                    notify_guild_id=notify_msg.guild.id,
                    notify_channel_id=notify_msg.channel.id,
                    notify_message_id=notify_msg.id,
                    permission_level=permission_level,
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
        emoji="",
    )
    async def remove_privilege_button(
        self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        # defer
        await interaction.response.defer()

        # client
        panopticon = _get_panopticon_client()
        if panopticon is None:
            return await interaction.followup.send(
                "APIが設定されていません", ephemeral=True
            )

        # get queue
        with db_session() as session:
            queue = (
                session.query(PrivilegeRemoveQueue)
                .filter(
                    PrivilegeRemoveQueue.notify_guild_id == interaction.guild.id,
                    PrivilegeRemoveQueue.notify_channel_id == interaction.channel.id,
                    PrivilegeRemoveQueue.notify_message_id == interaction.message.id,
                )
                .first()
            )

            if queue is None:
                await interaction.followup.send(
                    "権限剥奪キューが見つかりませんでした", ephemeral=True
                )
                return

            # 権限剥奪
            try:
                await panopticon.change_privilege(
                    site_unix_name=queue.wd_site_unix_name,
                    user_id=queue.wd_user_id,
                    action="revoke",
                )
            except Exception as e:
                await interaction.followup.send(
                    f"権限の削除に失敗しました: {e}", ephemeral=True
                )
                return

            # キューから削除
            session.delete(queue)
            session.commit()

            # notify_messageを削除
            await interaction.message.edit(
                content="権限を削除しました",
                view=None,
            )
            await interaction.message.delete(delay=5)
