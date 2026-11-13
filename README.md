# 🤖 VisagAssist — Asistente con IA para VisagShop

![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB)
![FastAPI](https://img.shields.io/badge/FastAPI-Swagger-009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-solo%20lectura-336791)
[![Pruebas](https://github.com/stiven-triana-dev/VisagAssist/actions/workflows/pruebas.yml/badge.svg)](https://github.com/stiven-triana-dev/VisagAssist/actions)

**VisagAssist** es un servicio en Python donde los clientes y el administrador de la tienda
[VisagShop](https://github.com/stiven-triana-dev/VisagShop) hacen preguntas en español
("¿tienen jeans talla 32 por menos de 160 mil?", "¿cómo va mi pedido?") y un agente con la
API de Claude responde **consultando los datos reales de la tienda** mediante herramientas fijas.

> **Estado: etapa 4 de 5.** Ya funcionan el agente (Claude Haiku 5.5 o Gemini, intercambiables), 7 herramientas, roles invitado / cliente / administrador con identidad firmada, historial con tokens y costo por respuesta, límites de uso, defensas contra *prompt injection* y **evaluaciones con 42 casos: 100 % en la versión actual**.

## 🔐 La idea central: la IA nunca escribe SQL

El modelo de IA **no** tiene acceso libre a la base. Solo puede elegir una herramienta de una
lista cerrada y darle argumentos; cada herramienta es una consulta fija y parametrizada.

| Barrera | Cómo se cumple |
| --- | --- |
| Sin SQL generado por IA | Las consultas se arman con SQLAlchemy (`select(...)`), con parámetros |
| Argumentos validados | Pydantic revisa tipos y rangos antes de consultar (texto ≤ 80, límite ≤ 20…) |
| Rol de solo lectura | El usuario de PostgreSQL solo tiene permiso `SELECT` |
| Conexión de solo lectura | Cada conexión abre en `READ ONLY`: aunque el rol tuviera más permisos, PostgreSQL rechaza escrituras |
| Consultas acotadas | `statement_timeout` de 5 s y límite de resultados |
| Identidad fuera del modelo | Quién pregunta llega en un pase firmado (JWT HS256) por VisagShop; `mis_pedidos` ni siquiera tiene un argumento de usuario |
| Permisos revisados dos veces | El modelo solo ve las herramientas de su rol, y al ejecutar se vuelve a revisar el permiso |
| Datos mínimos | Las herramientas no leen teléfono, dirección ni documento de los clientes |
| Entrada limpia | Se quitan caracteres invisibles (ancho cero, inversión de texto) y se normaliza el texto |
| Filtro de salida | Si la respuesta contiene fragmentos de las instrucciones internas o una clave de API, se reemplaza |
| Límites de uso | Preguntas por hora (invitados por huella HMAC de la IP, clientes por cuenta) y presupuesto diario en dólares, revisados antes de llamar al modelo; responde 429 con `Retry-After` |

Hay pruebas para cada barrera. En `tests/test_seguridad.py` un Claude simulado *obedece* al
atacante (pide pedidos ajenos, herramientas de administrador o inventadas, revela sus
instrucciones) y se comprueba que, aun así, el sistema no entrega nada indebido. Ver también
`tests/test_solo_lectura.py`, `tests/test_limites.py` y las pruebas de inyección SQL
en `tests/test_productos.py`).

## 🧰 Herramientas

| Herramienta | Qué hace | Etapa |
| --- | --- | --- |
| `buscar_productos` | Busca por texto (sin importar tildes ni mayúsculas), categoría, talla disponible y precio máximo | ✅ 1 |
| `ver_producto`, `listar_categorias` | Detalle de un producto y categorías con rango de precios | ✅ 2 |
| `mis_pedidos` | Solo los pedidos del cliente que pregunta (el id sale del pase firmado, nunca del modelo) | ✅ 2 |
| `pedidos_pendientes`, `resumen_ventas`, `productos_incompletos` | Solo administrador; sin datos de contacto de clientes | ✅ 2 |

## 📊 Evaluaciones del agente

Las pruebas automáticas usan un modelo simulado; las **evaluaciones** miden al modelo real. Son 42
preguntas ([evaluaciones/CASOS.md](evaluaciones/CASOS.md)) de catálogo, datos que no existen (no
debe inventar), privacidad, pedidos, administrador, temas ajenos, ataques, conversación y formato,
contra una copia fija del catálogo real (108 productos). Cada respuesta pasa por la ruta real
`/api/v1/chat` y se califica con reglas fijas: herramienta correcta, ninguna prohibida, el dato
esperado presente (precio, enlace, pedido) y nada indebido (otra persona, cifras inventadas).

| Versión | Aprobados | Cambio |
| --- | --- | --- |
| baseline | 39/42 (93 %) | — |
| v1 | 40/42 (95 %) | Regla 8: no tiene datos de envíos ni promociones; la búsqueda remite a `listar_categorias` para contar |
| **v2** | **42/42 (100 %)** | Frase explícita para el invitado; opción `orden=mas_caro` en la búsqueda |

Lo que encontraron (y no habrían visto las pruebas con modelo simulado):
- **Inventó un dato:** a "¿cuántos días tarda un envío?" respondió "2 a 4 días hábiles"; la tienda no tiene ese dato.
- **Concluyó con datos parciales:** dijo "10 gorras" (hay 42) porque la búsqueda devuelve máximo 10.
- **Repitió su instrucción interna** al invitado; el filtro de salida la bloqueó, como debía.

Modelo evaluado: `gemini-3.5-flash-lite` (plan gratuito de Google). Con 42 casos y una corrida por
versión el margen de azar es de varios puntos; cada falla tenía una causa concreta y se corrigió.
El calificador tiene sus propias pruebas: las respuestas de referencia aprueban y las vacías o
equivocadas no (`tests/test_calificador.py`).

```bash
python -m evaluaciones.ejecutar --variante v3        # corre los 42 casos (se puede reanudar)
```

El ejecutor tiene un candado: si cambian el ejecutor, el calificador o los casos, no corre hasta
que la persona dueña lo apruebe con `--aprobar-arnes`.

## 🔌 Proveedor de IA intercambiable

El agente está escrito con el formato de la API de Claude. `gemini.py` es un adaptador que traduce
esa misma petición al formato de Gemini (`generateContent`) y la respuesta de vuelta, incluidas las
llamadas a herramientas y la firma del razonamiento. Se elige con `PROVEEDOR_IA=claude|gemini`;
el agente, las herramientas, la seguridad y las pruebas no cambian.

## 🛠️ Tecnologías

Python 3.12 · FastAPI (documentación Swagger en `/docs`) · SQLAlchemy 2 · PostgreSQL (Neon) ·
pg8000 · Pydantic · pytest · ruff · mypy (estricto) · GitHub Actions

## 🚀 Cómo ejecutarlo

```bash
python -m venv .venv
.venv\Scripts\activate          # en Linux/Mac: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env          # y llena DATABASE_URL
uvicorn visagassist.api:app --reload
```

Abre <http://localhost:8000/docs> para probar las rutas.

### Base de datos de solo lectura

VisagAssist lee la misma base de VisagShop con un usuario propio que solo puede consultar:

```sql
CREATE ROLE visagassist_lectura LOGIN PASSWORD 'una-clave-segura';
GRANT CONNECT ON DATABASE neondb TO visagassist_lectura;
GRANT USAGE ON SCHEMA public TO visagassist_lectura;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO visagassist_lectura;
```

## 🧪 Pruebas

```bash
set TEST_DATABASE_URL=postgresql+pg8000://postgres:postgres@localhost:5432/visagassist_test
pytest
ruff check . && ruff format --check .
mypy src tests
```

Las pruebas de integración crean la estructura de VisagShop en una base vacía, cargan datos
conocidos y se conectan con un rol de solo lectura, igual que en producción. Sin
`TEST_DATABASE_URL`, esas pruebas se omiten y el resto corre normal.

**Resultado actual:** 370 pruebas, 0 fallos (modelo simulado: las pruebas no gastan saldo).

## 🧭 Decisiones técnicas

- **pg8000 en vez de psycopg.** Es un conector de PostgreSQL escrito en Python puro. En el equipo
  de desarrollo (Windows con Control de aplicaciones inteligente) las librerías compiladas de
  psycopg quedaban bloqueadas; pg8000 funciona igual en Windows, Linux y Docker.
- **Búsqueda sin tildes sin extensiones.** Se usa `translate()` de PostgreSQL en vez de la
  extensión `unaccent`, para no depender de permisos especiales en la base.
- **API de Claude por HTTP directo (httpx).** El SDK oficial depende de un módulo compilado que el Control de aplicaciones de Windows bloquea; el bucle de herramientas está escrito a mano, con reintentos, tope de rondas y cálculo de costo.
- **Dos bases:** la de la tienda (solo lectura) y una propia para el historial, con migraciones Alembic.
- **Los `%` y `_` del usuario se buscan literalmente** (`autoescape=True`): no funcionan como
  comodines de `LIKE`.

## 🗺️ Etapas

1. ✅ Base del proyecto, conexión de solo lectura y primera herramienta con pruebas
2. ✅ Agente completo con la API de Claude, todas las herramientas y roles (cliente / administrador)
3. ✅ Seguridad: límites de uso, filtro de salida y pruebas contra *prompt injection*
4. ✅ Evaluaciones del agente (42 casos) con reporte, y Gemini como proveedor alternativo
5. Chat integrado en VisagShop, Docker, publicación en Render y README final

## 👤 Autor

**Stiven** — Estudiante de Ingeniería de Sistemas · San Gil, Colombia
[GitHub](https://github.com/stiven-triana-dev) · [VisagShop](https://github.com/stiven-triana-dev/VisagShop) · [UniGest](https://github.com/stiven-triana-dev/UniGest)
