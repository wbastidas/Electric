import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type BorradorSubestacion, type CalculoSubestacion, type Resultado } from "../api/cliente";
import { Detalle } from "./Calculos";
import { Aviso, Campo, elegirPestana, MensajeError, type Pestana, Pestanas } from "./comunes";

const num = (v: number | string | null | undefined, d = 1) =>
  v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("es-EC", { maximumFractionDigits: d });

/** Subestación de cliente 69/13,8 kV. */
export function Subestacion({ id, pestana }: { id: string; pestana?: string }) {
  const consultas = useQueryClient();
  const se = useQuery({ queryKey: ["subestacion", id], queryFn: () => api.subestacion(id) });
  const revision = se.data?.revision ?? 0;
  const calculo = useQuery({
    queryKey: ["calculo-subestacion", id, revision],
    queryFn: () => api.calculoSubestacion(id),
    enabled: revision > 0,
  });
  const [datos, setDatos] = useState<BorradorSubestacion | null>(null);
  const [cambios, setCambios] = useState(false);
  const [seleccion, setSeleccion] = useState<Resultado | null>(null);
  useEffect(() => {
    if (se.data && !cambios) setDatos(se.data.datos);
  }, [se.data, cambios]);
  const guardar = useMutation({
    mutationFn: () => api.guardarSubestacion(id, revision, datos as BorradorSubestacion),
    onSuccess: (d) => {
      consultas.setQueryData(["subestacion", id], d);
      consultas.invalidateQueries({ queryKey: ["subestaciones"] });
      setCambios(false);
      setDatos(d.datos);
    },
  });
  if (se.isError) return <div className="pagina"><MensajeError error={se.error} /></div>;
  if (!datos) return <div className="pagina">Cargando…</div>;
  const cambiar = (p: Partial<BorradorSubestacion>) => {
    setDatos({ ...datos, ...p });
    setCambios(true);
  };
  const vacio = (v: string) => (v.trim() === "" ? null : v);
  const c = calculo.data?.estado === "listo" ? calculo.data : null;
  const pestanas: Pestana[] = [
    { id: "datos", titulo: "Datos" },
    { id: "equipos", titulo: "Transformador y equipos", marca: c?.equipos.length ?? null },
    {
      id: "malla",
      titulo: "Malla de tierra",
      marca: c?.malla ? (c.malla.cumple && c.malla.resistencia_cumple ? "✓" : "✗") : null,
      alerta: c?.malla ? !(c.malla.cumple && c.malla.resistencia_cumple) : false,
    },
    { id: "unifilar", titulo: "Unifilar" },
    { id: "memoria", titulo: "Memoria de cálculo", marca: c?.resultados.length ?? null },
  ];
  const activa = elegirPestana(pestana ?? (datos.demanda_mva ? "equipos" : "datos"), pestanas);
  const plano = (p: "unifilar" | "malla", titulo: string) =>
    c ? (
      <section className="tarjeta">
        <h2>{titulo}</h2>
        <div className="acciones izquierda">
          <a className="boton" href={api.urlPlanoSubestacion(id, p, "dxf", c.revision)}>Descargar DXF</a>
          <a className="boton" href={api.urlPlanoSubestacion(id, p, "pdf", c.revision)} target="_blank" rel="noreferrer">Abrir PDF</a>
        </div>
        <img className="unifilar" src={api.urlPlanoSubestacion(id, p, "png", c.revision)} alt={titulo} />
        <p className="tenue">{c.aviso}</p>
      </section>
    ) : null;

  return (
    <div className="pagina">
      <p className="miga"><a href="#/redes-mt">Redes MT</a> › {se.data?.datos.nombre}</p>
      <div className="titulo-proyecto">
        <h1>{se.data?.datos.nombre}</h1>
        <div className="acciones">
          <span className="chip-tipo">Subestación 69/13,8 kV</span>
          {cambios ? <span className="tenue">Cambios sin guardar</span> : null}
          <button className="primario" disabled={!cambios || guardar.isPending} onClick={() => guardar.mutate()}>
            {guardar.isPending ? "Guardando…" : "Guardar y calcular"}
          </button>
        </div>
      </div>
      {guardar.isError ? <MensajeError error={guardar.error} /> : null}
      {c ? (
        <div className="resumen compacto franja">
          <div className="dato"><span className="etiqueta">Transformador</span><span className="valor">{c.transformador ?? "—"}</span></div>
          <div className="dato"><span className="etiqueta">In AT / MT</span><span className="valor">{num(c.corriente_at_a)} / {num(c.corriente_mt_a, 0)} A</span></div>
          <div className="dato"><span className="etiqueta">Icc 69 kV</span><span className="valor">{num(c.icc_at_ka, 2)} kA</span></div>
          <div className="dato"><span className="etiqueta">Icc 13,8 kV</span><span className="valor">{num(c.icc_mt_ka, 2)} kA</span></div>
          <div className="dato"><span className="etiqueta">Malla</span><span className="valor">{c.malla ? `${num(c.malla.resistencia_ohm, 2)} Ω` : "—"}</span></div>
        </div>
      ) : null}
      {c?.scc_supuesta ? (
        <Aviso tipo="nota">Scc en 69 kV de {num(c.scc_at_mva, 0)} MVA supuesta, por verificar: escriba el dato de la factibilidad de CNEL en «Datos».</Aviso>
      ) : null}
      <Pestanas items={pestanas} activa={activa} base={`#/subestaciones/${id}`} />

      {activa === "datos" ? (
        <div className="columnas dos">
          <section className="tarjeta">
            <h2>Carga y red</h2>
            <div className="rejilla">
              <Campo etiqueta="Nombre"><input value={datos.nombre} onChange={(e) => cambiar({ nombre: e.target.value })} /></Campo>
              <Campo etiqueta="Propietario"><input value={datos.propietario ?? ""} onChange={(e) => cambiar({ propietario: e.target.value })} /></Campo>
              <Campo etiqueta="Demanda máxima (MVA)">
                <input inputMode="decimal" value={datos.demanda_mva ?? ""} onChange={(e) => cambiar({ demanda_mva: vacio(e.target.value) })} />
              </Campo>
              <Campo etiqueta="Alimentadores de 13,8 kV">
                <input inputMode="numeric" value={datos.alimentadores ?? 4}
                  onChange={(e) => cambiar({ alimentadores: Math.min(16, Math.max(1, Number(e.target.value) || 1)) })} />
              </Campo>
              <Campo etiqueta="Scc en 69 kV (MVA)" ayuda="De la factibilidad de CNEL; vacío: 500 MVA por verificar.">
                <input inputMode="decimal" value={datos.scc_at_mva ?? ""} onChange={(e) => cambiar({ scc_at_mva: vacio(e.target.value) })} />
              </Campo>
              <Campo etiqueta="Tensiones (kV)" ayuda="Vacío: 69 / 13,8 kV.">
                <div className="fila-formulario">
                  <input inputMode="decimal" placeholder="69" value={datos.tension_at_kv ?? ""} onChange={(e) => cambiar({ tension_at_kv: vacio(e.target.value) })} />
                  <input inputMode="decimal" placeholder="13.8" value={datos.tension_mt_kv ?? ""} onChange={(e) => cambiar({ tension_mt_kv: vacio(e.target.value) })} />
                </div>
              </Campo>
            </div>
          </section>
          <section className="tarjeta">
            <h2>Malla de tierra</h2>
            <div className="rejilla">
              <Campo etiqueta="Largo del patio (m)"><input inputMode="decimal" value={datos.largo_malla_m ?? "40"} onChange={(e) => cambiar({ largo_malla_m: e.target.value })} /></Campo>
              <Campo etiqueta="Ancho del patio (m)"><input inputMode="decimal" value={datos.ancho_malla_m ?? "30"} onChange={(e) => cambiar({ ancho_malla_m: e.target.value })} /></Campo>
              <Campo etiqueta="Resistividad del suelo (Ω·m)" ayuda="Medida en sitio; vacío: 100.">
                <input inputMode="decimal" value={datos.resistividad_ohm_m ?? ""} onChange={(e) => cambiar({ resistividad_ohm_m: vacio(e.target.value) })} />
              </Campo>
              <Campo etiqueta="Duración de la falla (s)" ayuda="Vacío: 0,5 s.">
                <input inputMode="decimal" value={datos.tiempo_falla_s ?? ""} onChange={(e) => cambiar({ tiempo_falla_s: vacio(e.target.value) })} />
              </Campo>
            </div>
          </section>
        </div>
      ) : null}
      {calculo.data?.estado === "incompleto" && activa !== "datos" ? <Aviso tipo="nota">{calculo.data.pendientes.join(" ")}</Aviso> : null}
      {c && activa === "equipos" ? <Equipos c={c} /> : null}
      {c && activa === "malla" ? <Malla c={c} /> : null}
      {c && activa === "malla" ? plano("malla", "Plano de la malla") : null}
      {activa === "unifilar" ? plano("unifilar", "Diagrama unifilar") : null}
      {c && activa === "memoria" ? (
        <section className="tarjeta">
          <h2>Memoria de cálculo</h2>
          <div className="tabla-ancha">
            <table>
              <thead><tr><th>Cálculo</th><th>Resultado</th></tr></thead>
              <tbody>
                {c.resultados.map((r) => (
                  <tr key={r.id} className="seleccionable" onClick={() => setSeleccion(r)}>
                    <td>{r.nombre}</td><td>{r.texto}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
      {seleccion ? <Detalle resultado={seleccion} cerrar={() => setSeleccion(null)} /> : null}
    </div>
  );
}

function Equipos({ c }: { c: CalculoSubestacion }) {
  return (
    <>
      <section className="tarjeta">
        <h2>Transformador, corrientes y cortocircuito</h2>
        <p>
          Transformador de <strong>{c.transformador ?? "—"}</strong>, Z {num(c.z_pct, 1)} %. In = {num(c.corriente_at_a)} A en{" "}
          {num(c.tension_at_kv)} kV y {num(c.corriente_mt_a)} A en {num(c.tension_mt_kv)} kV; cada alimentador lleva{" "}
          {num(c.corriente_alimentador_a, 0)} A. Cortocircuito trifásico: {num(c.icc_at_ka, 2)} kA en AT y {num(c.icc_mt_ka, 2)} kA en
          barras de MT.
        </p>
        <div className="tabla-ancha">
          <table>
            <thead><tr><th>Equipo</th><th>Especificación</th></tr></thead>
            <tbody>
              {c.equipos.map((e) => (
                <tr key={e.nombre}><td>{e.nombre}</td><td>{e.especificacion}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {c.avisos.length ? <Aviso tipo="alerta"><ul>{c.avisos.map((a) => <li key={a}>{a}</li>)}</ul></Aviso> : null}
    </>
  );
}

function Malla({ c }: { c: CalculoSubestacion }) {
  const m = c.malla;
  if (!m) return null;
  const fila = (nombre: string, valor: number, limite: number, cumple: boolean, u = "V") => (
    <tr className={cumple ? undefined : "falla"}>
      <td>{nombre}</td><td className="num">{num(valor, u === "Ω" ? 2 : 0)} {u}</td>
      <td className="num">{num(limite, u === "Ω" ? 1 : 0)} {u}</td><td>{cumple ? "✓ cumple" : "✗ no cumple"}</td>
    </tr>
  );
  return (
    <section className={`tarjeta decision ${m.cumple && m.resistencia_cumple ? "existente" : "particular"}`}>
      <h2>Malla de puesta a tierra (IEEE 80)</h2>
      <p>
        {num(m.largo_m, 0)} × {num(m.ancho_m, 0)} m con cuadrícula de {num(m.separacion_m, 0)} m ({m.conductores_x} × {m.conductores_y}{" "}
        conductores, {num(m.longitud_conductor_m, 0)} m de cobre {m.calibre}) y {m.varillas} varillas en el perímetro. Calibre mínimo por
        corriente de falla: {num(m.calibre_minimo_kcmil, 0)} kcmil. Corriente por la malla {num(m.corriente_malla_a, 0)} A, GPR{" "}
        {num(m.gpr_v, 0)} V.
      </p>
      <table>
        <thead><tr><th>Comprobación</th><th className="num">Calculado</th><th className="num">Límite</th><th /></tr></thead>
        <tbody>
          {fila("Tensión de malla (contacto)", m.tension_malla_v, m.contacto_tolerable_v, m.tension_malla_v <= m.contacto_tolerable_v)}
          {fila("Tensión de paso", m.tension_paso_v, m.paso_tolerable_v, m.tension_paso_v <= m.paso_tolerable_v)}
          {fila("Resistencia de la malla", m.resistencia_ohm, m.limite_resistencia_ohm, m.resistencia_cumple, "Ω")}
        </tbody>
      </table>
      <p className="tenue">Tolerables para una persona de 70 kg con 10 cm de grava; falla monofásica tomada igual a la trifásica y Sf = 0,6, por verificar.</p>
    </section>
  );
}
