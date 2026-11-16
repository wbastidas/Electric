import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type Borrador, ErrorApi, type ProyectoDetalle } from "../api/cliente";
import { Bitacora } from "./Bitacora";
import { Calculos } from "./Calculos";
import { Circuitos } from "./Circuitos";
import { Aviso, MensajeError } from "./comunes";
import { Datos } from "./Datos";
import { Plano } from "./Plano";

const PESTANAS = ["Datos", "Plano", "Circuitos", "Cálculos", "Bitácora"] as const;
type Pestana = (typeof PESTANAS)[number];

export function Editor({ id }: { id: string }) {
  const consultas = useQueryClient();
  const proyecto = useQuery({ queryKey: ["proyecto", id], queryFn: () => api.proyecto(id) });
  const perfiles = useQuery({ queryKey: ["perfiles"], queryFn: api.perfiles });
  const [datos, setDatos] = useState<Borrador | null>(null);
  const [revision, setRevision] = useState(0);
  const [sinGuardar, setSinGuardar] = useState(false);
  const [pestana, setPestana] = useState<Pestana | null>(null);

  useEffect(() => {
    if (proyecto.data && !sinGuardar) {
      setDatos(proyecto.data.datos);
      setRevision(proyecto.data.revision);
    }
    // Solo al llegar datos del servidor; los cambios locales no deben pisarse.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proyecto.data]);

  useEffect(() => {
    const avisar = (evento: BeforeUnloadEvent) => {
      if (sinGuardar) evento.preventDefault();
    };
    window.addEventListener("beforeunload", avisar);
    return () => window.removeEventListener("beforeunload", avisar);
  }, [sinGuardar]);

  /** El servidor devolvió una revisión nueva: pasa a ser la que se edita. */
  const adoptar = (guardado: ProyectoDetalle) => {
    setSinGuardar(false);
    setDatos(guardado.datos);
    setRevision(guardado.revision);
    consultas.setQueryData(["proyecto", id], guardado);
    consultas.invalidateQueries({ queryKey: ["calculos", id] });
    consultas.invalidateQueries({ queryKey: ["bitacora", id] });
    consultas.invalidateQueries({ queryKey: ["proyectos"] });
  };

  const guardar = useMutation({
    mutationFn: (nuevo: Borrador) => api.guardar(id, revision, nuevo),
    onSuccess: adoptar,
  });

  if (proyecto.isError) return <div className="pagina"><MensajeError error={proyecto.error} /></div>;
  const perfil = perfiles.data?.find((p) => p.id === datos?.perfil.id);
  if (!datos || !perfil) return <div className="pagina">Cargando…</div>;

  const cambiar = (nuevo: Borrador) => {
    setDatos(nuevo);
    setSinGuardar(true);
  };
  // Un proyecto con plano abre en el plano; uno sin plano, en los datos.
  const activa: Pestana = pestana ?? (datos.plano ? "Plano" : "Datos");
  const conflicto = guardar.error instanceof ErrorApi && guardar.error.estado === 409;

  return (
    <div className="pagina">
      <div className="cabecera">
        <div>
          <a className="volver" href="#/">
            ← Proyectos
          </a>
          <h1>{datos.nombre}</h1>
          <p className="tenue">
            {perfil.nombre} · versión {perfil.version} · revisión {revision}
          </p>
        </div>
        <div className="acciones">
          <span className="tenue" aria-live="polite">
            {sinGuardar ? "Cambios sin guardar" : "Todo guardado"}
          </span>
          <button
            className="primario"
            disabled={!sinGuardar || guardar.isPending}
            onClick={() => guardar.mutate(datos)}
          >
            {guardar.isPending ? "Guardando…" : "Guardar"}
          </button>
        </div>
      </div>

      {guardar.isError ? <MensajeError error={guardar.error} /> : null}
      {conflicto ? (
        <button
          onClick={() => {
            setSinGuardar(false);
            guardar.reset();
            proyecto.refetch();
          }}
        >
          Descartar mis cambios y recargar
        </button>
      ) : null}

      <nav className="pestanas" role="tablist">
        {PESTANAS.map((p) => (
          <button
            key={p}
            role="tab"
            aria-selected={p === activa}
            className={p === activa ? "activa" : ""}
            onClick={() => setPestana(p)}
          >
            {p}
          </button>
        ))}
      </nav>

      {activa === "Datos" ? <Datos datos={datos} perfil={perfil} cambiar={cambiar} /> : null}
      {activa === "Plano" ? (
        <Plano
          id={id}
          revision={revision}
          datos={datos}
          perfil={perfil}
          sinGuardar={sinGuardar}
          cambiar={cambiar}
          adoptar={adoptar}
        />
      ) : null}
      {activa === "Circuitos" ? <Circuitos datos={datos} perfil={perfil} cambiar={cambiar} /> : null}
      {activa === "Cálculos" ? (
        <>
          {sinGuardar ? (
            <Aviso tipo="alerta">
              Estos resultados son de la revisión {revision}. Guarde los cambios para recalcular.
            </Aviso>
          ) : null}
          <Calculos id={id} revision={revision} />
        </>
      ) : null}
      {activa === "Bitácora" ? <Bitacora id={id} /> : null}
    </div>
  );
}
