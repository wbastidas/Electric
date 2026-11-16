import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { api, type BorradorNuevo } from "../api/cliente";
import { fecha, viviendaDeEjemplo } from "../util";
import { Aviso, Campo, MensajeError } from "./comunes";

const abrir = (id: string) => {
  window.location.hash = `#/proyectos/${id}`;
};

export function Lista() {
  const consultas = useQueryClient();
  const proyectos = useQuery({ queryKey: ["proyectos"], queryFn: api.proyectos });
  const perfiles = useQuery({ queryKey: ["perfiles"], queryFn: api.perfiles });
  const [nombre, setNombre] = useState("");
  const [perfilId, setPerfilId] = useState("cnel-ep");

  const crear = useMutation({
    mutationFn: (datos: BorradorNuevo) => api.crear(datos),
    onSuccess: (proyecto) => {
      consultas.invalidateQueries({ queryKey: ["proyectos"] });
      abrir(proyecto.id);
    },
  });
  const borrar = useMutation({
    mutationFn: api.borrar,
    onSuccess: () => consultas.invalidateQueries({ queryKey: ["proyectos"] }),
  });

  const perfil = perfiles.data?.find((p) => p.id === perfilId) ?? perfiles.data?.[0];

  const alEnviar = (evento: FormEvent) => {
    evento.preventDefault();
    if (!perfil || !nombre.trim()) return;
    crear.mutate({ nombre: nombre.trim(), perfil: { id: perfil.id, version: perfil.version } });
  };

  return (
    <div className="pagina">
      <h1>Proyectos</h1>

      <section className="tarjeta">
        <h2>Nuevo proyecto</h2>
        <form className="fila-formulario" onSubmit={alEnviar}>
          <Campo etiqueta="Nombre del proyecto">
            <input
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              placeholder="Vivienda familia Pérez"
              required
            />
          </Campo>
          <Campo etiqueta="Perfil normativo">
            <select value={perfil?.id ?? ""} onChange={(e) => setPerfilId(e.target.value)}>
              {perfiles.data?.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.nombre} · v{p.version}
                </option>
              ))}
            </select>
          </Campo>
          <button className="primario" type="submit" disabled={!perfil || crear.isPending}>
            Crear proyecto
          </button>
          <button
            type="button"
            disabled={!perfil || crear.isPending}
            onClick={() => perfil && crear.mutate(viviendaDeEjemplo(perfil))}
          >
            Crear vivienda de ejemplo
          </button>
        </form>
        {crear.isError ? <MensajeError error={crear.error} /> : null}
        {perfiles.isError ? <MensajeError error={perfiles.error} /> : null}
      </section>

      {proyectos.isError ? <MensajeError error={proyectos.error} /> : null}
      {proyectos.data?.length === 0 ? (
        <Aviso tipo="nota">Todavía no hay proyectos. Cree uno o empiece con la vivienda de ejemplo.</Aviso>
      ) : null}
      {proyectos.data?.length ? (
        <div className="tabla-ancha">
          <table>
            <thead>
              <tr>
                <th>Proyecto</th>
                <th>Propietario</th>
                <th>Revisión</th>
                <th>Último cambio</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {proyectos.data.map((p) => (
                <tr key={p.id}>
                  <td>
                    <a href={`#/proyectos/${p.id}`}>{p.nombre}</a>
                  </td>
                  <td>{p.propietario || "—"}</td>
                  <td>{p.revision}</td>
                  <td>{fecha(p.actualizado)}</td>
                  <td className="derecha">
                    <button
                      className="discreto"
                      onClick={() => {
                        if (window.confirm(`¿Borrar "${p.nombre}"? No se puede deshacer.`))
                          borrar.mutate(p.id);
                      }}
                    >
                      Borrar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
