import logging

import discord
import httpx
from discord.commands import slash_command
from discord.ext import commands
from sqlalchemy import select

from config import bot_config
from db.package.models import Guilds, RegisteredRoles
from db.package.session import get_db


class LinkerUtility:
    def __init__(self):
        self.linker_api_url = bot_config.LINKER_API_URL
        self.linker_api_key = bot_config.LINKER_API_KEY

        self.logger = logging.getLogger("LinkerUtility")

        self.logger.info(f"Linker API URL: {self.linker_api_url}")
        self.logger.info(f"Linker API Key: {self.linker_api_key}")

    async def api_call(self, path, data):
        headers = {
            "Authorization": f"Bearer {self.linker_api_key}"
        }

        self.logger.info(f"API Call: {self.linker_api_url}/{path}")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.linker_api_url}/{path}",
                json=data,
                headers=headers
            )

            if response.status_code != 200:
                return None

            return response.json()

    async def start_flow(self, user: discord.User | discord.Member):
        data = {
            "discord": {
                "id": str(user.id),
                "username": user.name,
                "avatar": user.display_avatar.url if user.display_avatar else "https://cdn.discordapp.com/embed/avatars/0.png"
            }
        }

        resp = await self.api_call("v1/start", data)

        if resp is None:
            return None

        return resp["url"]

    async def recheck_flow(self, user: discord.User | discord.Member):
        data = {
            "discord": {
                "id": str(user.id),
                "username": user.name,
                "avatar": user.display_avatar.url if user.display_avatar else "https://cdn.discordapp.com/embed/avatars/0.png"
            }
        }

        resp = await self.api_call("v1/recheck", data)

        if resp is None:
            return None

        return resp

    async def list_accounts(self, users: list[discord.User | discord.Member]):
        data = {
            "discord_ids": [str(user.id) for user in users]
        }

        resp = await self.api_call("v1/list", data)

        if resp is None:
            return None

        return resp


class StartFlowView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.linker_util = LinkerUtility()

    @discord.ui.button(
        label="アカウント連携を開始",
        style=discord.ButtonStyle.primary,
        custom_id="linker:start_flow"
    )
    async def start_flow(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            url = await self.linker_util.start_flow(interaction.user)
            await interaction.followup.send(
                "\n".join([
                    f"## 以下の注意を読んでから、アカウント連携を開始してください",
                    "----",
                    f"1. **以下のURLは、10分間のみ有効です**",
                    f"2. URLをクリックすると、専用Wikidotサイトに遷移します。**右上に表示されているログイン中のユーザが連携したいユーザであることを確認してください。**",
                    f"3. サイトを開いた際に「安全な接続をサポートしていません」と表示された場合は、「サイトへ移動」をクリックしてください。",
                    f"4. **連携作業の途中でブラウザを変更しないでください。**",
                    f"  - **これには、Discordのアプリ内ブラウザからSafari等に切り替える動作なども含まれます。**",
                    "----",
                    "",
                    f"> ### **[アカウント連携を開始する]({url})**"
                ]),
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(
                f"<@{bot_config.OWNER_ID}> エラーが発生しました: {e}"
            )
            raise e


class Linker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(StartFlowView())

    @slash_command(name="send_linker_start_button", description="アカウント連携を開始するボタンを送信します")
    @commands.has_permissions(administrator=True)
    async def send_linker_start_button(self, ctx: discord.commands.context.ApplicationContext):
        await ctx.respond(
            "## Linker アカウント連携\n以下のボタンをクリックして、アカウント連携を開始してください。",
            view=StartFlowView()
        )

    @slash_command(name="register_role", description="付与対象ロールを登録します")
    @commands.has_permissions(administrator=True)
    async def register_role(
            self, ctx: discord.commands.context.ApplicationContext,
            role: discord.Option(discord.Role, "付与対象ロール", required=True),
            is_linked: discord.Option(bool, "連携済みかどうか", required=False, default=None),
            is_jp_member: discord.Option(bool, "JPメンバーかどうか", required=False, default=None)
    ):
        await ctx.interaction.response.defer(ephemeral=True)

        with get_db() as session:
            guild = session.execute(select(Guilds).where(Guilds.guild_id == ctx.guild.id))
            guild = guild.scalar()

            if guild is None:
                guild = Guilds(guild_id=ctx.guild.id)
                session.add(guild)
                session.commit()

            # guild.registered_rolesの中から検索
            registered_role = session.execute(select(RegisteredRoles).where(
                RegisteredRoles.guild_id == guild.id,
                RegisteredRoles.role_id == role.id
            ))
            registered_role = registered_role.scalar()

            if registered_role is None:
                registered_role = RegisteredRoles(
                    role_id=role.id,
                    guild_id=guild.id,
                    is_linked=is_linked,
                    is_jp_member=is_jp_member
                )
                session.add(registered_role)
                session.commit()
                await ctx.interaction.followup.send(f"{role.name} を登録しました。")
            else:
                registered_role.is_linked = is_linked
                registered_role.is_jp_member = is_jp_member
                session.commit()
                await ctx.interaction.followup.send(f"{role.name} を更新しました。")

    @slash_command(name="list_registered_roles", description="登録済みのロールを表示します")
    @commands.has_permissions(administrator=True)
    async def list_registered_roles(self, ctx: discord.commands.context.ApplicationContext):
        await ctx.interaction.response.defer(ephemeral=True)

        with get_db() as session:
            guild = session.execute(select(Guilds).where(Guilds.guild_id == ctx.guild.id))
            guild = guild.scalar()

            if guild is None:
                await ctx.interaction.followup.send("登録されているロールはありません。")
                return

            registered_roles = session.execute(select(RegisteredRoles).where(RegisteredRoles.guild_id == guild.id))
            registered_roles = registered_roles.scalars().all()

            if len(registered_roles) == 0:
                await ctx.interaction.followup.send("登録されているロールはありません。")
                return

            roles = []
            for role in registered_roles:
                roles.append(f"<&{role.role_id}>: {role.is_linked} {role.is_jp_member}")

            await ctx.interaction.followup.send("\n".join(roles))

    @slash_command(name="delete_registered_role", description="登録済みのロールを削除します")
    @commands.has_permissions(administrator=True)
    async def delete_registered_role(
            self, ctx: discord.commands.context.ApplicationContext,
            role: discord.Option(discord.Role, "削除対象ロール", required=True)
    ):
        await ctx.interaction.response.defer(ephemeral=True)

        with get_db() as session:
            guild = session.execute(select(Guilds).where(Guilds.guild_id == ctx.guild.id))
            guild = guild.scalar()

            if guild is None:
                await ctx.interaction.followup.send("登録されているロールはありません。")
                return

            registered_role = session.execute(select(RegisteredRoles).where(
                RegisteredRoles.guild_id == guild.id,
                RegisteredRoles.role_id == role.id
            ))
            registered_role = registered_role.scalar()

            if registered_role is None:
                await ctx.interaction.followup.send("登録されているロールはありません。")
                return

            session.delete(registered_role)
            session.commit()
            await ctx.interaction.followup.send(f"{role.name} を削除しました。")


def setup(bot):
    return bot.add_cog(Linker(bot))
