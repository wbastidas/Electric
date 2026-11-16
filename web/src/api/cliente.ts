import type { components } from "./esquema";

type S = components["schemas"];
export type Borrador = S["Borrador"];
export type Calculos = S["Calculos"];
export type Circuito = S["Circuito"];
export type CargaEspecial = S["CargaEspecial"];
export type EntradaBitacora = S["EntradaBitacora"];
export type Perfil = S["PerfilOut"];
export type ProyectoDetalle = S["ProyectoDetalle"];
export type ProyectoResumen = S["ProyectoResumen"];
export type Punto = S["Punto"];
export type Resultado = S["ResultadoOut"];
export type Supuesto = S["Supuesto"];
export type Estado = Resultado["estado"];
export type Plano = S["Plano"];
export type Ambiente = S["Ambiente"];
export type Fondo = S["Fondo"];
export type Diseno = S["DisenoOut"];

/** Lo mínimo para crear un proyecto; el servidor completa el resto. */
export type BorradorNuevo = Partial<Borrador> & Pick<Borrador, "nombre" | "perfil">;

/** Error de la API en formato RFC 9457. */
export class ErrorApi extends Error {
  constructor(
    readonly estado: number,
    readonly codigo: string,
    titulo: string,
    readonly detalle: string,
  ) {
    super(titulo);
  }
}

async function pedir<T>(ruta: string, opciones?: RequestInit): Promise<T> {
  let respuesta: Response;
  try {
    respuesta = await fetch(`/api/v1${ruta}`, {
      headers: { "Content-Type": "application/json" },
      ...opciones,
    });
  } catch {
    throw new ErrorApi(0, "sin_conexion", "No se pudo conectar con el servidor", "");
  }
  if (respuesta.status === 204) return undefined as T;
  const cuerpo = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) {
    const errores: { campo: string; mensaje: string }[] = cuerpo.errores ?? [];
    const detalle = cuerpo.detail ?? errores.map((e) => `${e.campo}: ${e.mensaje}`).join("; ");
    throw new ErrorApi(
      respuesta.status,
      cuerpo.codigo ?? "error",
      cuerpo.title ?? "Error del servidor",
      detalle ?? "",
    );
  }
  return cuerpo as T;
}

export const api = {
  perfiles: () => pedir<Perfil[]>("/perfiles"),
  proyectos: () => pedir<ProyectoResumen[]>("/proyectos"),
  proyecto: (id: string) => pedir<ProyectoDetalle>(`/proyectos/${id}`),
  crear: (datos: BorradorNuevo) =>
    pedir<ProyectoDetalle>("/proyectos", { method: "POST", body: JSON.stringify(datos) }),
  guardar: (id: string, revision: number, datos: Borrador) =>
    pedir<ProyectoDetalle>(`/proyectos/${id}`, {
      method: "PUT",
      body: JSON.stringify({ revision, datos }),
    }),
  borrar: (id: string) => pedir<void>(`/proyectos/${id}`, { method: "DELETE" }),
  calculos: (id: string) => pedir<Calculos>(`/proyectos/${id}/calculos`),
  bitacora: (id: string) => pedir<EntradaBitacora[]>(`/proyectos/${id}/bitacora`),
  ejemploConPlano: () => pedir<ProyectoDetalle>("/ejemplos/vivienda-plano", { method: "POST" }),
  subirPlano: (id: string, revision: number, archivo: File, escala?: string) => {
    const consulta = new URLSearchParams({ revision: String(revision), nombre: archivo.name });
    if (escala) consulta.set("escala", escala);
    return pedir<ProyectoDetalle>(`/proyectos/${id}/plano?${consulta}`, {
      method: "POST",
      body: archivo,
      headers: { "Content-Type": "application/octet-stream" },
    });
  },
  fondo: (id: string) => pedir<Fondo>(`/proyectos/${id}/plano/fondo`),
  disenar: (id: string, revision: number) =>
    pedir<Diseno>(`/proyectos/${id}/diseno`, { method: "POST", body: JSON.stringify({ revision }) }),
  urlSalida: (id: string, formato: "dxf" | "png" | "pdf") => `/api/v1/proyectos/${id}/salida.${formato}`,
};
