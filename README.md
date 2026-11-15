# Electric

Plataforma de proyectos eléctricos para CNEL EP: a partir de un plano
arquitectónico genera el expediente eléctrico (planos, cuadros de carga,
unifilar, memoria, materiales y presupuesto) como **borrador trazable que firma
un ingeniero habilitado**.

Este repositorio contiene por ahora el núcleo de cálculo: el modelo del
proyecto, los perfiles normativos como datos y el motor de cálculo de vivienda
(RC-01 a RC-14). La ingesta de planos, la API y la interfaz web vienen después.

> **Estado de las tablas.** Todas las tablas del perfil `cnel-ep` están
> `por_verificar`: sus valores vienen del documento de requerimientos o de
> conocimiento general, no de los documentos oficiales. Nada de lo que produce
> el motor debe presentarse a CNEL EP hasta que un ingeniero las verifique.

## Uso

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

Pruebas y comprobaciones:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy
```

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `nucleo/electric/modelo` | Entidades del proyecto y serialización canónica |
| `nucleo/electric/perfiles` | Esquema, carga y consulta de perfiles |
| `nucleo/electric/calculo` | Motor: registro de cálculos, RC-01 a RC-14, resultados trazables |
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

Cada uno está anotado en la tabla correspondiente y marcado `por_verificar`.
