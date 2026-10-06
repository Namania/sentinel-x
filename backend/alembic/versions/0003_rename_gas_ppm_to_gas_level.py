"""rename sensor_readings.gas_ppm to gas_level

The MQ-2 reports a raw level in millivolts, not a calibrated ppm value.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-06

"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("sensor_readings", "gas_ppm", new_column_name="gas_level")


def downgrade() -> None:
    op.alter_column("sensor_readings", "gas_level", new_column_name="gas_ppm")
