import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useState } from "react";
import { api, type DatosEdificacion, type EdificacionDetalle } from "../api/cliente";
import { Aviso, Campo, MensajeError } from "./comunes";

const num = (v: number, d = 1) => v.toLocaleString("es-EC", { maximumFractionDigits: d });

const ESTADO_PISO: Record<string, string> = {
  listo: "Diseñada",
  sin_plano: "Sin plano",
  incompleto: "Incompleta",
};

/** Vivienda de varios pisos: un plano por planta, tablero principal y subtableros. */
export function Edificacion({ id }: { id: string }) {
  const consultas = useQueryClient();
  const edificacion = useQuery({ queryKey: ["edificacion", id], queryFn: () => api.edificacion(id) });
  const perfiles = useQuery({ queryKey: ["perfiles"], queryFn: api.perfiles });
  const marca = edificacion.data ? `${edificacion.data.actualizado}-${edificacion.data.pisos.length}` : "";
  const calculo = useQuery({
    queryKey: ["calculo-edificacion", id, marca],
    queryFn: () => api.calculoEdificacion(id),
    enabled: !!edificacion.data,
  });
  const [datos, setDatos] = useState<DatosEdificacion | null>(null);
  const [cambios, setCambios] = useState(false);

  useEffect(() => {
    if (edificacion.data && !cambios) setDatos(edificacion.data.datos);
  }, [edificacion.data, cambios]);

  const alActualizar = (detalle: EdificacionDetalle) => {
    consultas.setQueryData(["edificacion", id], detalle);
    consultas.invalidateQueries({ queryKey: ["edificaciones"] });
    consultas.invalidateQueries({ queryKey: ["calculo-edificacion", id] });
    setCambios(false);
    setDatos(detalle.datos);
  };
  const guardar = useMutation({
    mutationFn: () => api.guardarEdificacion(id, datos as DatosEdificacion),
    onSuccess: alActualizar,
  });

  if (edificacion.isError) return <div className="pagina"><MensajeError error={edificacion.error} /></div>;
  if (!edificacion.data || !datos) return <div className="pagina">Cargando…</div>;

  const cambiar = (parcial: Partial<DatosEdificacion>) => {
    setDatos({ ...datos, ...parcial });
    setCambios(true);
  };
  const perfil = perfiles.data?.find((p) => p.id === datos.perfil.id);
  const pisos = edificacion.data.pisos;
  const siguiente = pisos.length ? Math.max(...pisos.map((p) => p.nivel)) + 1 : 0;
  const c = calculo.data;

  return (
    <div className="pagina">
      <a className="volver" href="#/">
        ← Proyectos
      </a>
      <div className="titulo-proyecto">
        <h1>{edificacion.data.datos.nombre}</h1>
        <div className="acciones">
          {cambios ? <span className="tenue">Cambios sin guardar</span> : null}
          <button className="primario" disabled={!cambios || guardar.isPending} onClick={() => guardar.mutate()}>
            {guardar.isPending ? "Guardando…" : "Guardar y calcular"}
          </button>
        </div>
      </div>
      {guardar.isError ? <MensajeError error={guardar.error} /> : null}

      <div className="columnas">
        <section className="tarjeta">
          <h2>Datos de la vivienda</h2>
          <div className="rejilla">
            <Campo etiqueta="Nombre">
              <input value={datos.nombre} onChange={(e) => cambiar({ nombre: e.target.value })} />
            </Campo>
            <Campo etiqueta="Propietario">
              <input value={datos.propietario} onChange={(e) => cambiar({ propietario: e.target.value })} />
            </Campo>
            <Campo etiqueta="Medidor → tablero principal (m)">
              <input
                inputMode="decimal"
                value={String(datos.medidor_m)}
                onChange={(e) => cambiar({ medidor_m: e.target.value })}
              />
            </Campo>
            <Campo etiqueta="Altura de piso a piso (m)" ayuda="Tramo vertical de cada alimentador.">
              <input
                inputMode="decimal"
                value={String(datos.altura_piso_m)}
                onChange={(e) => cambiar({ altura_piso_m: e.target.value })}
              />
            </Campo>
            <Campo etiqueta="Zona climática" ayuda="Se aplica a las plantas que cargue después.">
              <select
                value={datos.preferencias.zona_climatica ?? ""}
                onChange={(e) =>
                  cambiar({ preferencias: { ...datos.preferencias, zona_climatica: e.target.value || null } })
                }
              >
                <option value="">Sin zona</option>
                {perfil?.zonas.map((z) => (
                  <option key={z.id} value={z.id}>
                    {z.nombre}
                  </option>
                ))}
              </select>
            </Campo>
          </div>
        </section>

        <section className="tarjeta">
          <h2>Plantas</h2>
          {pisos.length ? (
            <div className="tabla-ancha">
              <table>
                <thead>
                  <tr>
                    <th>Nivel</th>
                    <th>Planta</th>
                    <th className="derecha">Ambientes</th>
                    <th className="derecha">Circuitos</th>
                    <th>Estado</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {pisos.map((p) => (
                    <tr key={p.proyecto_id}>
                      <td>{p.codigo}</td>
                      <td>{p.nombre}</td>
                      <td className="derecha">{p.ambientes}</td>
                      <td className="derecha">{p.circuitos}</td>
                      <td>{ESTADO_PISO[p.estado]}</td>
                      <td className="derecha">
                        <a href={`#/proyectos/${p.proyecto_id}`}>Abrir y editar</a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="tenue">Todavía no hay plantas. Cargue un plano DXF por planta, empezando por la baja.</p>
          )}
          <NuevaPlanta id={id} siguiente={siguiente} especiales={perfil?.cargas.filter((x) => x.especial) ?? []} />
        </section>
      </div>

      {calculo.isError ? <MensajeError error={calculo.error} /> : null}
      {c?.estado === "incompleto" ? <Aviso tipo="nota">{c.pendientes.join(" ")}</Aviso> : null}
      {c?.estado === "listo" ? (
        <>
          <section className="tarjeta">
            <h2>Vivienda completa</h2>
            <div className="resumen">
              <div className="dato">
                <span className="etiqueta">Área</span>
                <span className="valor">{num(c.area_m2)} m²</span>
              </div>
              <div className="dato">
                <span className="etiqueta">Demanda máxima</span>
                <span className="valor">{num(c.demanda_kw, 2)} kW</span>
              </div>
              <div className="dato">
                <span className="etiqueta">Clasificación CNEL</span>
                <span className="valor">{c.clasificacion}</span>
              </div>
              <div className="dato">
                <span className="etiqueta">Breaker principal</span>
                <span className="valor">{num(c.principal_a, 0)} A</span>
              </div>
              <div className="dato">
                <span className="etiqueta">Alimentador del medidor</span>
                <span className="valor">
                  {c.alimentador} · ΔV {num(c.caida_pct, 2)} %
                </span>
              </div>
              <div className="dato">
                <span className="etiqueta">Medidor</span>
                <span className="valor">{c.medidor}</span>
              </div>
            </div>
            <p className="tenue">
              La demanda se calcula sobre el área y la carga de toda la vivienda, no sumando la de cada planta.
            </p>
          </section>

          <section className="tarjeta">
            <h2>Tableros</h2>
            <div className="tabla-ancha">
              <table>
                <thead>
                  <tr>
                    <th>Tablero</th>
                    <th>Planta</th>
                    <th className="derecha">Demanda</th>
                    <th className="derecha">Alimentador</th>
                    <th>Recorrido</th>
                    <th className="derecha">Breaker</th>
                    <th>Conductor</th>
                    <th className="derecha">ΔV</th>
                  </tr>
                </thead>
                <tbody>
                  <tr className="principal">
                    <td>TP (principal)</td>
                    <td>{c.piso_principal}</td>
                    <td className="derecha">{num(c.demanda_principal_kw, 2)} kW</td>
                    <td colSpan={5} className="tenue">
                      Alimentado desde el medidor; también alimenta los subtableros.
                    </td>
                  </tr>
                  {c.subtableros.map((s) => (
                    <tr key={s.tablero}>
                      <td>
                        <a href={`#/proyectos/${s.proyecto_id}`}>{s.tablero}</a>
                      </td>
                      <td>{s.piso}</td>
                      <td className="derecha">{num(s.demanda_kw, 2)} kW</td>
                      <td className="derecha">{num(s.longitud_m)} m</td>
                      <td className="tenue">
                        {num(s.vertical_m)} m vertical + {num(s.horizontal_m)} m en planta
                      </td>
                      <td className="derecha">{num(s.breaker_a, 0)} A</td>
                      <td>{s.conductor}</td>
                      <td className="derecha">{num(s.caida_pct, 2)} %</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {c.avisos.length ? (
              <Aviso tipo="alerta">
                <ul>
                  {c.avisos.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              </Aviso>
            ) : null}
          </section>

          <section className="tarjeta">
            <h2>Diagrama unifilar</h2>
            <div className="acciones izquierda">
              <a className="boton" href={api.urlUnifilarEdificacion(id, "dxf", marca)}>
                Descargar DXF
              </a>
              <a className="boton" href={api.urlUnifilarEdificacion(id, "pdf", marca)} target="_blank" rel="noreferrer">
                Abrir PDF
              </a>
            </div>
            <img
              className="unifilar"
              src={api.urlUnifilarEdificacion(id, "png", marca)}
              alt="Diagrama unifilar de la vivienda"
            />
            <p className="tenue">{c.aviso}</p>
          </section>
        </>
      ) : null}
    </div>
  );
}

function NuevaPlanta({
  id,
  siguiente,
  especiales,
}: {
  id: string;
  siguiente: number;
  especiales: { tipo: string }[];
}) {
  const consultas = useQueryClient();
  const [archivo, setArchivo] = useState<File | null>(null);
  const [nivel, setNivel] = useState(siguiente);
  const [nombre, setNombre] = useState("");
  const [equipos, setEquipos] = useState<string[]>([]);
  useEffect(() => setNivel(siguiente), [siguiente]);

  const subir = useMutation({
    mutationFn: () =>
      api.subirPiso(
        id,
        archivo as File,
        nivel,
        nombre.trim() || (nivel === 0 ? "Planta baja" : `Piso ${nivel}`),
        equipos,
      ),
    onSuccess: (detalle) => {
      consultas.setQueryData(["edificacion", id], detalle);
      consultas.invalidateQueries({ queryKey: ["edificaciones"] });
      setArchivo(null);
      setNombre("");
      setEquipos([]);
    },
  });

  const alEnviar = (e: FormEvent) => {
    e.preventDefault();
    if (archivo) subir.mutate();
  };

  return (
    <form className="nueva-planta" onSubmit={alEnviar}>
      <h3>Agregar una planta</h3>
      <div className="rejilla">
        <Campo etiqueta="Plano DXF de la planta">
          <input type="file" accept=".dxf" onChange={(e) => setArchivo(e.target.files?.[0] ?? null)} />
        </Campo>
        <Campo etiqueta="Nivel" ayuda="0 planta baja, 1 primer piso alto, −1 subsuelo.">
          <input type="number" min={-5} max={40} value={nivel} onChange={(e) => setNivel(Number(e.target.value))} />
        </Campo>
        <Campo etiqueta="Nombre">
          <input
            value={nombre}
            placeholder={nivel === 0 ? "Planta baja" : `Piso ${nivel}`}
            onChange={(e) => setNombre(e.target.value)}
          />
        </Campo>
      </div>
      <fieldset className="equipos">
        <legend>Equipos de esta planta</legend>
        {especiales.map((c) => (
          <label key={c.tipo} className="casilla">
            <input
              type="checkbox"
              checked={equipos.includes(c.tipo)}
              onChange={(e) =>
                setEquipos(e.target.checked ? [...equipos, c.tipo] : equipos.filter((x) => x !== c.tipo))
              }
            />
            {c.tipo.replaceAll("_", " ")}
          </label>
        ))}
      </fieldset>
      <div className="acciones izquierda">
        <button className="primario" type="submit" disabled={!archivo || subir.isPending}>
          {subir.isPending ? "Leyendo y diseñando…" : "Cargar y diseñar la planta"}
        </button>
        <span className="tenue">Los planos de todas las plantas deben estar dibujados con las mismas coordenadas.</span>
      </div>
      {subir.isError ? <MensajeError error={subir.error} /> : null}
    </form>
  );
}
