import { useQuery } from "@tanstack/react-query";
import { api } from "../api/cliente";
import { fecha } from "../util";
import { MensajeError } from "./comunes";

const ACCION: Record<string, string> = { crear: "Creación", guardar: "Cambio guardado" };

export function Bitacora({ id }: { id: string }) {
  const bitacora = useQuery({ queryKey: ["bitacora", id], queryFn: () => api.bitacora(id) });
  if (bitacora.isError) return <MensajeError error={bitacora.error} />;
  if (!bitacora.data) return <p>Cargando…</p>;
  return (
    <div className="tabla-ancha">
      <table>
        <thead>
          <tr>
            <th>Revisión</th>
            <th>Acción</th>
            <th>Fecha</th>
            <th>Autor</th>
            <th>Contenido</th>
            <th>Huella</th>
          </tr>
        </thead>
        <tbody>
          {bitacora.data.map((e) => (
            <tr key={e.revision}>
              <td>{e.revision}</td>
              <td>{ACCION[e.accion] ?? e.accion}</td>
              <td>{fecha(e.fecha)}</td>
              <td>{e.autor}</td>
              <td>{e.resumen}</td>
              <td>
                <code>{e.huella.slice(0, 12)}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
