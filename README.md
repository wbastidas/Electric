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

### Asistente: tres opciones para elegir

**Nuevo proyecto con el asistente** (en la lista de proyectos) pregunta, paso a
paso: datos del predio, plano DXF, zona climática y aire acondicionado (según
la zona, solo dormitorios, todos o ninguno), gusto de iluminación (general, zonas
sociales y dormitorios), equipos con circuito propio, refrigeradora y
exteriores. Al terminar diseña tres opciones y las muestra comparadas:

| Opción | Qué lleva |
| --- | --- |
| Básica | Plafón según el área, sin aire ni refrigeradora dedicada; exteriores solo si se pidieron |
| Recomendada | Exactamente lo que se respondió |
| Confort | Ojos de buey en zonas sociales, aire en todos los ambientes que lo admiten, refrigeradora y fachada completa |

Las tres quedan como escenarios del proyecto, con los mismos equipos
declarados. El usuario abre la que prefiera y la ajusta. El asistente también
se abre desde un proyecto con plano (pestaña Plano), sin pisar las opciones
anteriores. Ojos de buey es solo una opción de estilo: el general por defecto
es plafón.

### Escenarios y criterios de diseño

En la pestaña **Plano**, la tarjeta *Criterios del escenario* define cómo se
diseña; la tabla de ambientes permite cambiarlo en uno solo:

| Criterio | Opciones | Por ambiente |
| --- | --- | --- |
| Estilo de iluminación | Plafón según el área, un foco central, ojos de buey en cuadrícula | Sí |
| Zona climática | Costa, Sierra, Amazonía, Galápagos o sin zona | Aire sí, no o según zona |
| Tomacorrientes | Repartidos por el perímetro o en los extremos de las paredes | Sí |
| Refrigeradora | Tomacorriente dedicado con circuito propio en la cocina | — |
| Exteriores | Luz y toma de intemperie junto a cada puerta a la calle, luces de fachada cada 6 m, interruptor adentro | — |

Con zona Costa, Amazonía o Galápagos se propone aire acondicionado en
dormitorios, sala y estudio: área × 600 BTU/m², redondeado al equipo comercial
siguiente (9 000 a 36 000 BTU). La carga es la mayor entre la del equipo y la
de la tabla de cargas (2 500 W). Cada luminaria, sea foco u ojo de buey, cuenta
con la potencia por punto de CNEL (100 W).

La pestaña **Escenarios** copia el proyecto con su plano para probar otros
criterios, y compara todos lado a lado: luminarias, tomas, aires, circuitos,
carga, demanda, Tipo CNEL, breaker principal y medidor. En el modelo de prueba,
pasar a Costa con ojos de buey lleva la vivienda de Tipo I (2P 60 A) a Tipo II
(2P 100 A).

Desde la línea de comandos: `electric disenar … --zona costa --iluminacion
ojos_de_buey [--sin-exteriores] [--sin-refrigeradora]`.

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

### Viviendas de varios pisos

Un plano DXF por planta, dibujados con las mismas coordenadas. Cada planta se
lee y se diseña con su plano, y queda como un proyecto que se abre y se edita
en el editor de siempre. El tablero principal está en la planta más baja y
alimenta sus circuitos; cada otro piso tiene un subtablero cuyo alimentador
sube la altura de piso por nivel más el recorrido en planta entre tableros, y
se calcula con la demanda de esa planta. La demanda, la clasificación CNEL, el
breaker principal, el alimentador del medidor y el medidor salen de la vivienda
completa (todos los circuitos juntos), no de sumar las plantas. Se genera el
diagrama unifilar con el tablero principal y los subtableros. Las luces y tomas
de fachada van solo en la planta más baja.

En la web: «Viviendas de varios pisos» en el inicio, o «Abrir el ejemplo de dos
plantas» (`ejemplos/vivienda-2-pisos`). En la línea de comandos:
`electric disenar-pisos planta-baja.dxf planta-alta.dxf --equipos "cocina,ducha;ducha"`.

### Redes de media tensión: extensión de red

Una extensión de red de MT arranca en un poste de la red existente y sigue por
postes nuevos, que se marcan con clic sobre el mapa (OpenStreetMap), se
arrastran para moverlos o se pegan como coordenadas (latitud, longitud y kVA
del transformador, si lleva). La plataforma calcula:

- Vanos y ángulo de deflexión en cada poste; estructura por función y ángulo
  (derivación, pasante, angular, retención angular, retención cada N vanos,
  terminal). Los códigos de las unidades de propiedad se toman del catálogo de
  CNEL; mientras falten, se muestra el tipo.
- Vano máximo por zona (urbana o rural).
- Caída de tensión por momento eléctrico, vano por vano, con la carga de los
  transformadores nuevos que queda aguas abajo.
- Cortocircuito trifásico en el arranque y al final (c = 1,1).
- Seccionador fusible de la derivación y fusible de cada transformador.

Entrega la planimetría DXF/PDF con la tabla de estructuras y la red existente en
gris, el unifilar de MT y un KML para Google Earth o un SIG.

La red existente (postes con estructura, tramos de MT, transformadores y
protecciones) se lee del geoportal de CNEL por sus servicios ArcGIS REST, con
las capas y los campos configurados en la tabla `sig` del perfil. Ese cliente
**no está probado contra el geoportal real**: las direcciones de las capas y los
nombres de los campos son supuestos, y el servidor necesita acceso a
geoportal.cnelep.gob.ec. Mientras tanto se puede cargar desde un GeoJSON
exportado del SIG. Ejemplo: `ejemplos/red-mt` y `electric red-mt extension.json`.

### Industrias: cuadro de cargas y transformador

Para una industria se parte del cuadro de cargas en Excel o CSV: una fila por
máquina o grupo de máquinas iguales. Solo la potencia es obligatoria; lo que
falte (factor de potencia, eficiencia, factores de utilización y simultaneidad,
arranque) toma los valores típicos del perfil y la memoria lo indica.
`electric plantilla-industrial cuadro.xlsx` escribe una plantilla con ejemplos,
listas desplegables y una hoja de instrucciones.

El análisis entrega:

1. Por máquina: potencia de entrada (los HP pasan a kW y se dividen por la
   eficiencia), corriente, demanda y, en motores, corriente de arranque según
   el método (directo, estrella-triángulo, autotransformador, arrancador suave
   o variador).
2. Por tablero y total: demanda en kW, kVAr y kVA, factor de potencia y breaker.
3. Banco de capacitores normalizado para llegar al factor de potencia objetivo.
4. Transformador particular normalizado con reserva, su montaje (poste,
   pedestal o cuarto) y la caída momentánea al arrancar el motor mayor.
5. Nivel de servicio según la norma: red existente, transformador particular,
   cuarto de transformación en media tensión o subestación propia.
6. Si la norma admite la red existente, se comprueba el transformador de CNEL
   más cercano: fases, capacidad libre (kVA × cargabilidad − demanda actual
   medida o estimada por clientes y estrato), distancia, caída de tensión de la
   acometida y caída al arrancar motores. Si algo no cumple, se propone el
   transformador particular y se dice por qué.

Con el análisis se calculan además los estudios para presentar a CNEL:

- **Alimentadores** del tablero principal a cada tablero: breaker, conductor
  (con paralelos desde 1/0 AWG) y caída de tensión. La distancia de cada
  tablero se escribe en la tabla de tableros; si falta se suponen 20 m.
- **Circuitos de máquinas:** breaker y conductor. En motores el conductor va
  al 125 % y el breaker cubre un tercio del arranque, hasta 250 % de In
  (NEC 430.52).
- **Cortocircuito trifásico** (IEC 60909 simplificado) en el tablero principal
  y en cada tablero: red de CNEL (250 MVA si no se indica el dato de la
  factibilidad), transformador particular o existente con su acometida,
  alimentadores y aporte de los motores. Con la corriente se elige la
  capacidad de interrupción (Icu) de los breakers.
- **Diagrama unifilar** en DXF, PDF y PNG: red, transformador, medición,
  breaker principal, banco de capacitores, tableros y máquinas, con la
  corriente de cortocircuito en cada barra.

- **Coordinación de protecciones:** fusible tipo K del primario del
  transformador particular (que soporte la energización y lo proteja de una
  falla en bornes), breaker principal, alimentadores y el mayor breaker de
  máquina de cada tablero. Para cada par dice si es selectivo hasta la falla
  del punto o en qué tramo de corriente se cruzan las curvas, con el gráfico
  tiempo-corriente. Las curvas son genéricas: sirven para detectar problemas y
  deben reemplazarse por las del fabricante.
- Las cargas monofásicas se reparten por fase; la corriente de cada tablero y
  del principal es la de la fase más cargada.

Base normativa usada (leída de resúmenes, falta contrastar con los PDF):

- **ARCONEL-008/24** (distribución y comercialización): hasta 12 kW de demanda
  declarada se atiende en bajo voltaje; sobre 12 kW la distribuidora decide
  bajo, medio o alto voltaje tras el análisis de factibilidad. Por eso, sobre
  12 kW un transformador existente que cumple las comprobaciones se propone
  «sujeto a factibilidad», y si no, transformador particular.
- **ARCONEL-004/18**: radio de 200 m a un transformador existente.
- **CNEL MN-COM-AC-001** (acometidas y medición): CNEL provee el transformador
  hasta 12 kW; transformador monofásico de 100 kVA como máximo.
- **Normas para Sistemas de Distribución, Parte A** (homologación MEER): la
  demanda máxima diversificada por estrato (A a E) servirá para estimar la carga
  actual de un transformador; la tabla `demanda_estratos` aún es provisional.

En la aplicación web, la sección «Industrias y comercios grandes» de la página
de inicio crea una industria. En su pantalla se carga el Excel (o se descarga
la plantilla), se indican la ubicación y el transformador existente (potencia,
fases, distancia, demanda medida o clientes por estrato) y se ve la decisión
con cada comprobación, los resultados con su fórmula y tablas, y los tableros.

La lectura automática del transformador más cercano desde el geoportal de CNEL
(geoportal.cnelep.gob.ec/cnel/) está pendiente: la red de esta sesión no lo
alcanza. Por ahora sus datos se ingresan a mano.

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

# Industria: plantilla del cuadro de cargas y análisis
.venv/bin/electric plantilla-industrial cuadro.xlsx
.venv/bin/electric industrial cuadro.xlsx
.venv/bin/electric industrial cuadro.xlsx --existente-kva 75 --clientes C=20 --distancia 60
.venv/bin/electric industrial cuadro.xlsx --distancias TD-1=45 --scc 180 --unifilar unifilar.dxf --curvas curvas.png
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
- Estilos de iluminación, zonas climáticas (600 BTU/m² en Costa, Amazonía y
  Galápagos), capacidades y potencias de los aires, refrigeradora de 400 W,
  alturas de exteriores y aire, separación de luces de fachada (6 m) y muro
  exterior de 20 cm para ubicarlas.
- Industrial: valores típicos por tipo de carga, corrientes de arranque,
  potencias, impedancias y montaje de transformadores, bancos de capacitores,
  sistemas de 440/254 V y 480/277 V, conductores hasta 750 kcmil y breakers
  hasta 4000 A. También el FP objetivo de 0,92, la reserva del 20 %, la
  cargabilidad máxima del 80 % de un transformador existente, la caída de
  arranque del 15 %, la acometida de 200 m como máximo, la demanda por estrato
  y los umbrales de nivel de servicio (12 kW y 500 kW siguen Tipo I y II; los
  5000 kW de subestación son una propuesta).
- Cortocircuito: 250 MVA en la red, X/R 5 de transformadores, aporte de
  motores de 4 × In, c = 1,05, tablero principal junto al transformador,
  circuitos de máquinas de 15 m y la serie de capacidades de interrupción.
- Media tensión: conductores ACSR (R y X de uso general), vanos máximos de
  40 m urbano y 100 m rural, retención cada 10 vanos, caída máxima de 3 %,
  carga de transformadores al 80 %, seccionador de 10 kA y capas del SIG.
- Protecciones: fusible K a 1,5 × In primaria, curvas genéricas de breakers
  (disparo instantáneo a 10 × In) y fusibles K, margen de 75 % entre fusible y
  breaker, relación 1,6 entre breakers en serie y energización de 12 × In.

Cada uno está anotado en la tabla correspondiente y marcado `por_verificar`.
