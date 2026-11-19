from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

import jwt

EMISOR = "visagshop"
AUDIENCIA = "visagassist"
VIGENCIA_MAXIMA = timedelta(minutes=10)


class Rol(StrEnum):
    INVITADO = "invitado"
    CLIENTE = "cliente"
    ADMINISTRADOR = "administrador"


@dataclass(frozen=True)
class Identidad:
    rol: Rol
    usuario_id: UUID | None = None
    nombre: str | None = None
    origen: str | None = None

    @property
    def clave_propietario(self) -> str:
        return f"{self.rol}:{self.usuario_id or '-'}"


INVITADO = Identidad(Rol.INVITADO)


class PaseInvalido(Exception):
    pass


def emitir_pase(identidad: Identidad, secreto: str, vigencia: timedelta = VIGENCIA_MAXIMA) -> str:
    ahora = datetime.now(UTC)
    datos: dict[str, object] = {
        "iss": EMISOR,
        "aud": AUDIENCIA,
        "iat": ahora,
        "exp": ahora + vigencia,
        "rol": identidad.rol.value,
    }
    if identidad.usuario_id:
        datos["sub"] = str(identidad.usuario_id)
    if identidad.nombre:
        datos["nombre"] = identidad.nombre
    if identidad.origen:
        datos["origen"] = identidad.origen
    return jwt.encode(datos, secreto, algorithm="HS256")


def verificar_pase(pase: str, secreto: str) -> Identidad:
    try:
        datos = jwt.decode(
            pase,
            secreto,
            algorithms=["HS256"],  # fijo: evita el ataque de cambiar el algoritmo a "none"
            audience=AUDIENCIA,
            issuer=EMISOR,
            options={"require": ["exp", "iat", "iss", "aud"]},
            leeway=5,
        )
    except jwt.PyJWTError as error:
        raise PaseInvalido(str(error)) from error

    emitido = datetime.fromtimestamp(datos["iat"], UTC)
    vence = datetime.fromtimestamp(datos["exp"], UTC)
    if vence - emitido > VIGENCIA_MAXIMA:
        raise PaseInvalido("El pase dura más de lo permitido")

    try:
        rol = Rol(str(datos.get("rol")))
    except ValueError as error:
        raise PaseInvalido("Rol desconocido") from error

    usuario_id: UUID | None = None
    if rol is Rol.CLIENTE:
        try:
            usuario_id = UUID(str(datos.get("sub")))
        except ValueError as error:
            raise PaseInvalido("Un cliente debe traer su id de usuario") from error

    nombre = datos.get("nombre")
    origen = datos.get("origen")
    return Identidad(
        rol,
        usuario_id,
        str(nombre)[:75] if nombre else None,
        str(origen)[:128] if origen else None,
    )
