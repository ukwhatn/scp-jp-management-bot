"""migrate_to_panopticon

Revision ID: 780b5a5101cb
Revises: a7f563ecdbc1
Create Date: 2026-01-03 21:18:32

DBモデルをpanopticon用に変更:
- site_id (Integer/BigInteger) -> site_unix_name (String)
- wd_site_id (Integer) -> wd_site_unix_name (String)

対象テーブル:
- site_application_notify_channels
- site_applications
- privilege_remove_queue
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "780b5a5101cb"
down_revision = "a7f563ecdbc1"
branch_labels = None
depends_on = None

# site_id to unix_name mapping
SITE_MAPPING = {
    578002: "scp-jp",
    591812: "scpsandbox-jp",
    852966: "scp-jp-sandbox2",
    1422068: "05command-ja",
    1971800: "scp-jp-sandbox3",
    4548695: "scp-jp-storage",
}


def upgrade():
    # === site_application_notify_channels ===
    # 1. 旧unique制約を削除
    # PostgreSQLは63文字制限があるため、テーブル名部分が切り詰められている
    op.drop_constraint(
        "site_application_notify_channel_site_id_guild_id_channel_id_key",
        "site_application_notify_channels",
        type_="unique",
    )

    # 2. 新カラム追加（nullable）
    op.add_column(
        "site_application_notify_channels",
        sa.Column("site_unix_name", sa.String(length=100), nullable=True),
    )

    # 3. データ変換
    for site_id, unix_name in SITE_MAPPING.items():
        op.execute(
            f"UPDATE site_application_notify_channels "
            f"SET site_unix_name = '{unix_name}' WHERE site_id = {site_id}"
        )

    # 4. 旧カラム削除
    op.drop_column("site_application_notify_channels", "site_id")

    # 5. 新カラムをnot nullに
    op.alter_column(
        "site_application_notify_channels",
        "site_unix_name",
        existing_type=sa.String(length=100),
        nullable=False,
    )

    # 6. 新unique制約を追加
    op.create_unique_constraint(
        "site_app_notify_channels_unix_name_guild_channel_key",
        "site_application_notify_channels",
        ["site_unix_name", "guild_id", "channel_id"],
    )

    # === site_applications ===
    # 1. 新カラム追加（nullable）
    op.add_column(
        "site_applications",
        sa.Column("site_unix_name", sa.String(length=100), nullable=True),
    )

    # 2. データ変換
    for site_id, unix_name in SITE_MAPPING.items():
        op.execute(
            f"UPDATE site_applications "
            f"SET site_unix_name = '{unix_name}' WHERE site_id = {site_id}"
        )

    # 3. 旧カラム削除
    op.drop_column("site_applications", "site_id")

    # 4. 新カラムをnot nullに
    op.alter_column(
        "site_applications",
        "site_unix_name",
        existing_type=sa.String(length=100),
        nullable=False,
    )

    # === privilege_remove_queue ===
    # 1. 新カラム追加（nullable）
    op.add_column(
        "privilege_remove_queue",
        sa.Column("wd_site_unix_name", sa.String(length=100), nullable=True),
    )

    # 2. データ変換
    for site_id, unix_name in SITE_MAPPING.items():
        op.execute(
            f"UPDATE privilege_remove_queue "
            f"SET wd_site_unix_name = '{unix_name}' WHERE wd_site_id = {site_id}"
        )

    # 3. 旧カラム削除
    op.drop_column("privilege_remove_queue", "wd_site_id")

    # 4. 新カラムをnot nullに
    op.alter_column(
        "privilege_remove_queue",
        "wd_site_unix_name",
        existing_type=sa.String(length=100),
        nullable=False,
    )


def downgrade():
    # === privilege_remove_queue ===
    op.add_column(
        "privilege_remove_queue",
        sa.Column("wd_site_id", sa.Integer(), nullable=True),
    )
    op.drop_column("privilege_remove_queue", "wd_site_unix_name")

    # === site_applications ===
    op.add_column(
        "site_applications",
        sa.Column("site_id", sa.BigInteger(), nullable=True),
    )
    op.drop_column("site_applications", "site_unix_name")

    # === site_application_notify_channels ===
    op.drop_constraint(
        "site_app_notify_channels_unix_name_guild_channel_key",
        "site_application_notify_channels",
        type_="unique",
    )
    op.add_column(
        "site_application_notify_channels",
        sa.Column("site_id", sa.Integer(), nullable=True),
    )
    op.drop_column("site_application_notify_channels", "site_unix_name")
    op.create_unique_constraint(
        "site_application_notify_channel_site_id_guild_id_channel_id_key",
        "site_application_notify_channels",
        ["site_id", "guild_id", "channel_id"],
    )
