import type { Borrador, BorradorNuevo, Estado, Perfil } from "./api/cliente";

export const texto = (valor: number | string | null | undefined): string =>
  valor === null || valor === undefined ? "" : String(valor);

/** Campo numérico vacío se guarda como "sin dato", nunca como cero. */
export const numero = (valor: string): string | null => (valor.trim() === "" ? null : valor.trim());

export const ETIQUETA_TIPO: Record<string, string> = {
  iluminacion: "Iluminación",
  tomacorrientes: "Tomacorrientes",
  especial: "Carga especial",
  alimentador: "Alimentador",
};

export const ETIQUETA_ESTADO: Record<Estado, string> = {
  verificado: "Verificado",
  por_verificar: "Por verificar",
  defecto_fuente: "Defecto de fuente",
};

const UNIDADES: [RegExp, string][] = [
  [/_ohm_km$/, " (Ω/km)"],
  [/_mm2$/, " (mm²)"],
  [/_m2$/, " (m²)"],
  [/_pct$/, " (%)"],
  [/_pulg$/, " (pulg)"],
  [/_kw$/, " (kW)"],
  [/_w$/, " (W)"],
  [/_a$/, " (A)"],
  [/_v$/, " (V)"],
  [/_m$/, " (m)"],
];

/** `corriente_diseno_a` → «Corriente diseno (A)». */
export const legible = (clave: string): string => {
  let unidad = "";
  let base = clave;
  for (const [patron, sufijo] of UNIDADES) {
    if (patron.test(clave)) {
      base = clave.replace(patron, "");
      unidad = sufijo;
      break;
    }
  }
  const limpio = base.replace(/_/g, " ");
  return limpio.charAt(0).toUpperCase() + limpio.slice(1) + unidad;
};

export const fecha = (iso: string): string =>
  new Date(iso).toLocaleString("es-EC", { dateStyle: "medium", timeStyle: "short" });

export const hoy = (): string => new Date().toISOString().slice(0, 10);

/** Primer identificador libre: C1, C2… */
export function nuevoIdCircuito(datos: Borrador): string {
  const usados = new Set(datos.circuitos.map((c) => c.id));
  let n = 1;
  while (usados.has(`C${n}`)) n += 1;
  return `C${n}`;
}

const TIPO_PUNTO: Record<string, string> = {
  iluminacion: "punto_luz",
  tomacorrientes: "tomacorriente",
};

/** Deja el circuito con exactamente `cantidad` puntos del tipo que le corresponde. */
export function conCantidadDePuntos(datos: Borrador, circuito: string, cantidad: number): Borrador {
  const tipo = datos.circuitos.find((c) => c.id === circuito)?.tipo ?? "iluminacion";
  const otros = datos.puntos.filter((p) => p.circuito !== circuito);
  const nuevos = Array.from({ length: Math.max(0, cantidad) }, (_, i) => ({
    id: `${circuito}-P${String(i + 1).padStart(2, "0")}`,
    tipo: TIPO_PUNTO[tipo] ?? "punto_luz",
    circuito,
    origen: "fijado" as const,
  }));
  return { ...datos, puntos: [...otros, ...nuevos] };
}

/** Vivienda de 120 m² lista para calcular, igual a la del repositorio. */
export function viviendaDeEjemplo(perfil: Perfil): BorradorNuevo {
  const circuitos = [
    { id: "C1", tipo: "iluminacion" as const, longitud_m: "18", puntos: 10 },
    { id: "C2", tipo: "iluminacion" as const, longitud_m: "22", puntos: 8 },
    { id: "C3", tipo: "tomacorrientes" as const, longitud_m: "20", puntos: 8 },
    { id: "C4", tipo: "tomacorrientes" as const, longitud_m: "25", puntos: 7, zona_humeda: true },
    { id: "C5", tipo: "especial" as const, longitud_m: "12", puntos: 0, zona_humeda: true },
    { id: "C6", tipo: "especial" as const, longitud_m: "10", puntos: 0 },
  ];
  return {
    nombre: "Vivienda unifamiliar de ejemplo, 120 m²",
    area_construida_m2: "120",
    perfil: { id: perfil.id, version: perfil.version },
    circuitos: circuitos.map(({ puntos: _puntos, ...c }) => ({ zona_humeda: false, ...c })),
    puntos: circuitos.flatMap((c) =>
      Array.from({ length: c.puntos }, (_, i) => ({
        id: `${c.id}-P${String(i + 1).padStart(2, "0")}`,
        tipo: TIPO_PUNTO[c.tipo] ?? "punto_luz",
        circuito: c.id,
        origen: "fijado" as const,
      })),
    ),
    cargas_especiales: [
      { id: "C5-EQ", tipo: "ducha", circuito: "C5", origen: "fijado" },
      { id: "C6-EQ", tipo: "cocina", circuito: "C6", origen: "fijado" },
    ],
    tablero: { id: "TD-1", alimentador_longitud_m: "15" },
  };
}
