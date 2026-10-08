"""drop intruder alerts

The "intruder" alert (opened by the vision worker for a blacklisted face) is gone: the metric no
longer exists, so its rows would be unreadable by the API and the dashboard. They are deleted.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08

"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM alerts WHERE metric = 'intruder'"))


def downgrade() -> None:
    # The deleted rows cannot be restored; the previous schema accepted them as it was.
    pass
