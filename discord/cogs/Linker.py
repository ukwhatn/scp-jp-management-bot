import logging

import discord
import httpx
from discord.commands import slash_command
from discord.ext import commands, tasks
from sqlalchemy import select

from config import bot_config
from db.package.models import Guilds, RegisteredRoles, NickUpdateTargetGuilds
from db.package.session import get_db


class LinkerUtility:
    def __init__(self):
        self.linker_api_url = bot_config.LINKER_API_URL
        self.linker_api_key = bot_config.LINKER_API_KEY

        self.logger = logging.getLogger("LinkerUtility")

    async def api_call(self, path, data):
        headers = {"Authorization": f"Bearer {self.linker_api_key}"}

        self.logger.info(f"API Call: {self.linker_api_url}/{path}")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.linker_api_url}/{path}", json=data, headers=headers
            )

            if response.status_code != 200:
                return None

            return response.json()

    async def start_flow(self, user: discord.User | discord.Member):
        data = {
            "discord": {
                "id": str(user.id),
                "username": user.name,
                "avatar": user.display_avatar.url
                if user.display_avatar
                else "https://cdn.discordapp.com/embed/avatars/0.png",
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
                "avatar": user.display_avatar.url
                if user.display_avatar
                else "https://cdn.discordapp.com/embed/avatars/0.png",
            }
        }

        resp = await self.api_call("v1/recheck", data)

        if resp is None:
            return None

        return resp

    async def list_accounts(self, users: list[discord.User | discord.Member]):
        data = {"discord_ids": [str(user.id) for user in users]}

        resp = await self.api_call("v1/list", data)

        if resp is None:
            return None

        return resp["result"]


class StartFlowView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.linker_util = LinkerUtility()

    @discord.ui.button(
        label="アカウント連携を開始",
        style=discord.ButtonStyle.primary,
        custom_id="linker:start_flow",
    )
    async def start_flow(
            self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        await interaction.response.defer()
        try:
            url = await self.linker_util.start_flow(interaction.user)
            await interaction.followup.send(
                "\n".join(
                    [
                        "## 以下の注意を読んでから、アカウント連携を開始してください",
                        "----",
                        "1. **以下のURLは、10分間のみ有効です**",
                        "2. URLをクリックすると、専用Wikidotサイトに遷移します。**右上に表示されているログイン中のユーザが連携したいユーザであることを確認してください。**",
                        "3. サイトを開いた際に「安全な接続をサポートしていません」と表示された場合は、「サイトへ移動」をクリックしてください。",
                        "4. **連携作業の途中でブラウザを変更しないでください。**",
                        "  - **これには、Discordのアプリ内ブラウザからSafari等に切り替える動作なども含まれます。**",
                        "----",
                        "",
                        f"> ### **[アカウント連携を開始する]({url})**",
                    ]
                ),
                ephemeral=True,
            )
        except Exception as e:
            await interaction.followup.send(
                f"<@{bot_config.OWNER_ID}> エラーが発生しました: {e}", ephemeral=True
            )
            raise e

    @discord.ui.button(
        label="現在の登録情報を確認",
        style=discord.ButtonStyle.secondary,
        custom_id="linker:check_info",
    )
    async def check_info(
            self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        await interaction.response.defer()

        linker_util = LinkerUtility()
        resp = await linker_util.list_accounts([interaction.user])

        if resp is None or str(interaction.user.id) not in resp:
            await interaction.followup.send(
                "情報が登録されていません。", ephemeral=True
            )
            return

        data = resp[str(interaction.user.id)]
        wikidot = data["wikidot"]

        if len(wikidot) == 0:
            await interaction.followup.send(
                "情報が登録されていません。", ephemeral=True
            )
            return

        wikidot_str = "\n".join(
            [
                f"**[{w['username']}](https://wikidot.com/user:info/{w['unixname']})**"
                f"（{'JPメンバ' if w['is_jp_member'] else '非JPメンバ'}）"
                for w in wikidot
            ]
        )

        await interaction.followup.send(
            f"### あなたが現在連携しているWikidotアカウント:\n>>> {wikidot_str}",
            ephemeral=True,
        )

    @discord.ui.button(
        label="アカウント情報を更新",
        style=discord.ButtonStyle.secondary,
        custom_id="linker:recheck_info",
    )
    async def recheck_info(
            self, button: discord.ui.Button, interaction: discord.Interaction
    ):
        await interaction.response.defer(ephemeral=True)

        linker_util = LinkerUtility()
        resp = await linker_util.recheck_flow(interaction.user)

        if resp is None:
            await interaction.followup.send("エラーが発生しました。", ephemeral=True)
            return

        wikidot = resp["wikidot"]

        if len(wikidot) == 0:
            await interaction.followup.send(
                "情報が登録されていません。", ephemeral=True
            )
            return

        wikidot_str = "\n".join(
            [
                f"**[{w['username']}](https://wikidot.com/user:info/{w['unixname']})**"
                f"（{'JPメンバ' if w['is_jp_member'] else '非JPメンバ'}）"
                for w in wikidot
            ]
        )

        await interaction.followup.send(
            f"### 更新された情報を表示します:\n>>> {wikidot_str}", ephemeral=True
        )


class Linker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = logging.getLogger("Linker")

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(StartFlowView())
        self.update_roles.start()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not self.update_roles.is_running():
            self.logger.warning("update_roles task is not running. Starting task.")
            self.update_roles.start()

    @slash_command(
        name="send_linker_start_button",
        description="アカウント連携を開始するボタンを送信します",
    )
    @commands.has_permissions(administrator=True)
    async def send_linker_start_button(
            self, ctx: discord.commands.context.ApplicationContext
    ):
        await ctx.respond(
            "## Linker アカウント連携\n以下のボタンをクリックして、アカウント連携を開始してください。",
            view=StartFlowView(),
        )

    @slash_command(name="register_role", description="付与対象ロールを登録します")
    @commands.has_permissions(administrator=True)
    async def register_role(
            self,
            ctx: discord.commands.context.ApplicationContext,
            role: discord.Option(discord.Role, "付与対象ロール", required=True),
            is_linked: discord.Option(
                bool, "連携済みかどうか", required=False, default=None
            ),
            is_jp_member: discord.Option(
                bool, "JPメンバーかどうか", required=False, default=None
            ),
    ):
        await ctx.interaction.response.defer(ephemeral=True)

        # is_linkedとis_jp_memberについて、以下に当てはまらないものを弾く
        # is_linkedがNone / is_jp_memberがNone = 全員
        # is_linkedがTrue / is_jp_memberがTrue = 連携済みJPメンバー
        # is_linkedがTrue / is_jp_memberがFalse = 連携済み非JPメンバー
        # is_linkedがTrue / is_jp_memberがNone = 連携済み
        # is_linkedがFalse = 未連携

        if (is_linked, is_jp_member) not in [
            (None, None),
            (True, True),
            (True, False),
            (True, None),
            (False, None),
        ]:
            await ctx.interaction.followup.send(
                "is_linkedとis_jp_memberの組み合わせが不正です。"
            )
            return

        with get_db() as session:
            guild = session.execute(
                select(Guilds).where(Guilds.guild_id == ctx.guild.id)
            )
            guild = guild.scalar()

            if guild is None:
                guild = Guilds(guild_id=ctx.guild.id)
                session.add(guild)
                session.commit()

            # guild.registered_rolesの中から検索
            registered_role = session.execute(
                select(RegisteredRoles).where(
                    RegisteredRoles.guild_id == guild.id,
                    RegisteredRoles.role_id == role.id,
                )
            )
            registered_role = registered_role.scalar()

            if registered_role is None:
                registered_role = RegisteredRoles(
                    role_id=role.id,
                    guild_id=guild.id,
                    is_linked=is_linked,
                    is_jp_member=is_jp_member,
                )
                session.add(registered_role)
                session.commit()
                await ctx.interaction.followup.send(f"{role.name} を登録しました。")
            else:
                registered_role.is_linked = is_linked
                registered_role.is_jp_member = is_jp_member
                session.commit()
                await ctx.interaction.followup.send(f"{role.name} を更新しました。")

    @slash_command(
        name="list_registered_roles", description="登録済みのロールを表示します"
    )
    @commands.has_permissions(administrator=True)
    async def list_registered_roles(
            self, ctx: discord.commands.context.ApplicationContext
    ):
        await ctx.interaction.response.defer(ephemeral=True)

        with get_db() as session:
            guild = session.execute(
                select(Guilds).where(Guilds.guild_id == ctx.guild.id)
            )
            guild = guild.scalar()

            if guild is None:
                await ctx.interaction.followup.send(
                    "登録されているロールはありません。"
                )
                return

            registered_roles = session.execute(
                select(RegisteredRoles).where(RegisteredRoles.guild_id == guild.id)
            )
            registered_roles = registered_roles.scalars().all()

            if len(registered_roles) == 0:
                await ctx.interaction.followup.send(
                    "登録されているロールはありません。"
                )
                return

            roles = []
            for role in registered_roles:
                roles.append(
                    f"<@&{role.role_id}>: {role.is_linked} {role.is_jp_member}"
                )

            await ctx.interaction.followup.send("\n".join(roles))

    @slash_command(
        name="delete_registered_role", description="登録済みのロールを削除します"
    )
    @commands.has_permissions(administrator=True)
    async def delete_registered_role(
            self,
            ctx: discord.commands.context.ApplicationContext,
            role: discord.Option(discord.Role, "削除対象ロール", required=True),
    ):
        await ctx.interaction.response.defer(ephemeral=True)

        with get_db() as session:
            guild = session.execute(
                select(Guilds).where(Guilds.guild_id == ctx.guild.id)
            )
            guild = guild.scalar()

            if guild is None:
                await ctx.interaction.followup.send(
                    "登録されているロールはありません。"
                )
                return

            registered_role = session.execute(
                select(RegisteredRoles).where(
                    RegisteredRoles.guild_id == guild.id,
                    RegisteredRoles.role_id == role.id,
                )
            )
            registered_role = registered_role.scalar()

            if registered_role is None:
                await ctx.interaction.followup.send(
                    "登録されているロールはありません。"
                )
                return

            session.delete(registered_role)
            session.commit()
            await ctx.interaction.followup.send(f"{role.name} を削除しました。")

    async def update_roles_in_guild(self, guild: discord.Guild, update_nick: bool = False):
        # guildに紐づいたロールを取得
        with get_db() as session:
            guild_db = session.execute(
                select(Guilds).where(Guilds.guild_id == guild.id)
            )
            guild_db = guild_db.scalar()

            if guild_db is None:
                return

            registered_roles = session.execute(
                select(RegisteredRoles).where(RegisteredRoles.guild_id == guild_db.id)
            )
            registered_roles = registered_roles.scalars().all()

            is_nick_update_target = update_nick and session.execute(
                select(NickUpdateTargetGuilds).where(NickUpdateTargetGuilds.guild_id == guild.id)
            ).scalar() is not None

        # guild内のメンバーのIDを取得
        members = await guild.fetch_members().flatten()
        member_ids = [member.id for member in members if not member.bot]

        # linker APIでリストを取得
        linker_util = LinkerUtility()
        resp = await linker_util.list_accounts(
            [guild.get_member(member_id) for member_id in member_ids]
        )

        if resp is None:
            return

        # 仕分け
        linker_linked_members = []
        linker_linked_jp_members = []
        linker_linked_non_jp_members = []

        nick_update_target = []

        for data in resp.values():
            # discord.idを取得
            _d_id = int(data["discord"]["id"])

            # wikidotアカウントが存在しない場合
            if len(data["wikidot"]) == 0:
                continue

            # JPメンバ判定
            is_jp_member = False
            for w in data["wikidot"]:
                if w["is_jp_member"]:
                    is_jp_member = True
                    break

            # idを配列に投入
            linker_linked_members.append(_d_id)
            if is_jp_member:
                linker_linked_jp_members.append(_d_id)
            else:
                linker_linked_non_jp_members.append(_d_id)

            if is_nick_update_target:
                # discord idとwikidot user nameのペアを作成
                # 複数のwikidotアカウントが連携されている場合は、すべてのアカウントを"/"で連結
                nick_update_target.append((_d_id, str("/".join([w["username"] for w in data["wikidot"]]))))

        # linker_linked_membersに含まれないメンバーをunknownに追加
        linker_unknown_members = [
            member_id
            for member_id in member_ids
            if member_id not in linker_linked_members
        ]

        member_dict = {member.id: member for member in members}

        # ロールの付与
        for role in registered_roles:
            role_obj = guild.get_role(role.role_id)

            self.logger.info(f"Role: {role.role_id} in {guild.name}")

            if role_obj is None:
                await bot_config.NOTIFY_TO_OWNER(
                    self.bot, f"Role not found: {role.role_id} in {guild.name}"
                )
                continue

            target_user_ids = []
            # is_linkedがNone / is_jp_memberがNone = 全員
            if role.is_linked is None and role.is_jp_member is None:
                target_user_ids = member_ids

            # is_linkedがTrue / is_jp_memberがTrue = 連携済みJPメンバー
            elif role.is_linked is True and role.is_jp_member is True:
                target_user_ids = linker_linked_jp_members

            # is_linkedがTrue / is_jp_memberがFalse = 連携済み非JPメンバー
            elif role.is_linked is True and role.is_jp_member is False:
                target_user_ids = linker_linked_non_jp_members

            # is_linkedがTrue / is_jp_memberがNone = 連携済み
            elif role.is_linked is True and role.is_jp_member is None:
                target_user_ids = linker_linked_members

            # is_linkedがFalse = 未連携
            elif role.is_linked is False:
                target_user_ids = linker_unknown_members

            for member_id in target_user_ids:
                member = member_dict.get(member_id)
                if member is None:
                    continue

                if role_obj not in member.roles:
                    await member.add_roles(role_obj)

            # 付与対象から外れたメンバーについてはロールを削除
            for member in role_obj.members:
                if member.id not in target_user_ids:
                    await member.remove_roles(role_obj)

        # ニックネームの更新
        if is_nick_update_target:
            for member_id, nick in nick_update_target:
                member = member_dict.get(member_id)
                if member is None:
                    continue

                # nickが30文字以上の場合は27で切って"..."を付ける
                if len(nick) > 30:
                    nick = nick[:27] + "..."

                if member.nick != nick:
                    await member.edit(nick=nick)

    @tasks.loop(minutes=15)
    async def update_roles(self):
        for guild in self.bot.guilds:
            self.logger.info(f"Updating roles in {guild.name}")
            await self.update_roles_in_guild(guild, update_nick=True)

    @update_roles.before_loop
    async def before_update_roles(self):
        await self.bot.wait_until_ready()

    @slash_command(name="force_update", description="ロールの強制更新を行います")
    @commands.has_permissions(administrator=True)
    async def force_update(
            self, ctx: discord.commands.context.ApplicationContext,
            nick: discord.Option(bool, "ニックネーム更新の要否", default=False)
    ):
        await ctx.interaction.response.defer(ephemeral=True)
        await self.update_roles_in_guild(ctx.guild, update_nick=nick)
        await ctx.interaction.followup.send("ロールの強制更新を行いました。")

    @slash_command(
        name="check_info_from_discord",
        description="DiscordユーザからLinkerの情報を取得します",
    )
    @commands.has_permissions(administrator=True)
    async def check_info_from_discord(
            self,
            ctx: discord.commands.context.ApplicationContext,
            user: discord.Option(discord.User, "ユーザ", required=True),
    ):
        await ctx.interaction.response.defer(ephemeral=True)

        linker_util = LinkerUtility()
        resp = await linker_util.list_accounts([user])

        if resp is None or str(user.id) not in resp:
            await ctx.interaction.followup.send("情報が登録されていません。")
            return

        data = resp[str(user.id)]
        wikidot = data["wikidot"]

        if len(wikidot) == 0:
            await ctx.interaction.followup.send("情報が登録されていません。")
            return

        wikidot_str = "\n".join(
            [
                f"**{w['username']}** ({w['unixname']} / {w['id']} / {'JPメンバ' if w['is_jp_member'] else '非JPメンバ'})"
                for w in wikidot
            ]
        )

        await ctx.interaction.followup.send(
            f"### **{user.name}** の情報:\n>>> {wikidot_str}"
        )

    @slash_command(
        name="recheck_user", description="Linker APIのアカウント情報を更新します"
    )
    @commands.has_permissions(administrator=True)
    async def recheck_user(
            self,
            ctx: discord.commands.context.ApplicationContext,
            user: discord.Option(discord.User, "ユーザ", required=True),
    ):
        await ctx.interaction.response.defer(ephemeral=True)

        linker_util = LinkerUtility()
        resp = await linker_util.recheck_flow(user)

        if resp is None:
            await ctx.interaction.followup.send("エラーが発生しました。")
            return

        wikidot = resp["wikidot"]

        if len(wikidot) == 0:
            await ctx.interaction.followup.send("情報が登録されていません。")
            return

        wikidot_str = "\n".join(
            [
                f"**{w['username']}** ({w['unixname']} / {w['id']} / {'JPメンバ' if w['is_jp_member'] else '非JPメンバ'})"
                for w in wikidot
            ]
        )

        await ctx.interaction.followup.send(
            f"### **{user.name}** の情報:\n>>> {wikidot_str}"
        )

    @slash_command(
        name="toggle_auto_nick", description="ニックネーム自動更新対象を登録します"
    )
    @commands.has_permissions(administrator=True)
    async def toggle_auto_nick(
            self,
            ctx: discord.commands.context.ApplicationContext,
    ):
        await ctx.interaction.response.defer(ephemeral=True)

        with get_db() as session:
            guild = session.execute(
                select(NickUpdateTargetGuilds).where(NickUpdateTargetGuilds.guild_id == ctx.guild.id)
            )
            guild = guild.scalar()

            if guild is None:
                guild = NickUpdateTargetGuilds(guild_id=ctx.guild.id)
                session.add(guild)
                session.commit()
                await ctx.interaction.followup.send("ニックネーム自動更新対象を登録しました。")
            else:
                session.delete(guild)
                session.commit()
                await ctx.interaction.followup.send("ニックネーム自動更新対象を解除しました。")


def setup(bot):
    return bot.add_cog(Linker(bot))
