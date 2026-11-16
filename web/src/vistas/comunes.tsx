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
