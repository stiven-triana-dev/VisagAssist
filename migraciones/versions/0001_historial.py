import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversaciones",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("propietario", sa.String(60), nullable=False),
        sa.Column("rol", sa.String(20), nullable=False),
        sa.Column(
            "creada_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "actualizada_en",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_conversaciones_propietario", "conversaciones", ["propietario"])

    op.create_table(
        "mensajes",
        sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
        sa.Column(
            "conversacion_id",
            sa.Uuid,
            sa.ForeignKey("conversaciones.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("autor", sa.String(10), nullable=False),
        sa.Column("texto", sa.Text, nullable=False),
        sa.Column("modelo", sa.String(40)),
        sa.Column("motivo", sa.String(20)),
        sa.Column("herramientas", JSONB, nullable=False, server_default="[]"),
        sa.Column("tokens_entrada", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_salida", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_cache_lectura", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_cache_escritura", sa.Integer, nullable=False, server_default="0"),
        sa.Column("costo_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("latencia_ms", sa.Integer),
        sa.Column(
            "creado_en", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("autor IN ('usuario', 'asistente')", name="mensajes_autor_valido"),
    )
    op.create_index("ix_mensajes_conversacion_id", "mensajes", ["conversacion_id", "id"])
    op.create_index("ix_mensajes_creado_en", "mensajes", ["creado_en"])


def downgrade() -> None:
    op.drop_table("mensajes")
    op.drop_table("conversaciones")
