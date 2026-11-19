import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integracion

ESCRITURAS = [
    "INSERT INTO categories (name) VALUES ('Hackeada')",
    "UPDATE products SET price = 1",
    "DELETE FROM products",
    "DROP TABLE products",
    "CREATE TABLE intrusa (id int)",
]


@pytest.mark.parametrize("sql", ESCRITURAS)
def test_la_sesion_rechaza_cualquier_escritura(sesion: Session, sql: str) -> None:
    with pytest.raises(DBAPIError):
        sesion.execute(text(sql))
    sesion.rollback()
    assert sesion.execute(text("SELECT count(*) FROM products")).scalar_one() == 8


def test_aunque_se_pida_lectura_y_escritura_el_rol_no_tiene_permiso(sesion: Session) -> None:
    sesion.execute(text("SET TRANSACTION READ WRITE"))
    with pytest.raises(DBAPIError, match=r"permission denied|permiso denegado"):
        sesion.execute(text("UPDATE products SET price = 1"))
    sesion.rollback()


def test_las_consultas_tienen_tiempo_maximo(sesion: Session) -> None:
    valor = sesion.execute(text("SHOW statement_timeout")).scalar_one()
    assert valor == "5s"


def test_la_sesion_es_de_solo_lectura(sesion: Session) -> None:
    assert sesion.execute(text("SHOW transaction_read_only")).scalar_one() == "on"
