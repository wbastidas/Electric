import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/cliente";
import { fecha } from "../util";
import { MensajeError } from "./comunes";

interface Reciente {
  id: string;
  nombre: string;
  tipo: string;
  enlace: string;
  actualizado: string;
  detalle: string;
}

/** Tablero de inicio: crear por módulo y lo último que se trabajó. */
export function Inicio() {
  const consultas = useQueryClient();
  const proyectos = useQuery({ queryKey: ["proyectos"], queryFn: api.proyectos });
  const edificaciones = useQuery({ queryKey: ["edificaciones"], queryFn: api.edificaciones });
  const industrias = useQuery({ queryKey: ["industrias"], queryFn: api.industrias });
  const redes = useQuery({ queryKey: ["redes-mt"], queryFn: api.redesMT });

  const abrir = (hash: string) => {
    consultas.invalidateQueries();
    window.location.hash = hash;
  };
  const ejemploPlano = useMutation({ mutationFn: api.ejemploConPlano, onSuccess: (p) => abrir(`#/proyectos/${p.id}`) });
  const ejemploPisos = useMutation({ mutationFn: api.ejemploPisos, onSuccess: (e) => abrir(`#/edificaciones/${e.id}`) });

  // Las plantas de una vivienda de varios pisos se abren desde su vivienda.
  const recientes: Reciente[] = [
    ...(proyectos.data ?? []).filter((p) => !p.edificacion_id).map((p) => ({
      id: p.id,
      nombre: p.nombre,
      tipo: "Vivienda",
      enlace: `#/proyectos/${p.id}`,
      actualizado: p.actualizado,
      detalle: p.propietario || `revisión ${p.revision}`,
    })),
    ...(edificaciones.data ?? []).map((e) => ({
      id: e.id,
      nombre: e.nombre,
      tipo: "Varios pisos",
      enlace: `#/edificaciones/${e.id}`,
      actualizado: e.actualizado,
      detalle: `${e.pisos} plantas`,
    })),
    ...(industrias.data ?? []).map((i) => ({
      id: i.id,
      nombre: i.nombre,
      tipo: "Industria",
      enlace: `#/industrias/${i.id}`,
      actualizado: i.actualizado,
      detalle: `${i.maquinas} máquinas`,
    })),
    ...(redes.data ?? []).map((r) => ({
      id: r.id,
      nombre: r.nombre,
      tipo: "Red MT",
      enlace: `#/redes-mt/${r.id}`,
      actualizado: r.actualizado,
      detalle: `${r.postes} postes nuevos`,
    })),
  ]
    .sort((a, b) => b.actualizado.localeCompare(a.actualizado))
    .slice(0, 10);

  const cuenta = (n: number | undefined) => (n === undefined ? "…" : n);

  return (
    <div className="pagina">
      <div className="titulo-modulo">
        <h1>Inicio</h1>
        <p className="tenue">Proyectos eléctricos para presentar a CNEL EP. Todos los resultados son borradores.</p>
      </div>

      <div className="modulos">
        <a className="modulo" href="#/viviendas">
          <span className="modulo-cifra">
            {cuenta(proyectos.data?.filter((p) => !p.edificacion_id).length)}
          </span>
          <span className="modulo-nombre">Viviendas</span>
          <span className="tenue">Una planta, desde el plano DXF</span>
        </a>
        <a className="modulo" href="#/pisos">
          <span className="modulo-cifra">{cuenta(edificaciones.data?.length)}</span>
          <span className="modulo-nombre">Varios pisos</span>
          <span className="tenue">Un plano por planta y subtableros</span>
        </a>
        <a className="modulo" href="#/industrias">
          <span className="modulo-cifra">{cuenta(industrias.data?.length)}</span>
          <span className="modulo-nombre">Industrias</span>
          <span className="tenue">Cuadro de cargas, transformador y protecciones</span>
        </a>
        <a className="modulo pronto" href="#/no-residencial">
          <span className="modulo-cifra">—</span>
          <span className="modulo-nombre">No residencial</span>
          <span className="tenue">Locales, oficinas, edificios: en desarrollo</span>
        </a>
        <a className="modulo" href="#/redes-mt">
          <span className="modulo-cifra">{cuenta(redes.data?.length)}</span>
          <span className="modulo-nombre">Redes MT</span>
          <span className="tenue">Extensión de red sobre el mapa, estructuras y planos</span>
        </a>
      </div>

      <div className="columnas dos">
        <section className="tarjeta">
          <h2>Crear</h2>
          <div className="acciones-columna">
            <a className="boton primario" href="#/nuevo">Vivienda con el asistente</a>
            <a className="boton" href="#/pisos">Vivienda de varios pisos</a>
            <a className="boton" href="#/industrias">Industria</a>
            <a className="boton" href="#/redes-mt">Extensión de red MT</a>
          </div>
          <h3>Ejemplos</h3>
          <div className="acciones-columna">
            <button disabled={ejemploPlano.isPending} onClick={() => ejemploPlano.mutate()}>
              {ejemploPlano.isPending ? "Diseñando…" : "Vivienda de una planta con plano"}
            </button>
            <button disabled={ejemploPisos.isPending} onClick={() => ejemploPisos.mutate()}>
              {ejemploPisos.isPending ? "Diseñando las dos plantas…" : "Vivienda de dos plantas"}
            </button>
          </div>
          {ejemploPlano.isError ? <MensajeError error={ejemploPlano.error} /> : null}
          {ejemploPisos.isError ? <MensajeError error={ejemploPisos.error} /> : null}
        </section>

        <section className="tarjeta">
          <h2>Recientes</h2>
          {recientes.length ? (
            <ul className="recientes">
              {recientes.map((r) => (
                <li key={`${r.tipo}-${r.id}`}>
                  <a href={r.enlace}>{r.nombre}</a>
                  <span className="etiqueta-tipo">{r.tipo}</span>
                  <span className="tenue">
                    {r.detalle} · {fecha(r.actualizado)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="tenue">Todavía no hay proyectos. Cree uno o abra un ejemplo.</p>
          )}
        </section>
      </div>
    </div>
  );
}
