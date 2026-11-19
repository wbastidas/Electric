import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { api, type BorradorNuevo } from "../api/cliente";
import { fecha, viviendaDeEjemplo } from "../util";
import { Aviso, Campo, MensajeError } from "./comunes";

const abrir = (id: string) => {
  window.location.hash = `#/proyectos/${id}`;
};

export function Edificaciones() {
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

export function Industrias() {
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

export function Viviendas() {
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
  // Las plantas de una vivienda de varios pisos se listan en su vivienda.
  const sueltas = proyectos.data?.filter((p) => !p.edificacion_id);

  const alEnviar = (evento: FormEvent) => {
    evento.preventDefault();
    if (!perfil || !nombre.trim()) return;
    crear.mutate({ nombre: nombre.trim(), perfil: { id: perfil.id, version: perfil.version } });
  };

  return (
    <div className="pagina">
      <div className="titulo-modulo">
        <h1>Viviendas</h1>
        <p className="tenue">Vivienda unifamiliar de una planta: desde el plano del arquitecto o por formulario.</p>
      </div>

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
      {sueltas?.length === 0 ? (
        <Aviso tipo="nota">Todavía no hay proyectos. Cree uno o abra el modelo de prueba con plano.</Aviso>
      ) : null}
      {sueltas?.length ? (
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
              {sueltas.map((p) => (
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

export function PaginaPisos() {
  return (
    <div className="pagina">
      <div className="titulo-modulo">
        <h1>Viviendas de varios pisos</h1>
        <p className="tenue">Un plano por planta, tablero principal en la planta baja y un subtablero por piso.</p>
      </div>
      <Edificaciones />
    </div>
  );
}

export function PaginaIndustrias() {
  return (
    <div className="pagina">
      <div className="titulo-modulo">
        <h1>Industrias</h1>
        <p className="tenue">
          Cuadro de cargas, factor de potencia, transformador existente o particular, cortocircuito, protecciones y
          unifilar.
        </p>
      </div>
      <Industrias />
    </div>
  );
}

export function PaginaRedesMT() {
  const consultas = useQueryClient();
  const redes = useQuery({ queryKey: ["redes-mt"], queryFn: api.redesMT });
  const [nombre, setNombre] = useState("");
  const abrir = (id: string) => {
    consultas.invalidateQueries({ queryKey: ["redes-mt"] });
    window.location.hash = `#/redes-mt/${id}`;
  };
  const crear = useMutation({ mutationFn: (n: string) => api.crearRedMT(n), onSuccess: (r) => abrir(r.id) });
  const ejemplo = useMutation({ mutationFn: api.ejemploRedMT, onSuccess: (r) => abrir(r.id) });
  const borrar = useMutation({
    mutationFn: api.borrarRedMT,
    onSuccess: () => consultas.invalidateQueries({ queryKey: ["redes-mt"] }),
  });
  return (
    <div className="pagina">
      <div className="titulo-modulo">
        <h1>Redes de media tensión</h1>
        <p className="tenue">
          Extensión de red: trazado sobre el mapa o por coordenadas, estructuras, caída de tensión, cortocircuito,
          protección, planimetría DXF, unifilar y KML. Cámaras, urbanizaciones y subestaciones vienen después.
        </p>
      </div>
      <section className="tarjeta">
        <h2>Nueva extensión de red</h2>
        <form
          className="fila-formulario"
          onSubmit={(e) => {
            e.preventDefault();
            if (nombre.trim()) crear.mutate(nombre.trim());
          }}
        >
          <Campo etiqueta="Nombre">
            <input value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Extensión barrio Las Palmas" />
          </Campo>
          <button className="primario" type="submit" disabled={!nombre.trim() || crear.isPending}>
            Nueva extensión de red
          </button>
          <button type="button" disabled={ejemplo.isPending} onClick={() => ejemplo.mutate()}>
            Abrir el ejemplo
          </button>
        </form>
        {crear.isError ? <MensajeError error={crear.error} /> : null}
        {ejemplo.isError ? <MensajeError error={ejemplo.error} /> : null}
        {redes.data?.length ? (
          <div className="tabla-ancha">
            <table>
              <thead>
                <tr>
                  <th>Red</th>
                  <th>Solicitante</th>
                  <th>Postes nuevos</th>
                  <th>Último cambio</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {redes.data.map((r) => (
                  <tr key={r.id}>
                    <td><a href={`#/redes-mt/${r.id}`}>{r.nombre}</a></td>
                    <td>{r.propietario || "—"}</td>
                    <td>{r.postes}</td>
                    <td>{fecha(r.actualizado)}</td>
                    <td className="derecha">
                      <button
                        className="discreto"
                        onClick={() => {
                          if (window.confirm(`¿Borrar "${r.nombre}"? No se puede deshacer.`)) borrar.mutate(r.id);
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
    </div>
  );
}

const TIPOS_NR: Record<string, string> = {
  departamentos: "Edificio de departamentos",
  locales_oficinas: "Locales y oficinas",
  comercial: "Comercial grande",
};

export function PaginaNoResidencial() {
  const consultas = useQueryClient();
  const edificios = useQuery({ queryKey: ["edificios"], queryFn: api.edificios });
  const [nombre, setNombre] = useState("");
  const [tipo, setTipo] = useState<"departamentos" | "locales_oficinas" | "comercial">("departamentos");
  const abrirEdificio = (id: string) => {
    consultas.invalidateQueries({ queryKey: ["edificios"] });
    window.location.hash = `#/edificios/${id}/unidades`;
  };
  const crear = useMutation({
    mutationFn: () =>
      api.crearEdificio({
        nombre: nombre.trim(),
        tipo,
        respaldo: tipo === "comercial" ? "total" : "ninguno",
      }),
    onSuccess: (r) => abrirEdificio(r.id),
  });
  const ejemplo = useMutation({ mutationFn: api.ejemploEdificio, onSuccess: (r) => abrirEdificio(r.id) });
  const borrar = useMutation({
    mutationFn: api.borrarEdificio,
    onSuccess: () => consultas.invalidateQueries({ queryKey: ["edificios"] }),
  });
  return (
    <div className="pagina">
      <div className="titulo-modulo">
        <h1>Proyectos no residenciales</h1>
        <p className="tenue">
          Edificios de departamentos, locales y oficinas, y comercios grandes: demanda con factor de coincidencia, nivel de
          servicio, transformador o cámara, centro de medición, alimentadores por unidad, generador con transferencia y
          unifilar. Las naves industriales se diseñan en <a href="#/industrias">Industrias</a>.
        </p>
      </div>
      <section className="tarjeta">
        <h2>Nuevo proyecto</h2>
        <form
          className="fila-formulario"
          onSubmit={(e) => {
            e.preventDefault();
            if (nombre.trim()) crear.mutate();
          }}
        >
          <Campo etiqueta="Nombre">
            <input value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Edificio Las Acacias" />
          </Campo>
          <Campo etiqueta="Tipo">
            <select value={tipo} onChange={(e) => setTipo(e.target.value as typeof tipo)}>
              {Object.entries(TIPOS_NR).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </Campo>
          <button className="primario" type="submit" disabled={!nombre.trim() || crear.isPending}>
            Crear
          </button>
          <button type="button" disabled={ejemplo.isPending} onClick={() => ejemplo.mutate()}>
            Abrir el ejemplo de departamentos
          </button>
        </form>
        {crear.isError ? <MensajeError error={crear.error} /> : null}
        {ejemplo.isError ? <MensajeError error={ejemplo.error} /> : null}
        {edificios.data?.length ? (
          <div className="tabla-ancha">
            <table>
              <thead>
                <tr><th>Proyecto</th><th>Tipo</th><th>Propietario</th><th>Unidades</th><th>Último cambio</th><th /></tr>
              </thead>
              <tbody>
                {edificios.data.map((r) => (
                  <tr key={r.id}>
                    <td><a href={`#/edificios/${r.id}`}>{r.nombre}</a></td>
                    <td>{TIPOS_NR[r.tipo] ?? r.tipo}</td>
                    <td>{r.propietario || "—"}</td>
                    <td>{r.unidades}</td>
                    <td>{fecha(r.actualizado)}</td>
                    <td className="derecha">
                      <button
                        className="discreto"
                        onClick={() => {
                          if (window.confirm(`¿Borrar "${r.nombre}"? No se puede deshacer.`)) borrar.mutate(r.id);
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
    </div>
  );
}
