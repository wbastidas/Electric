# Caso de control UPS CT012742

Vivienda de 1.045 ft² calculada con NFPA 70. El documento de requerimientos da
tres cifras de esa tesis, y el motor debe reproducirlas:

| Cifra | Valor |
| --- | --- |
| Carga instalada | 9.861 VA |
| Demanda | 5.401 VA |
| Corriente a 240 V | 22,5 A |

## Qué es dato y qué es supuesto

No se tuvo la tesis a la vista. Las tres cifras son dato; el desglose de la
carga instalada es una **reconstrucción**:

| Carga | VA | Origen |
| --- | --- | --- |
| Iluminación general, 3 VA/ft² × 1.045 ft² | 3.135 | Reconstruido |
| Dos circuitos de pequeños artefactos | 3.000 | Reconstruido |
| Circuito de lavandería | 1.500 | Reconstruido |
| Resto no identificado | 2.226 | Diferencia hasta 9.861 |

La demanda sí queda determinada por las cifras: 3.000 VA al 100 % y el resto al
35 % da 3.000 + 0,35 × 6.861 = 5.401,35 VA, y 5.401,35 / 240 = 22,5 A.

## Defecto conocido de la fuente

La tesis aplica el 35 % a **todo** el subtotal, incluido lo que no es
iluminación general. El perfil `control-nfpa70` reproduce ese método a
propósito y por eso su tabla de tramos está marcada `defecto_fuente`. Este
perfil sirve solo para esta prueba; no debe usarse en proyectos.

Las potencias están en VA con factor de potencia 1, de modo que W y VA coinciden.
