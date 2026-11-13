"""Huella del origen de cada pregunta, para el límite de peticiones de los invitados.

Se guarda un HMAC de la dirección IP (no la IP): sirve para contar preguntas por hora
sin poder saber de qué dirección vino cada una.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13
"""

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
