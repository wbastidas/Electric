import type { ReactNode } from "react";
import { ErrorApi, type Estado } from "../api/cliente";
import { ETIQUETA_ESTADO } from "../util";

export function Insignia({ estado }: { estado: Estado }) {
  return <span className={`insignia ${estado}`}>{ETIQUETA_ESTADO[estado]}</span>;
}

export function Aviso({ tipo, children }: { tipo: "error" | "nota" | "alerta"; children: ReactNode }) {
  return (
    <div className={`aviso ${tipo}`} role={tipo === "error" ? "alert" : "status"}>
      {children}
    </div>
  );
}

export function MensajeError({ error }: { error: unknown }) {
  const e = error instanceof ErrorApi ? error : null;
  return (
    <Aviso tipo="error">
      <strong>{e ? e.message : "Ocurrió un error inesperado"}</strong>
      {e?.detalle ? <div>{e.detalle}</div> : null}
    </Aviso>
  );
}

export function Campo({
  etiqueta,
  ayuda,
  children,
}: {
  etiqueta: string;
  ayuda?: string;
  children: ReactNode;
}) {
  return (
    <label className="campo">
      <span className="etiqueta">{etiqueta}</span>
      {children}
      {ayuda ? <span className="ayuda">{ayuda}</span> : null}
    </label>
  );
}

export interface Pestana {
  id: string;
  titulo: string;
  /** Número o marca junto al título (p. ej. cuántas máquinas o un ✗). */
  marca?: string | number | null;
  alerta?: boolean;
}

/** Pestañas accesibles; la activa vive en la ruta para poder compartir el enlace. */
export function Pestanas({
  items,
  activa,
  base,
}: {
  items: Pestana[];
  activa: string;
  /** Ruta sin la pestaña, p. ej. `#/industrias/abc`. */
  base: string;
}) {
  const ir = (id: string) => {
    window.location.hash = `${base}/${id}`;
  };
  return (
    <nav className="pestanas" role="tablist">
      {items.map((p, n) => (
        <button
          key={p.id}
          role="tab"
          aria-selected={p.id === activa}
          tabIndex={p.id === activa ? 0 : -1}
          className={p.id === activa ? "activa" : ""}
          onClick={() => ir(p.id)}
          onKeyDown={(e) => {
            const paso = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
            if (!paso) return;
            const siguiente = items[(n + paso + items.length) % items.length];
            ir(siguiente.id);
            requestAnimationFrame(() =>
              (document.querySelector(`[role=tab][aria-selected=true]`) as HTMLElement | null)?.focus(),
            );
          }}
        >
          {p.titulo}
          {p.marca !== undefined && p.marca !== null && p.marca !== "" ? (
            <span className={`marca-pestana${p.alerta ? " alerta" : ""}`}>{p.marca}</span>
          ) : null}
        </button>
      ))}
    </nav>
  );
}

/** Pestaña pedida en la ruta, o la primera si no es válida. */
export const elegirPestana = (pedida: string | undefined, items: Pestana[]): string =>
  items.some((p) => p.id === pedida) ? (pedida as string) : items[0].id;
