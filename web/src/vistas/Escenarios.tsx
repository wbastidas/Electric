import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { api, type Escenario, type Perfil } from "../api/cliente";
import { Aviso, Campo, MensajeError } from "./comunes";

interface Props {
  id: string;
  revision: number;
  perfil: Perfil;
  sinGuardar: boolean;
}

/** Alternativas del mismo proyecto, lado a lado, para elegir con números. */
export function Escenarios({ id, revision, perfil, sinGuardar }: Props) {
  const consultas = useQueryClient();
  const escenarios = useQuery({
    queryKey: ["escenarios", id, revision],
    queryFn: () => api.escenarios(id),
  });
  const [nombre, setNombre] = useState("");
  const crear = useMutation({
    mutationFn: (n: string) => api.crearEscenario(id, n),
    onSuccess: (nuevo) => {
      setNombre("");
      consultas.invalidateQueries({ queryKey: ["escenarios"] });
      consultas.invalidateQueries({ queryKey: ["proyectos"] });
      window.location.hash = `#/proyectos/${nuevo.id}`;
    },
  });

  const alCrear = (e: FormEvent) => {
    e.preventDefault();
    if (nombre.trim()) crear.mutate(nombre.trim());
  };

  const lista = escenarios.data ?? [];

  return (
    <div className="columnas">
      <section className="tarjeta">
        <h2>Escenarios</h2>
        <p className="tenue">
          Cada escenario es una copia del proyecto con su plano, donde puede probar otro estilo de iluminación, zona
          climática, equipos o ediciones a mano. Los números de abajo salen del último guardado de cada uno.
        </p>
        {sinGuardar ? <Aviso tipo="alerta">Guarde los cambios para verlos en la comparación.</Aviso> : null}
        {escenarios.isError ? <MensajeError error={escenarios.error} /> : null}
        {lista.length ? (
          <Comparacion lista={lista} perfil={perfil} actual={id} />
        ) : escenarios.isLoading ? (
          <p>Calculando…</p>
        ) : null}
      </section>

      <section className="tarjeta">
        <h2>Nuevo escenario</h2>
        <form className="rejilla" onSubmit={alCrear}>
          <Campo etiqueta="Nombre" ayuda="Por ejemplo: «Con aires», «Ojos de buey en sala», «Económico».">
            <input value={nombre} maxLength={80} onChange={(e) => setNombre(e.target.value)} />
          </Campo>
          <div className="acciones izquierda">
            <button className="primario" type="submit" disabled={!nombre.trim() || crear.isPending || sinGuardar}>
              {crear.isPending ? "Copiando…" : "Crear a partir de este"}
            </button>
          </div>
        </form>
        <p className="tenue">
          Se abre la copia; ahí cambie los criterios en la pestaña Plano y pulse «Volver a diseñar».
        </p>
        {crear.isError ? <MensajeError error={crear.error} /> : null}
      </section>
    </div>
  );
}

/** Tabla con un escenario por columna; `actual` es el que está abierto. */
export function Comparacion({
  lista,
  perfil,
  actual,
}: {
  lista: Escenario[];
  perfil: Perfil;
  actual?: string;
}) {
  const estilo = (clave: string) => perfil.estilos.find((x) => x.id === clave)?.nombre ?? clave;
  const zona = (clave: string | null | undefined) =>
    clave ? perfil.zonas.find((x) => x.id === clave)?.nombre ?? clave : "Sin zona";
  const etiquetas = Array.from(new Set(lista.flatMap((e) => e.resumen.map((d) => d.etiqueta))));
  const fila = (titulo: string, valores: (string | number)[]) => (
    <tr key={titulo}>
      <th scope="row">{titulo}</th>
      {valores.map((v, i) => (
        <td key={lista[i].id} className={lista[i].id === actual ? "actual" : ""}>{v}</td>
      ))}
    </tr>
  );
  return (
    <div className="tabla-ancha">
      <table className="comparacion">
        <thead>
          <tr>
            <th />
            {lista.map((e) => (
              <th key={e.id} className={e.id === actual ? "actual" : ""}>
                {e.id === actual ? e.nombre : <a href={`#/proyectos/${e.id}`}>{e.nombre}</a>}
                {e.id === actual ? <span className="tenue"> (abierto)</span> : null}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fila("Iluminación", lista.map((e) => estilo(e.iluminacion)))}
          {fila("Zona climática", lista.map((e) => zona(e.zona_climatica)))}
          {fila("Luminarias", lista.map((e) => e.luminarias))}
          {fila("Tomacorrientes", lista.map((e) => e.tomacorrientes))}
          {fila("Aires acondicionados", lista.map((e) => e.aires))}
          {fila("Circuitos", lista.map((e) => e.circuitos))}
          {etiquetas.map((etiqueta) =>
            fila(
              etiqueta,
              lista.map((e) =>
                e.estado === "listo" ? e.resumen.find((d) => d.etiqueta === etiqueta)?.texto ?? "—" : "incompleto",
              ),
            ),
          )}
        </tbody>
      </table>
    </div>
  );
}
