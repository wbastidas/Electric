import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { api, type BorradorNuevo } from "../api/cliente";
import { fecha, viviendaDeEjemplo } from "../util";
import { Aviso, Campo, MensajeError } from "./comunes";

const abrir = (id: string) => {
  window.location.hash = `#/proyectos/${id}`;
};

function Edificaciones() {
  const consultas = useQueryClient();
  const edificaciones = useQuery({ queryKey: ["edificaciones"], queryFn: api.edificaciones });
  const perfiles = useQuery({ queryKey: ["perfiles"], queryFn: api.perfiles });
  const [nombre, setNombre] = useState("");
  const abrirEdificacion = (id: string) => {
    consultas.invalidateQueries({ queryKey: ["edificaciones"] });
    window.location.hash = `#/edificaciones/${id}`;
  };
  const crear = useMutation({
    mutationFn: (n: string) => {
      const perfil = perfiles.data?.find((p) => p.id === "cnel-ep") ?? perfiles.data?.[0];
      if (!perfil) throw new Error("sin perfil");
      return api.crearEdificacion({
        nombre: n,
        perfil: { id: perfil.id, version: perfil.version },
        propietario: "",
        medidor_m: "15",
        altura_piso_m: "2.8",
        preferencias: { iluminacion: "plafon", zona_climatica: null, refrigeradora: true, exteriores: true, ambientes: {} },
      });
    },
    onSuccess: (e) => abrirEdificacion(e.id),
  });
  const ejemplo = useMutation({ mutationFn: api.ejemploPisos, onSuccess: (e) => abrirEdificacion(e.id) });
  const borrar = useMutation({
    mutationFn: api.borrarEdificacion,
    onSuccess: () => {
      consultas.invalidateQueries({ queryKey: ["edificaciones"] });
      consultas.invalidateQueries({ queryKey: ["proyectos"] });
    },
  });
  return (
    <section className="tarjeta">
      <h2>Viviendas de varios pisos</h2>
      <p className="tenue">
        Un plano DXF por planta: el tablero principal queda en la planta baja y cada piso tiene su subtablero con el
        alimentador calculado.
      </p>
      <form
        className="fila-formulario"
        onSubmit={(e) => {
          e.preventDefault();
          if (nombre.trim()) crear.mutate(nombre.trim());
        }}
      >
        <Campo etiqueta="Nombre de la vivienda">
          <input value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Casa Pérez, dos plantas" />
        </Campo>
        <button className="primario" type="submit" disabled={!nombre.trim() || crear.isPending}>
          Nueva vivienda de varios pisos
        </button>
        <button type="button" disabled={ejemplo.isPending} onClick={() => ejemplo.mutate()}>
          {ejemplo.isPending ? "Diseñando las dos plantas…" : "Abrir el ejemplo de dos plantas"}
        </button>
      </form>
      {crear.isError ? <MensajeError error={crear.error} /> : null}
      {ejemplo.isError ? <MensajeError error={ejemplo.error} /> : null}
      {edificaciones.data?.length ? (
        <div className="tabla-ancha">
          <table>
            <thead>
              <tr>
                <th>Vivienda</th>
                <th>Propietario</th>
                <th>Plantas</th>
                <th>Último cambio</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {edificaciones.data.map((e) => (
                <tr key={e.id}>
                  <td><a href={`#/edificaciones/${e.id}`}>{e.nombre}</a></td>
                  <td>{e.propietario || "—"}</td>
                  <td>{e.pisos}</td>
                  <td>{fecha(e.actualizado)}</td>
                  <td className="derecha">
                    <button
                      className="discreto"
                      onClick={() => {
                        if (window.confirm(`¿Borrar "${e.nombre}" y sus plantas? No se puede deshacer.`))
                          borrar.mutate(e.id);
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
    </section>
  );
}

function Industrias() {
  const consultas = useQueryClient();
  const industrias = useQuery({ queryKey: ["industrias"], queryFn: api.industrias });
  const [nombre, setNombre] = useState("");
  const crear = useMutation({
    mutationFn: (n: string) => api.crearIndustria({ nombre: n }),
    onSuccess: (industria) => {
      consultas.invalidateQueries({ queryKey: ["industrias"] });
      window.location.hash = `#/industrias/${industria.id}`;
    },
  });
  const borrar = useMutation({
    mutationFn: api.borrarIndustria,
    onSuccess: () => consultas.invalidateQueries({ queryKey: ["industrias"] }),
  });
  return (
    <section className="tarjeta">
      <h2>Industrias y comercios grandes</h2>
      <p className="tenue">
        Cuadro de cargas en Excel, motores, factor de potencia, transformador y si puede usar el transformador
        existente de CNEL o necesita uno particular.
      </p>
      <form
        className="fila-formulario"
        onSubmit={(e) => {
          e.preventDefault();
          if (nombre.trim()) crear.mutate(nombre.trim());
        }}
      >
        <Campo etiqueta="Nombre de la industria">
          <input value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Metalmecánica Andina" />
        </Campo>
        <button className="primario" type="submit" disabled={!nombre.trim() || crear.isPending}>
          Nueva industria
        </button>
      </form>
      {crear.isError ? <MensajeError error={crear.error} /> : null}
      {industrias.isError ? <MensajeError error={industrias.error} /> : null}
      {industrias.data?.length ? (
        <div className="tabla-ancha">
          <table>
            <thead>
              <tr>
                <th>Industria</th>
                <th>Propietario</th>
                <th>Máquinas</th>
                <th>Último cambio</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {industrias.data.map((i) => (
                <tr key={i.id}>
                  <td><a href={`#/industrias/${i.id}`}>{i.nombre}</a></td>
                  <td>{i.propietario || "—"}</td>
                  <td>{i.maquinas}</td>
                  <td>{fecha(i.actualizado)}</td>
                  <td className="derecha">
                    <button
                      className="discreto"
                      onClick={() => {
                        if (window.confirm(`¿Borrar "${i.nombre}"? No se puede deshacer.`)) borrar.mutate(i.id);
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
    </section>
  );
}

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
  const ejemplo = useMutation({
    mutationFn: api.ejemploConPlano,
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
        <div className="acciones izquierda">
          <a className="boton primario" href="#/nuevo">Nuevo proyecto con el asistente</a>
          <span className="tenue">
            Datos, plano, clima, gustos de iluminación y equipos: al final le propone tres opciones para elegir.
          </span>
        </div>
        <details>
          <summary>Crear un proyecto vacío, sin asistente</summary>
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
            Ejemplo por formulario
          </button>
        </form>
        </details>
        <div className="acciones izquierda">
          <button disabled={ejemplo.isPending} onClick={() => ejemplo.mutate()}>
            {ejemplo.isPending ? "Diseñando…" : "Abrir el modelo de prueba con plano"}
          </button>
          <span className="tenue">
            Vivienda de 12 × 10 m: lee el plano, detecta 9 ambientes y dibuja la instalación.
          </span>
        </div>
        {crear.isError ? <MensajeError error={crear.error} /> : null}
        {ejemplo.isError ? <MensajeError error={ejemplo.error} /> : null}
        {perfiles.isError ? <MensajeError error={perfiles.error} /> : null}
      </section>

      {proyectos.isError ? <MensajeError error={proyectos.error} /> : null}
      {proyectos.data?.length === 0 ? (
        <Aviso tipo="nota">Todavía no hay proyectos. Cree uno o abra el modelo de prueba con plano.</Aviso>
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
      <Edificaciones />
      <Industrias />
    </div>
  );
}
