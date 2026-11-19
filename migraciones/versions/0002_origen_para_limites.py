import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mensajes", sa.Column("origen", sa.String(64)))
    op.create_index("ix_mensajes_origen_creado_en", "mensajes", ["origen", "creado_en"])


def downgrade() -> None:
    op.drop_index("ix_mensajes_origen_creado_en", table_name="mensajes")
    op.drop_column("mensajes", "origen")
