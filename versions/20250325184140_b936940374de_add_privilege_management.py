"""add privilege management

Revision ID: b936940374de
Revises: fa238d6e3a00
Create Date: 2025-03-25 18:41:40.185908

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b936940374de'
down_revision = 'fa238d6e3a00'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('privilege_remove_queue',
    sa.Column('dc_user_id', sa.BigInteger(), nullable=False),
    sa.Column('wd_site_id', sa.Integer(), nullable=False),
    sa.Column('wd_user_id', sa.Integer(), nullable=False),
    sa.Column('notify_guild_id', sa.BigInteger(), nullable=False),
    sa.Column('notify_channel_id', sa.BigInteger(), nullable=False),
    sa.Column('notify_message_id', sa.BigInteger(), nullable=False),
    sa.Column('expired_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_privilege_remove_queue_dc_user_id'), 'privilege_remove_queue', ['dc_user_id'], unique=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_privilege_remove_queue_dc_user_id'), table_name='privilege_remove_queue')
    op.drop_table('privilege_remove_queue')
    # ### end Alembic commands ###