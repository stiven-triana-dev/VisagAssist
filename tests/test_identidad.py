"""Pase firmado que identifica al cliente o al administrador."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from visagassist.identidad import (
    AUDIENCIA,
    EMISOR,
    Identidad,
    PaseInvalido,
    Rol,
    emitir_pase,
    verificar_pase,
)

SECRETO = "secreto-de-pruebas-con-al-menos-32-bytes"


def test_ida_y_vuelta_de_un_cliente() -> None:
    cliente = Identidad(Rol.CLIENTE, uuid4(), "Andrés")
    assert verificar_pase(emitir_pase(cliente, SECRETO), SECRETO) == cliente


def test_ida_y_vuelta_de_un_administrador() -> None:
    admin = Identidad(Rol.ADMINISTRADOR)
    assert verificar_pase(emitir_pase(admin, SECRETO), SECRETO) == admin


def test_rechaza_firma_con_otro_secreto() -> None:
    pase = emitir_pase(Identidad(Rol.ADMINISTRADOR), "otro-secreto-que-no-es-el-de-la-tienda")
    with pytest.raises(PaseInvalido):
        verificar_pase(pase, SECRETO)


def test_rechaza_pase_vencido() -> None:
    pase = emitir_pase(Identidad(Rol.ADMINISTRADOR), SECRETO, vigencia=timedelta(seconds=-60))
    with pytest.raises(PaseInvalido):
        verificar_pase(pase, SECRETO)


def test_rechaza_pase_que_dura_demasiado() -> None:
    pase = emitir_pase(Identidad(Rol.ADMINISTRADOR), SECRETO, vigencia=timedelta(days=30))
    with pytest.raises(PaseInvalido, match="más de lo permitido"):
        verificar_pase(pase, SECRETO)


def test_rechaza_pase_modificado() -> None:
    pase = emitir_pase(Identidad(Rol.CLIENTE, uuid4()), SECRETO)
    cabecera, _cuerpo, firma = pase.split(".")
    otro = emitir_pase(Identidad(Rol.ADMINISTRADOR), "x" * 40).split(".")[1]
    with pytest.raises(PaseInvalido):
        verificar_pase(f"{cabecera}.{otro}.{firma}", SECRETO)


def test_rechaza_algoritmo_none() -> None:
    ahora = datetime.now(UTC)
    datos = {"iss": EMISOR, "aud": AUDIENCIA, "iat": ahora, "exp": ahora + timedelta(minutes=5)}
    pase = jwt.encode({**datos, "rol": "administrador"}, key=None, algorithm="none")
    with pytest.raises(PaseInvalido):
        verificar_pase(pase, SECRETO)


def test_rechaza_rol_desconocido() -> None:
    ahora = datetime.now(UTC)
    pase = jwt.encode(
        {
            "iss": EMISOR,
            "aud": AUDIENCIA,
            "iat": ahora,
            "exp": ahora + timedelta(minutes=5),
            "rol": "superusuario",
        },
        SECRETO,
        algorithm="HS256",
    )
    with pytest.raises(PaseInvalido, match="Rol desconocido"):
        verificar_pase(pase, SECRETO)


def test_un_cliente_sin_id_no_es_valido() -> None:
    with pytest.raises(PaseInvalido, match="id de usuario"):
        verificar_pase(emitir_pase(Identidad(Rol.CLIENTE), SECRETO), SECRETO)


def test_rechaza_otro_emisor_o_audiencia() -> None:
    ahora = datetime.now(UTC)
    base = {"iat": ahora, "exp": ahora + timedelta(minutes=5), "rol": "administrador"}
    for extra in ({"iss": "otra-app", "aud": AUDIENCIA}, {"iss": EMISOR, "aud": "otra-api"}):
        pase = jwt.encode({**base, **extra}, SECRETO, algorithm="HS256")
        with pytest.raises(PaseInvalido):
            verificar_pase(pase, SECRETO)


def test_rechaza_basura() -> None:
    with pytest.raises(PaseInvalido):
        verificar_pase("esto-no-es-un-pase", SECRETO)


def test_clave_de_propietario_distingue_usuarios() -> None:
    a, b = Identidad(Rol.CLIENTE, uuid4()), Identidad(Rol.CLIENTE, uuid4())
    assert a.clave_propietario != b.clave_propietario
    assert Identidad(Rol.INVITADO).clave_propietario == "invitado:-"


def test_el_origen_firmado_viaja_en_el_pase() -> None:
    invitado = Identidad(Rol.INVITADO, origen="huella-del-visitante")
    assert verificar_pase(emitir_pase(invitado, SECRETO), SECRETO) == invitado
