import logging
import re
from collections import defaultdict
from typing import List

import discord
from discord.ext import commands
from sqlalchemy.orm import joinedload

from core import get_settings
from db.connection import db_session
from db.models import RoleGroup, RoleGroupRole


class RoleGroupCog(commands.Cog):
    """ロールグループ管理コマンド群"""

    def __init__(self, bot: discord.Bot):
        self.bot = bot
        self.settings = get_settings()
        self.logger = logging.getLogger("discord")

    # ==============================
    # ユーティリティ関数
    # ==============================

    def parse_mentions(
        self, mention_string: str, mention_type: str = "role"
    ) -> List[int]:
        """メンション文字列からIDを抽出"""
        if mention_type == "role":
            pattern = r"<@&(\d+)>"
        elif mention_type == "user":
            pattern = r"<@!?(\d+)>"
        else:
            raise ValueError(f"Invalid mention_type: {mention_type}")

        matches = re.findall(pattern, mention_string)
        return [int(match) for match in matches]

    async def get_role_group_autocomplete(
        self, ctx: discord.AutocompleteContext
    ) -> List[str]:
        """ロールグループ名のautocomplete候補を取得"""
        with db_session() as db:
            groups = db.query(RoleGroup).all()
            group_names = [group.name for group in groups]

            # 入力値でフィルタリング
            if ctx.value:
                group_names = [
                    name for name in group_names if ctx.value.lower() in name.lower()
                ]

            return group_names[:25]  # Discord制限

    def check_manage_roles_permission(self, ctx: discord.ApplicationContext) -> bool:
        """ユーザーがmanage_roles権限を持っているかチェック"""
        if not isinstance(ctx.author, discord.Member):
            return False
        return ctx.author.guild_permissions.manage_roles

    # ==============================
    # コマンドグループ
    # ==============================

    group_rolegroup = discord.SlashCommandGroup(
        "rolegroup", "ロールグループを管理するコマンド群"
    )

    # ==============================
    # ロールグループ作成
    # ==============================

    @group_rolegroup.command(
        name="create", description="新しいロールグループを作成します"
    )
    async def create_group(
        self,
        ctx: discord.ApplicationContext,
        name: discord.Option(str, "グループ名", max_length=100),
        description: discord.Option(
            str, "グループの説明", max_length=500, required=False
        ),
    ):
        """ロールグループを作成"""
        if not self.check_manage_roles_permission(ctx):
            await ctx.respond(
                "❌ このコマンドを使用するには `ロールの管理` 権限が必要です。",
                ephemeral=True,
            )
            return

        try:
            with db_session() as db:
                # 同名のグループが存在するかチェック
                existing_group = (
                    db.query(RoleGroup).filter(RoleGroup.name == name).first()
                )
                if existing_group:
                    await ctx.respond(
                        f"❌ グループ名 `{name}` は既に存在します。", ephemeral=True
                    )
                    return

                # 新しいグループを作成
                new_group = RoleGroup(
                    name=name, description=description, created_by_user_id=ctx.author.id
                )
                db.add(new_group)
                db.commit()

                embed = discord.Embed(
                    title="✅ ロールグループが作成されました",
                    description=f"グループ名: `{name}`",
                    color=discord.Color.green(),
                )
                if description:
                    embed.add_field(name="説明", value=description, inline=False)

                await ctx.respond(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error creating role group: {e}")
            await ctx.respond(
                "❌ グループの作成中にエラーが発生しました。", ephemeral=True
            )

    # ==============================
    # ロールグループ削除
    # ==============================

    @group_rolegroup.command(name="delete", description="ロールグループを削除します")
    async def delete_group(
        self,
        ctx: discord.ApplicationContext,
        group_name: discord.Option(
            str, "削除するグループ名", autocomplete=get_role_group_autocomplete
        ),
    ):
        """ロールグループを削除"""
        if not self.check_manage_roles_permission(ctx):
            await ctx.respond(
                "❌ このコマンドを使用するには `ロールの管理` 権限が必要です。",
                ephemeral=True,
            )
            return

        try:
            with db_session() as db:
                group = db.query(RoleGroup).filter(RoleGroup.name == group_name).first()
                if not group:
                    await ctx.respond(
                        f"❌ グループ `{group_name}` が見つかりません。", ephemeral=True
                    )
                    return

                # 削除（カスケードでRoleGroupRoleも削除される）
                db.delete(group)
                db.commit()

                embed = discord.Embed(
                    title="✅ ロールグループが削除されました",
                    description=f"グループ名: `{group_name}`",
                    color=discord.Color.red(),
                )
                await ctx.respond(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error deleting role group: {e}")
            await ctx.respond(
                "❌ グループの削除中にエラーが発生しました。", ephemeral=True
            )

    # ==============================
    # ロール追加
    # ==============================

    @group_rolegroup.command(
        name="add_role", description="ロールグループにロールを追加します"
    )
    async def add_role(
        self,
        ctx: discord.ApplicationContext,
        group_name: discord.Option(
            str, "グループ名", autocomplete=get_role_group_autocomplete
        ),
        role_mentions: discord.Option(str, "追加するロール（メンション形式）"),
    ):
        """ロールグループにロールを追加"""
        if not self.check_manage_roles_permission(ctx):
            await ctx.respond(
                "❌ このコマンドを使用するには `ロールの管理` 権限が必要です。",
                ephemeral=True,
            )
            return

        try:
            # ロールIDを抽出
            role_ids = self.parse_mentions(role_mentions, "role")
            if not role_ids:
                await ctx.respond(
                    "❌ 有効なロールメンションが見つかりません。", ephemeral=True
                )
                return

            with db_session() as db:
                group = db.query(RoleGroup).filter(RoleGroup.name == group_name).first()
                if not group:
                    await ctx.respond(
                        f"❌ グループ `{group_name}` が見つかりません。", ephemeral=True
                    )
                    return

                added_roles = []
                skipped_roles = []

                for role_id in role_ids:
                    # ロールが存在するかチェック
                    role = ctx.guild.get_role(role_id)
                    if not role:
                        skipped_roles.append(f"<@&{role_id}> (存在しないロール)")
                        continue

                    # Botがそのロールを管理できるかチェック
                    if role >= ctx.guild.me.top_role:
                        skipped_roles.append(f"{role.mention} (Botより高位のロール)")
                        continue

                    # @everyoneロールかチェック
                    if role.id == ctx.guild.id:
                        skipped_roles.append(f"{role.mention} (@everyoneロール)")
                        continue

                    # 既にグループに含まれているかチェック
                    existing = (
                        db.query(RoleGroupRole)
                        .filter(
                            RoleGroupRole.role_group_id == group.id,
                            RoleGroupRole.guild_id == ctx.guild.id,
                            RoleGroupRole.role_id == role_id,
                        )
                        .first()
                    )

                    if existing:
                        skipped_roles.append(f"{role.mention} (既に追加済み)")
                        continue

                    # ロールを追加
                    role_group_role = RoleGroupRole(
                        role_group_id=group.id, guild_id=ctx.guild.id, role_id=role_id
                    )
                    db.add(role_group_role)
                    added_roles.append(role.mention)

                db.commit()

                # 結果を表示
                embed = discord.Embed(
                    title=f"ロールグループ `{group_name}` にロールを追加",
                    color=discord.Color.blue(),
                )

                if added_roles:
                    embed.add_field(
                        name="✅ 追加されたロール",
                        value="\n".join(added_roles),
                        inline=False,
                    )

                if skipped_roles:
                    embed.add_field(
                        name="⚠️ スキップされたロール",
                        value="\n".join(skipped_roles),
                        inline=False,
                    )

                if not added_roles and not skipped_roles:
                    embed.description = "追加されたロールはありません。"

                await ctx.respond(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error adding roles to group: {e}")
            await ctx.respond(
                "❌ ロールの追加中にエラーが発生しました。", ephemeral=True
            )

    # ==============================
    # ロール削除
    # ==============================

    @group_rolegroup.command(
        name="remove_role", description="ロールグループからロールを削除します"
    )
    async def remove_role(
        self,
        ctx: discord.ApplicationContext,
        group_name: discord.Option(
            str, "グループ名", autocomplete=get_role_group_autocomplete
        ),
        role_mentions: discord.Option(str, "削除するロール（メンション形式）"),
    ):
        """ロールグループからロールを削除"""
        if not self.check_manage_roles_permission(ctx):
            await ctx.respond(
                "❌ このコマンドを使用するには `ロールの管理` 権限が必要です。",
                ephemeral=True,
            )
            return

        try:
            # ロールIDを抽出
            role_ids = self.parse_mentions(role_mentions, "role")
            if not role_ids:
                await ctx.respond(
                    "❌ 有効なロールメンションが見つかりません。", ephemeral=True
                )
                return

            with db_session() as db:
                group = db.query(RoleGroup).filter(RoleGroup.name == group_name).first()
                if not group:
                    await ctx.respond(
                        f"❌ グループ `{group_name}` が見つかりません。", ephemeral=True
                    )
                    return

                removed_roles = []
                not_found_roles = []

                for role_id in role_ids:
                    role_group_role = (
                        db.query(RoleGroupRole)
                        .filter(
                            RoleGroupRole.role_group_id == group.id,
                            RoleGroupRole.guild_id == ctx.guild.id,
                            RoleGroupRole.role_id == role_id,
                        )
                        .first()
                    )

                    if role_group_role:
                        db.delete(role_group_role)
                        role = ctx.guild.get_role(role_id)
                        role_mention = role.mention if role else f"<@&{role_id}>"
                        removed_roles.append(role_mention)
                    else:
                        role = ctx.guild.get_role(role_id)
                        role_mention = role.mention if role else f"<@&{role_id}>"
                        not_found_roles.append(role_mention)

                db.commit()

                # 結果を表示
                embed = discord.Embed(
                    title=f"ロールグループ `{group_name}` からロールを削除",
                    color=discord.Color.orange(),
                )

                if removed_roles:
                    embed.add_field(
                        name="✅ 削除されたロール",
                        value="\n".join(removed_roles),
                        inline=False,
                    )

                if not_found_roles:
                    embed.add_field(
                        name="⚠️ グループに含まれていなかったロール",
                        value="\n".join(not_found_roles),
                        inline=False,
                    )

                await ctx.respond(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error removing roles from group: {e}")
            await ctx.respond(
                "❌ ロールの削除中にエラーが発生しました。", ephemeral=True
            )

    # ==============================
    # ロールグループ一覧
    # ==============================

    @group_rolegroup.command(
        name="list", description="ロールグループの一覧を表示します"
    )
    async def list_groups(self, ctx: discord.ApplicationContext):
        """ロールグループの一覧を表示"""
        try:
            with db_session() as db:
                groups = db.query(RoleGroup).options(joinedload(RoleGroup.roles)).all()

                if not groups:
                    await ctx.respond(
                        "📋 登録されているロールグループはありません。", ephemeral=True
                    )
                    return

                embeds = []
                for group in groups:
                    embed = discord.Embed(
                        title=f"📁 {group.name}", color=discord.Color.blue()
                    )

                    if group.description:
                        embed.add_field(
                            name="説明", value=group.description, inline=False
                        )

                    # グループに含まれるロールを表示
                    if group.roles:
                        role_info = []
                        for role_group_role in group.roles:
                            guild = self.bot.get_guild(role_group_role.guild_id)
                            if guild:
                                role = guild.get_role(role_group_role.role_id)
                                if role:
                                    role_info.append(f"{role.name} ({guild.name})")
                                else:
                                    role_info.append(
                                        f"ID:{role_group_role.role_id} ({guild.name}) [削除済み]"
                                    )
                            else:
                                role_info.append(
                                    f"ID:{role_group_role.role_id} [ギルド不明]"
                                )

                        if role_info:
                            role_display = "\n".join(role_info[:10])
                            if len(role_info) > 10:
                                role_display += "\n..."
                            embed.add_field(
                                name="含まれるロール", value=role_display, inline=False
                            )
                    else:
                        embed.add_field(
                            name="含まれるロール", value="なし", inline=False
                        )

                    # 作成者情報
                    creator = self.bot.get_user(group.created_by_user_id)
                    embed.set_footer(
                        text=f"作成者: {creator.display_name if creator else f'ID:{group.created_by_user_id}'} | 作成日: {group.created_at.strftime('%Y/%m/%d')}"
                    )

                    embeds.append(embed)

                # 複数のembedがある場合は分割して送信
                for i in range(0, len(embeds), 10):  # Discord制限で10個まで
                    await ctx.respond(embeds=embeds[i : i + 10], ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error listing role groups: {e}")
            await ctx.respond(
                "❌ グループ一覧の取得中にエラーが発生しました。", ephemeral=True
            )

    # ==============================
    # ロール適用（全ギルド対応）
    # ==============================

    @group_rolegroup.command(
        name="apply", description="ユーザーにロールグループのロールを適用します"
    )
    async def apply_roles(
        self,
        ctx: discord.ApplicationContext,
        group_name: discord.Option(
            str, "グループ名", autocomplete=get_role_group_autocomplete
        ),
        user_mentions: discord.Option(str, "対象ユーザー（メンション形式）"),
    ):
        """ユーザーにロールグループのロールを適用（全ギルド対応）"""
        if not self.check_manage_roles_permission(ctx):
            await ctx.respond(
                "❌ このコマンドを使用するには `ロールの管理` 権限が必要です。",
                ephemeral=True,
            )
            return

        try:
            # ユーザーIDを抽出
            user_ids = self.parse_mentions(user_mentions, "user")
            if not user_ids:
                await ctx.respond(
                    "❌ 有効なユーザーメンションが見つかりません。", ephemeral=True
                )
                return

            with db_session() as db:
                group = (
                    db.query(RoleGroup)
                    .options(joinedload(RoleGroup.roles))
                    .filter(RoleGroup.name == group_name)
                    .first()
                )

                if not group:
                    await ctx.respond(
                        f"❌ グループ `{group_name}` が見つかりません。", ephemeral=True
                    )
                    return

                if not group.roles:
                    await ctx.respond(
                        f"❌ グループ `{group_name}` にはロールが含まれていません。",
                        ephemeral=True,
                    )
                    return

                # ギルドごとにロールをまとめる
                roles_by_guild = defaultdict(list)
                for role_group_role in group.roles:
                    roles_by_guild[role_group_role.guild_id].append(role_group_role)

                results = []

                for user_id in user_ids:
                    user_results = []

                    # 各ギルドでロールを処理
                    for guild_id, guild_roles in roles_by_guild.items():
                        guild = self.bot.get_guild(guild_id)
                        if not guild:
                            user_results.append(f"ギルド不明(ID:{guild_id}): スキップ")
                            continue

                        member = guild.get_member(user_id)
                        if not member:
                            user_results.append(f"{guild.name}: メンバーではありません")
                            continue

                        added_roles = []
                        skipped_roles = []

                        for role_group_role in guild_roles:
                            role = guild.get_role(role_group_role.role_id)
                            if not role:
                                skipped_roles.append(
                                    f"ID:{role_group_role.role_id}(削除済み)"
                                )
                                continue

                            # Botがそのロールを管理できるかチェック
                            if role >= guild.me.top_role:
                                skipped_roles.append(f"{role.name}(Botより高位)")
                                continue

                            # ユーザーが既にロールを持っているかチェック
                            if role in member.roles:
                                skipped_roles.append(f"{role.name}(既に所持)")
                                continue

                            try:
                                await member.add_roles(
                                    role, reason=f"ロールグループ '{group_name}' を適用"
                                )
                                added_roles.append(role.name)
                            except discord.Forbidden:
                                skipped_roles.append(f"{role.name}(権限不足)")
                            except discord.HTTPException:
                                skipped_roles.append(f"{role.name}(エラー)")

                        # このギルドの結果をまとめる
                        guild_result_parts = [f"**{guild.name}**"]
                        if added_roles:
                            guild_result_parts.append(f"✅ {', '.join(added_roles)}")
                        if skipped_roles:
                            guild_result_parts.append(f"⚠️ {', '.join(skipped_roles)}")

                        if len(guild_result_parts) > 1:
                            user_results.append(" - ".join(guild_result_parts))

                    # ユーザー全体の結果をまとめる
                    if user_results:
                        results.append(f"<@{user_id}>:\n  " + "\n  ".join(user_results))
                    else:
                        results.append(f"<@{user_id}>: 操作対象なし")

                # 結果を表示
                description = "\n\n".join(results[:10])
                if len(results) > 10:
                    description += "\n\n..."
                embed = discord.Embed(
                    title=f"ロールグループ `{group_name}` を適用",
                    description=description,
                    color=discord.Color.green(),
                )

                await ctx.respond(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error applying role group: {e}")
            await ctx.respond(
                "❌ ロールの適用中にエラーが発生しました。", ephemeral=True
            )

    # ==============================
    # ロール削除（全ギルド対応）
    # ==============================

    @group_rolegroup.command(
        name="remove", description="ユーザーからロールグループのロールを削除します"
    )
    async def remove_roles(
        self,
        ctx: discord.ApplicationContext,
        group_name: discord.Option(
            str, "グループ名", autocomplete=get_role_group_autocomplete
        ),
        user_mentions: discord.Option(str, "対象ユーザー（メンション形式）"),
    ):
        """ユーザーからロールグループのロールを削除（全ギルド対応）"""
        if not self.check_manage_roles_permission(ctx):
            await ctx.respond(
                "❌ このコマンドを使用するには `ロールの管理` 権限が必要です。",
                ephemeral=True,
            )
            return

        try:
            # ユーザーIDを抽出
            user_ids = self.parse_mentions(user_mentions, "user")
            if not user_ids:
                await ctx.respond(
                    "❌ 有効なユーザーメンションが見つかりません。", ephemeral=True
                )
                return

            with db_session() as db:
                group = (
                    db.query(RoleGroup)
                    .options(joinedload(RoleGroup.roles))
                    .filter(RoleGroup.name == group_name)
                    .first()
                )

                if not group:
                    await ctx.respond(
                        f"❌ グループ `{group_name}` が見つかりません。", ephemeral=True
                    )
                    return

                if not group.roles:
                    await ctx.respond(
                        f"❌ グループ `{group_name}` にはロールが含まれていません。",
                        ephemeral=True,
                    )
                    return

                # ギルドごとにロールをまとめる
                roles_by_guild = defaultdict(list)
                for role_group_role in group.roles:
                    roles_by_guild[role_group_role.guild_id].append(role_group_role)

                results = []

                for user_id in user_ids:
                    user_results = []

                    # 各ギルドでロールを処理
                    for guild_id, guild_roles in roles_by_guild.items():
                        guild = self.bot.get_guild(guild_id)
                        if not guild:
                            user_results.append(f"ギルド不明(ID:{guild_id}): スキップ")
                            continue

                        member = guild.get_member(user_id)
                        if not member:
                            user_results.append(f"{guild.name}: メンバーではありません")
                            continue

                        removed_roles = []
                        skipped_roles = []

                        for role_group_role in guild_roles:
                            role = guild.get_role(role_group_role.role_id)
                            if not role:
                                skipped_roles.append(
                                    f"ID:{role_group_role.role_id}(削除済み)"
                                )
                                continue

                            # Botがそのロールを管理できるかチェック
                            if role >= guild.me.top_role:
                                skipped_roles.append(f"{role.name}(Botより高位)")
                                continue

                            # ユーザーがロールを持っているかチェック
                            if role not in member.roles:
                                skipped_roles.append(f"{role.name}(未所持)")
                                continue

                            try:
                                await member.remove_roles(
                                    role, reason=f"ロールグループ '{group_name}' を削除"
                                )
                                removed_roles.append(role.name)
                            except discord.Forbidden:
                                skipped_roles.append(f"{role.name}(権限不足)")
                            except discord.HTTPException:
                                skipped_roles.append(f"{role.name}(エラー)")

                        # このギルドの結果をまとめる
                        guild_result_parts = [f"**{guild.name}**"]
                        if removed_roles:
                            guild_result_parts.append(f"✅ {', '.join(removed_roles)}")
                        if skipped_roles:
                            guild_result_parts.append(f"⚠️ {', '.join(skipped_roles)}")

                        if len(guild_result_parts) > 1:
                            user_results.append(" - ".join(guild_result_parts))

                    # ユーザー全体の結果をまとめる
                    if user_results:
                        results.append(f"<@{user_id}>:\n  " + "\n  ".join(user_results))
                    else:
                        results.append(f"<@{user_id}>: 操作対象なし")

                # 結果を表示
                description = "\n\n".join(results[:10])
                if len(results) > 10:
                    description += "\n\n..."
                embed = discord.Embed(
                    title=f"ロールグループ `{group_name}` から削除",
                    description=description,
                    color=discord.Color.red(),
                )

                await ctx.respond(embed=embed, ephemeral=True)

        except Exception as e:
            self.logger.error(f"Error removing role group: {e}")
            await ctx.respond(
                "❌ ロールの削除中にエラーが発生しました。", ephemeral=True
            )


def setup(bot):
    bot.add_cog(RoleGroupCog(bot))
