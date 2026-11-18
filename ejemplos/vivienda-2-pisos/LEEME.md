# Vivienda de dos plantas

Ejemplo de vivienda de varios pisos: un plano DXF por planta, dibujados con
las mismas coordenadas (10 × 8 m, escalera en la misma esquina).

| Planta | Ambientes | Equipos declarados |
| --- | --- | --- |
| Planta baja (PB) | sala-comedor, cocina, lavandería, baño social, estudio, escalera | cocina, ducha |
| Planta alta (P1) | 3 dormitorios, baño master, baño, hall, escalera | ducha |

Zona climática Costa: aire acondicionado en los ambientes que lo admiten y
refrigeradora en la cocina. La fachada solo en la planta baja.

Resultado: tablero principal TP en la planta baja y subtablero TD-P1 en la alta,
uno sobre otro en la escalera (alimentador de 2,8 m, solo vertical). La
vivienda completa, de 165,4 m², tiene 24,95 kW de demanda y es Tipo II, con
breaker principal de 125 A, alimentador 1/0 AWG y medidor clase 200.

Archivos:

- `planta-baja.dxf`, `planta-alta.dxf`: planos de entrada (`generar_planos.py`).
- `planta-*-red.dxf` y `.png`: instalación diseñada en cada planta.
- `unifilar.dxf`, `.pdf`, `.png`: medidor, tablero principal y subtablero.
- `vivienda.json`: todos los circuitos de la vivienda, con los que se calcula.

Para regenerar:

```bash
python generar_planos.py
../../nucleo/.venv/bin/electric disenar-pisos planta-baja.dxf planta-alta.dxf \
  --nombres "Planta baja,Planta alta" --equipos "cocina,ducha;ducha" --zona costa \
  --nombre "Vivienda de dos plantas" --salida .
```

En la aplicación web: «Abrir el ejemplo de dos plantas» en la página de inicio.
