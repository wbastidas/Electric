# Electric

Plataforma de proyectos eléctricos para CNEL EP: a partir de un plano
arquitectónico genera el expediente eléctrico (planos, cuadros de carga,
unifilar, memoria, materiales y presupuesto) como **borrador trazable que firma
un ingeniero habilitado**.

Hoy el repositorio lee un plano DXF de una vivienda, detecta sus ambientes,
propone la instalación (luminarias, interruptores, tomacorrientes, tablero,
circuitos y recorridos), la calcula (RC-01 a RC-14) y la entrega en un visor
web, en DXF con capas propias y en PDF o imagen. Faltan la verificación
normativa, la edición de puntos en el visor, las láminas, la memoria técnica
y el inicio de sesión.

> **Estado de las tablas.** Todas las tablas del perfil `cnel-ep` están
> `por_verificar`: sus valores vienen del documento de requerimientos o de
> conocimiento general, no de los documentos oficiales. Nada de lo que produce
> el motor debe presentarse a CNEL EP hasta que un ingeniero las verifique.

## Modelo de prueba

`ejemplos/vivienda-plano/` es el caso de prueba de punta a punta: una vivienda
de 12 × 10 m con 9 ambientes.

| Archivo | Qué es |
| --- | --- |
| `planta.dxf` | Plano arquitectónico de prueba (lo genera `generar_plano.py`) |
| `red.dxf` | El mismo plano en gris con la instalación en capas `E-*` |
| `red.png`, `red.pdf` | Lámina para revisar sin abrir CAD |
| `proyecto.json` | Proyecto resultante, con ambientes, puntos, circuitos y recorridos |

Para repetirlo desde `nucleo/`:

```bash
.venv/bin/electric disenar ../ejemplos/vivienda-plano/planta.dxf \
  --equipos ducha,cocina --alimentador 12 --salida ../ejemplos/vivienda-plano
```

En la aplicación web, el botón **Abrir el modelo de prueba con plano** hace lo
mismo y muestra la red en el visor.

### Corregir la red a mano

En la pestaña **Plano**, con la instalación diseñada:

- **Mover:** arrastre cualquier símbolo (luminaria, tomacorriente, carga
  especial, interruptor o tablero). Queda fijado (●) y el servidor rehace los
  recorridos, las longitudes y el cálculo completo.
- **Agregar:** elija *Luminaria* o *Tomacorriente* y toque el plano. El punto
  va al circuito de ese tipo que ya pasa por el ambiente o, si no hay, al
  menos cargado. Esc termina.
- **Cambiar de circuito, quitar o liberar:** toque el símbolo y use su ficha.
  Si un circuito queda vacío se elimina; si supera el máximo de puntos del
  perfil, aparece un aviso.
- **Deshacer:** vuelve un paso atrás por cada pulsación, incluido un rediseño.
  No pasa de un cambio de plano.
- **Volver a diseñar** respeta lo fijado. Descarta los puntos agregados a mano
  y los cambios de circuito, y lo avisa.

Un interruptor movido sigue mandando las luces de su ambiente aunque quede en
otro (por ejemplo, en el pasillo junto a la puerta). Cada cambio queda en la
bitácora con lo que se hizo.

El plano es sintético. La detección de ambientes solo se ha probado con él;
con planos reales de arquitectos habrá casos que todavía no resuelve.

## Uso

### Aplicación web

```bash
# 1. API (también sirve la interfaz compilada si existe web/dist)
cd api
uv venv && uv pip install -e ../nucleo -e ".[dev]"
.venv/bin/python -m electric_api          # http://127.0.0.1:8000

# 2. Interfaz
cd web
pnpm install
pnpm build                                # la sirve la API en el puerto 8000
pnpm dev                                  # o en desarrollo: http://localhost:5173
```

En la pantalla de proyectos, **Crear vivienda de ejemplo** deja un proyecto
listo para calcular. Los proyectos se guardan en `api/electric.db` (SQLite);
`ELECTRIC_BD` acepta cualquier URL de SQLAlchemy, por ejemplo PostgreSQL.

Todavía no hay inicio de sesión ni roles: no exponga la API fuera de su equipo.

### Línea de comandos

```bash
cd nucleo
uv venv && uv pip install -e ".[dev]"

# Cuadro de cargas y resumen de un proyecto
.venv/bin/electric calcular ../ejemplos/vivienda-120m2/proyecto.json

# Fórmula, entradas y tablas de un resultado
.venv/bin/electric calcular ../ejemplos/vivienda-120m2/proyecto.json --explicar RC-08:C4

# Salida JSON canónica, con la huella del cálculo
.venv/bin/electric calcular ../ejemplos/vivienda-120m2/proyecto.json --json

# Validar un perfil
.venv/bin/electric validar-perfil ../perfiles/cnel-ep
```

### Pruebas y comprobaciones

```bash
# en nucleo/ y en api/
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy

# en web/
pnpm build
```

Si cambia la API, regenere los tipos de la interfaz: `python exportar_openapi.py`
en `api/` y `pnpm gen` en `web/`.

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `nucleo/electric/modelo` | Entidades del proyecto y serialización canónica |
| `nucleo/electric/perfiles` | Esquema, carga y consulta de perfiles |
| `nucleo/electric/ingesta` | Lectura de DXF y clasificación de capas |
| `nucleo/electric/interpretacion` | Detección de ambientes y de su uso |
| `nucleo/electric/diseno` | Diseño automático: puntos, tablero, circuitos, recorridos |
| `nucleo/electric/salida_cad` | DXF de salida, imagen y PDF |
| `nucleo/electric/calculo` | Motor: registro de cálculos, RC-01 a RC-14, resultados trazables |
| `api/electric_api` | API FastAPI: proyectos, cálculos, bitácora |
| `web/src` | Interfaz React: proyectos, datos, circuitos, cálculos, bitácora |
| `perfiles/cnel-ep` | Perfil CNEL EP + NEC-SB-IE (tablas `por_verificar`) |
| `perfiles/control-nfpa70` | Perfil de prueba para el caso de control; no usar en proyectos |
| `ejemplos/` | Proyectos de ejemplo y su salida guardada para regresión |

## Principios

- **Determinista.** Aritmética en `Decimal`, sin reloj, red ni aleatoriedad: el
  mismo proyecto y el mismo perfil dan la misma huella. Ningún valor lo genera
  un modelo de lenguaje.
- **Trazable.** Cada resultado lleva fórmula, entradas, tabla, versión, fila
  usada y estado de verificación; hereda el peor estado de lo que usa.
- **Normativa como datos.** Corregir una tabla o agregar una distribuidora es
  un cambio en `perfiles/`, no en el código.
- **Fallo seguro.** Si falta una fila o un dato, el motor se detiene con un
  error tipado; nunca interpola ni asume.

## Cómo se verifica una tabla

1. Compare cada fila de `perfiles/cnel-ep/tablas/<tabla>.yaml` con el documento
   oficial y corrija los valores, la `fuente.numeral` y la `fuente.url`.
2. Cambie `estado` a `verificado` y agregue quién verificó:

   ```yaml
   estado: verificado
   verificacion: {por: Ing. Nombre Apellido, fecha: 2026-12-01}
   ```

3. Suba la `version` de la tabla y la del perfil, y regenere
   `ejemplos/vivienda-120m2/resultados.json` si cambian cifras.

## Supuestos de esta versión que no vienen del documento de requerimientos

- Factor de potencia por defecto 0,92 y temperatura ambiente 30 °C.
- Conexión de cada carga especial (ducha a fase-neutro; cocina, calefón, aire
  acondicionado y cargador EV entre líneas).
- Filas intermedias de factores de demanda y de conductor de tierra.
- Ampacidad, resistencia, reactancia, factores de corrección, áreas de ducto y
  series de breakers, tableros y barras: valores de uso general.
- El alimentador admite de caída la diferencia entre el límite total y el del
  ramal (5 % − 3 % = 2 %).
- El desbalance se mide como (fase mayor − fase menor) / fase mayor.

- Plantillas de diseño por ambiente (luminarias por m², separación de tomas,
  alturas, equipos admitidos) y alturas de interruptor, tablero y techo.
- Los recorridos son ortogonales y encadenan los puntos; no esquivan muros ni
  comparten ducto entre circuitos.
- La caída de tensión de un circuito diseñado usa la longitud equivalente por
  momento de carga (promedio de la distancia del tablero a cada punto).

Cada uno está anotado en la tabla correspondiente y marcado `por_verificar`.
