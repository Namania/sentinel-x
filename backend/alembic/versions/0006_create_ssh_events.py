"""create ssh_events

One row per SSH connection to the Pi (accepted or refused) relayed by the host agent.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08

"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ssh_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("journal_id", sa.String(length=255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outcome", sa.String(length=8), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=True),
        sa.Column("key_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("key_comment", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ssh_events_occurred_at", "ssh_events", ["occurred_at"])
    op.create_index("uq_ssh_events_journal_id", "ssh_events", ["journal_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_ssh_events_journal_id", table_name="ssh_events")
    op.drop_index("ix_ssh_events_occurred_at", table_name="ssh_events")
    op.drop_table("ssh_events")
