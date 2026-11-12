"""Preparación de la URL de conexión (no necesita base de datos)."""

import ssl

from visagassist.db import preparar_url


def test_url_de_neon_activa_ssl_y_quita_parametros_que_pg8000_no_entiende() -> None:
    url, argumentos = preparar_url(
        "postgresql+pg8000://lector:clave@ep-ejemplo.neon.tech/tienda"
        "?sslmode=require&channel_binding=require"
    )
    assert "sslmode" not in url.query
    assert "channel_binding" not in url.query
    contexto = argumentos["ssl_context"]
    assert isinstance(contexto, ssl.SSLContext)
    assert contexto.verify_mode == ssl.CERT_REQUIRED
    assert contexto.check_hostname


def test_url_local_sin_ssl_queda_igual() -> None:
    url, argumentos = preparar_url("postgresql+pg8000://lector:clave@localhost:5432/tienda")
    assert url.host == "localhost"
    assert argumentos == {}
