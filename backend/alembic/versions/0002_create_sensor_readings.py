"""create sensor_readings

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06

"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sensor_readings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.String(length=64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("humidity_pct", sa.Float(), nullable=True),
        sa.Column("gas_ppm", sa.Integer(), nullable=True),
        sa.Column("gas_alert", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sensor_readings_device_time", "sensor_readings", ["device_id", "recorded_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_sensor_readings_device_time", table_name="sensor_readings")
    op.drop_table("sensor_readings")
