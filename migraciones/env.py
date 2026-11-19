import os

from alembic import context
from sqlalchemy import create_engine

from visagassist.db import preparar_url

configuracion = context.config
url = configuracion.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL_ASISTENTE")
if not url:
    raise RuntimeError("Define DATABASE_URL_ASISTENTE para aplicar las migraciones")

datos_url, argumentos = preparar_url(url)
motor = create_engine(datos_url, connect_args=argumentos)

with motor.connect() as conexion:
    context.configure(connection=conexion, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
motor.dispose()
