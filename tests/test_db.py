import ssl

import pytest

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


def test_acepta_la_url_tal_como_la_copia_neon() -> None:
    url, argumentos = preparar_url(
        "postgresql://lector:clave@ep-ejemplo.neon.tech/neondb?sslmode=require&channel_binding=require"
    )
    assert url.drivername == "postgresql+pg8000"
    assert dict(url.query) == {}
    assert "ssl_context" in argumentos


@pytest.mark.parametrize(
    "pegada",
    [
        "  postgresql://u:c@ep-x.neon.tech/neondb?sslmode=require \n",
        "'postgresql://u:c@ep-x.neon.tech/neondb?sslmode=require'",
        "psql 'postgresql://u:c@ep-x.neon.tech/neondb?sslmode=require'",
        '"postgresql://u:c@ep-x.neon.tech/neondb?sslmode=require"',
    ],
)
def test_tolera_espacios_comillas_y_formato_psql(pegada: str) -> None:
    url, _ = preparar_url(pegada)
    assert url.host == "ep-x.neon.tech"
    assert url.database == "neondb"


def test_una_url_invalida_no_revela_la_clave() -> None:
    with pytest.raises(ValueError) as error:
        preparar_url("usuario:clave-secreta@host/base")
    assert "clave-secreta" not in str(error.value)
