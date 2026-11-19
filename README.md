# 🤖 VisagAssist — Asistente con IA para VisagShop

![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB)
![FastAPI](https://img.shields.io/badge/FastAPI-Swagger-009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-solo%20lectura-336791)
[![Pruebas](https://github.com/stiven-triana-dev/VisagAssist/actions/workflows/pruebas.yml/badge.svg)](https://github.com/stiven-triana-dev/VisagAssist/actions)

**VisagAssist** es un servicio en Python donde los clientes y el administrador de la tienda
[VisagShop](https://github.com/stiven-triana-dev/VisagShop) hacen preguntas en español
("¿tienen jeans talla 32 por menos de 160 mil?", "¿cómo va mi pedido?") y un agente con la
API de Claude responde **consultando los datos reales de la tienda** mediante herramientas fijas.

> **Terminado (5 de 5 etapas) y en línea.** Agente con Claude Haiku 5.5 o Gemini (intercambiables), 7 herramientas, roles invitado / cliente / administrador con identidad firmada, historial con tokens y costo, límites de uso, defensas contra *prompt injection*, **evaluaciones con 42 casos (100 %)** y chat integrado en la tienda.

## 🌐 Pruébalo

- **En la tienda:** <https://visagshop.onrender.com> → botón **"Pregúntale al asistente"** (abajo a la derecha).
- **La API (Swagger):** <https://visagassist.onrender.com/docs>

> Corre en el plan gratuito de Render: si nadie lo ha usado en un rato, la primera respuesta puede tardar
> cerca de un minuto mientras el servicio despierta.

<p>
  <img src="docs/capturas/burbuja-escritorio.png" alt="La burbuja de VisagAssist en VisagShop (computador)" width="68%">
  <img src="docs/capturas/burbuja-movil.png" alt="La burbuja de VisagAssist en celular" width="26%">
</p>

## 🏗️ Arquitectura

```mermaid
flowchart LR
    N["Navegador<br/>(burbuja de chat)"] -- "pregunta" --> S["Servidor de VisagShop<br/>(Node / Express)"]
    S -- "pase firmado JWT HS256<br/>(rol, id del cliente, huella)" --> A["VisagAssist<br/>(Python / FastAPI)"]
    A -- "herramientas fijas" --> T[("Base de la tienda<br/>usuario de SOLO LECTURA")]
    A -- "historial, tokens y costo" --> H[("Base propia<br/>del asistente")]
    A -- "Messages API" --> M["Claude Haiku 5.5<br/>o Gemini"]
```

El navegador nunca habla directo con VisagAssist: el servidor de VisagShop, que sabe quién inició
sesión, firma un pase de 5 minutos con un secreto que solo conocen los dos servicios. Por eso nadie
puede hacerse pasar por otro cliente ni por el administrador, aunque modifique la página.

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
pg8000 · Pydantic · Alembic · pytest · ruff · mypy (estricto) · Docker · GitHub Actions · Render

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
-- Solo las tablas que usan las herramientas: nada de usuarios ni sesiones.
GRANT SELECT ON products, categories, sizes, colors, product_sizes, product_colors,
                orders, order_items TO visagassist_lectura;
ALTER ROLE visagassist_lectura SET default_transaction_read_only = on;
ALTER ROLE visagassist_lectura SET statement_timeout = '5s';
```

Usa la conexión **directa** de Neon (sin `-pooler`): con el pooler, los ajustes de solo lectura por
sesión no son confiables.

### Con Docker

```bash
docker build -t visagassist .
docker run --env-file .env -p 8000:8000 visagassist   # aplica las migraciones y arranca
```

### Publicación en Render

`render.yaml` crea el servicio (Docker, plan gratuito, Gemini). En VisagShop se configuran
`VISAGASSIST_URL` y el mismo `VISAGASSIST_SECRETO`; sin ellas la burbuja simplemente no aparece.

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

**Resultado actual:** 380 pruebas, 0 fallos (modelo simulado: las pruebas no gastan saldo). La CI
además construye la imagen Docker y comprueba que arranca.

## 🧭 Decisiones técnicas

- **pg8000 en vez de psycopg.** Es un conector de PostgreSQL escrito en Python puro. En el equipo
  de desarrollo (Windows con Control de aplicaciones inteligente) las librerías compiladas de
  psycopg quedaban bloqueadas; pg8000 funciona igual en Windows, Linux y Docker.
- **Búsqueda sin tildes sin extensiones.** Se usa `translate()` de PostgreSQL en vez de la
  extensión `unaccent`, para no depender de permisos especiales en la base.
- **API de Claude por HTTP directo (httpx).** El SDK oficial depende de un módulo compilado que el Control de aplicaciones de Windows bloquea; el bucle de herramientas está escrito a mano, con reintentos, tope de rondas y cálculo de costo.
- **Dos bases:** la de la tienda (solo lectura) y una propia para el historial, con migraciones Alembic.
- **Plurales en la búsqueda.** "jeans" debe encontrar "Jean 1.1": cada palabra se busca en
  singular. Se encontró probando la versión publicada, y quedó con su prueba.
- **Los `%` y `_` del usuario se buscan literalmente** (`autoescape=True`): no funcionan como
  comodines de `LIKE`.

## Lo que aprendí con este proyecto

Quería un proyecto en Python con IA que no fuera un chat genérico, sino uno que respondiera con los datos reales de mi tienda. La primera decisión fue la más importante: el modelo nunca escribe SQL. Solo puede elegir entre siete herramientas fijas que yo programé, y además se conecta a la base con un rol de PostgreSQL que solo puede leer ocho tablas, sin acceso a usuarios ni sesiones. Así, aunque alguien engañe al modelo con *prompt injection*, no hay forma de que modifique datos o vea cuentas ajenas.

Mi computador me obligó a cambiar de planes dos veces. El Control de aplicaciones inteligente de Windows bloqueaba las librerías compiladas: primero psycopg, el conector de PostgreSQL, y luego el SDK oficial de Anthropic. Cambié a pg8000, que está escrito en Python puro, y escribí a mano las llamadas a la API con httpx, incluido el ciclo de herramientas, los reintentos y el cálculo de costo. Fue más trabajo, pero entendí cómo funciona por dentro el *tool use*.

Tampoco tenía dinero para la API de Claude, así que agregué Gemini, que tiene un nivel gratuito, y dejé el proveedor intercambiable con una variable de entorno. Gemini trae sus propias reglas: el modelo más nuevo solo permitía 20 preguntas al día gratis, y en las respuestas con herramientas hay que devolver intacta una firma de razonamiento o la siguiente llamada falla.

Las evaluaciones me enseñaron a medir en vez de suponer. Escribí 42 casos con lo que el asistente debe y no debe responder. La primera versión aprobó 39; ajusté las instrucciones del sistema en dos rondas, revisando cada fallo, hasta llegar a 42 de 42.

Al publicarlo en Render aparecieron errores que no vi en local. La dirección de la base no funcionaba tal como la copia Neon (`postgresql://`), y luego tampoco cuando se pegaba con espacios, comillas o en formato de `psql`; ahora el servicio la acepta en cualquiera de esas formas. Probando la versión publicada descubrí que buscar «jeans» no encontraba «Jean», y lo arreglé buscando cada palabra en singular, con su prueba.

Como el plan gratis de Render tiene 750 horas al mes compartidas con mis otros proyectos, dejé que el asistente se duerma. La revisión de salud no toca la base de datos, para no despertar a Neon sin necesidad, y VisagShop despierta al asistente apenas el cliente abre el chat. Todo esto lo cuidan 380 pruebas con pytest, ruff y mypy en modo estricto, que corren en GitHub Actions en cada cambio.

## 🗺️ Etapas

1. ✅ Base del proyecto, conexión de solo lectura y primera herramienta con pruebas
2. ✅ Agente completo con la API de Claude, todas las herramientas y roles (cliente / administrador)
3. ✅ Seguridad: límites de uso, filtro de salida y pruebas contra *prompt injection*
4. ✅ Evaluaciones del agente (42 casos) con reporte, y Gemini como proveedor alternativo
5. ✅ Chat integrado en VisagShop (burbuja + intermediario que firma la identidad), Docker y publicación en Render

## 👤 Autor

**Stiven** — Estudiante de Ingeniería de Sistemas · San Gil, Colombia
[GitHub](https://github.com/stiven-triana-dev) · [VisagShop](https://github.com/stiven-triana-dev/VisagShop) · [UniGest](https://github.com/stiven-triana-dev/UniGest)
