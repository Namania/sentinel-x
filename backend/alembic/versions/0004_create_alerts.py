"""create alerts

One row per out-of-bounds episode of a device metric; at most one open per (device, metric).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("metric", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_value", sa.Float(), nullable=False),
        sa.Column("peak_value", sa.Float(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_value", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alerts_opened_at", "alerts", ["opened_at"])
    op.create_index(
        "uq_alerts_open_per_metric",
        "alerts",
        ["device_id", "metric"],
        unique=True,
        postgresql_where=sa.text("resolved_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_alerts_open_per_metric", table_name="alerts")
    op.drop_index("ix_alerts_opened_at", table_name="alerts")
    op.drop_table("alerts")
