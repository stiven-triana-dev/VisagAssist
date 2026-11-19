import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from visagassist import historial
from visagassist.identidad import Identidad, Rol

ZONA = ZoneInfo("America/Bogota")
VENTANA = timedelta(hours=1)


@dataclass(frozen=True)
class Limites:
    por_hora: dict[Rol, int] = field(
        default_factory=lambda: {Rol.INVITADO: 15, Rol.CLIENTE: 30, Rol.ADMINISTRADOR: 60}
    )
    presupuesto_diario_usd: Decimal = Decimal("1.00")


class LimiteAlcanzado(Exception):
    def __init__(self, mensaje: str, reintentar_en: int) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.reintentar_en = reintentar_en  # segundos, para el encabezado Retry-After


def huella_origen(direccion_ip: str | None, secreto: str) -> str:
    valor = (direccion_ip or "desconocido").encode()
    return hmac.new(secreto.encode(), valor, hashlib.sha256).hexdigest()[:32]


def inicio_del_dia(ahora: datetime) -> datetime:
    local = ahora.astimezone(ZONA)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def verificar(
    sesion: Session,
    quien: Identidad,
    origen: str,
    limites: Limites,
    ahora: datetime | None = None,
) -> None:
    momento = ahora or datetime.now(UTC)

    hoy = inicio_del_dia(momento)
    if historial.gasto_desde(sesion, hoy) >= limites.presupuesto_diario_usd:
        manana = hoy + timedelta(days=1)
        raise LimiteAlcanzado(
            "El asistente alcanzó su límite de uso de hoy. "
            "Vuelve mañana o escríbenos por WhatsApp.",
            int((manana - momento).total_seconds()),
        )

    if quien.rol is Rol.INVITADO:
        hechas = historial.preguntas_desde(sesion, momento - VENTANA, origen=origen)
    else:
        hechas = historial.preguntas_desde(
            sesion, momento - VENTANA, propietario=quien.clave_propietario
        )
    if hechas >= limites.por_hora[quien.rol]:
        raise LimiteAlcanzado(
            "Hiciste muchas preguntas seguidas. Espera un rato y vuelve a intentarlo.",
            int(VENTANA.total_seconds()),
        )
