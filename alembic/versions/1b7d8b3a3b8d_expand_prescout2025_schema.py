"""Expand prescout2025 schema with 2025 scoring fields

Revision ID: 1b7d8b3a3b8d
Revises: 033016c23fe8
Create Date: 2025-02-02 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1b7d8b3a3b8d"
down_revision: Union[str, Sequence[str], None] = "033016c23fe8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    enum_type = sa.Enum(
        "NONE",
        "PARK",
        "SHALLOW",
        "DEEP",
        name="endgame2025",
        create_type=False,
    )

    numeric_columns = [
        "al4c",
        "al3c",
        "al2c",
        "al1c",
        "tl4c",
        "tl3c",
        "tl2c",
        "tl1c",
        "aNet",
        "tNet",
        "aProcessor",
        "tProcessor",
    ]

    for column_name in numeric_columns:
        op.add_column(
            "prescout2025",
            sa.Column(column_name, sa.Integer(), nullable=False, server_default="0"),
        )
        op.alter_column("prescout2025", column_name, server_default=None)

    op.add_column(
        "prescout2025",
        sa.Column("endgame", enum_type, nullable=False, server_default="NONE"),
    )
    op.alter_column("prescout2025", "endgame", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_column("prescout2025", "endgame")

    for column_name in [
        "tProcessor",
        "aProcessor",
        "tNet",
        "aNet",
        "tl1c",
        "tl2c",
        "tl3c",
        "tl4c",
        "al1c",
        "al2c",
        "al3c",
        "al4c",
    ]:
        op.drop_column("prescout2025", column_name)
