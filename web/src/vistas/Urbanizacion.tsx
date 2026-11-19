import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type BorradorUrbanizacion, type CalculoUrbanizacion, type Resultado } from "../api/cliente";
import { Detalle } from "./Calculos";
import { Aviso, Campo, elegirPestana, MensajeError, type Pestana, Pestanas } from "./comunes";

type Manzana = BorradorUrbanizacion["manzanas"][number];
type Comunal = BorradorUrbanizacion["comunales"][number];

const num = (v: number | string | null | undefined, d = 1) =>
  v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("es-EC", { maximumFractionDigits: d });

/** Urbanización o lotización: sectores de transformación, red de BT y alumbrado público. */
export function Urbanizacion({ id, pestana }: { id: string; pestana?: string }) {
  const consultas = useQueryClient();
  const urbanizacion = useQuery({ queryKey: ["urbanizacion", id], queryFn: () => api.urbanizacion(id) });
  const revision = urbanizacion.data?.revision ?? 0;
  const calculo = useQuery({
    queryKey: ["calculo-urbanizacion", id, revision],
    queryFn: () => api.calculoUrbanizacion(id),
    enabled: revision > 0,
  });
  const opciones = useQuery({ queryKey: ["opciones-edificio"], queryFn: api.opcionesEdificio });
  const [datos, setDatos] = useState<BorradorUrbanizacion | null>(null);
  const [cambios, setCambios] = useState(false);
  const [seleccion, setSeleccion] = useState<Resultado | null>(null);
  useEffect(() => {
    if (urbanizacion.data && !cambios) setDatos(urbanizacion.data.datos);
  }, [urbanizacion.data, cambios]);
  const guardar = useMutation({
    mutationFn: () => api.guardarUrbanizacion(id, revision, datos as BorradorUrbanizacion),
    onSuccess: (d) => {
      consultas.setQueryData(["urbanizacion", id], d);
      consultas.invalidateQueries({ queryKey: ["urbanizaciones"] });
      setCambios(false);
      setDatos(d.datos);
    },
  });
  if (urbanizacion.isError) return <div className="pagina"><MensajeError error={urbanizacion.error} /></div>;
  if (!datos) return <div className="pagina">Cargando…</div>;
  const cambiar = (p: Partial<BorradorUrbanizacion>) => {
    setDatos({ ...datos, ...p });
    setCambios(true);
  };
  const listo = calculo.data?.estado === "listo" ? calculo.data : null;
  const lotes = datos.manzanas.reduce((n, m) => n + m.lotes, 0);
  const pestanas: Pestana[] = [
    { id: "datos", titulo: "Manzanas y datos", marca: lotes || null },
    { id: "sectores", titulo: "Transformadores y red BT", marca: listo?.sectores.length ?? null },
    { id: "plano", titulo: "Plano" },
    { id: "memoria", titulo: "Memoria de cálculo", marca: listo?.resultados.length ?? null },
  ];
  const activa = elegirPestana(pestana ?? (datos.manzanas.length ? "sectores" : "datos"), pestanas);
  const vacio = (v: string) => (v.trim() === "" ? null : v);
  const cambiarManzana = (i: number, p: Partial<Manzana>) =>
    cambiar({ manzanas: datos.manzanas.map((m, j) => (j === i ? { ...m, ...p } : m)) });
  const cambiarComunal = (i: number, p: Partial<Comunal>) =>
    cambiar({ comunales: datos.comunales.map((c, j) => (j === i ? { ...c, ...p } : c)) });

  return (
    <div className="pagina">
      <p className="miga">
        <a href="#/redes-mt">Redes MT</a> › {urbanizacion.data?.datos.nombre}
      </p>
      <div className="titulo-proyecto">
        <h1>{urbanizacion.data?.datos.nombre}</h1>
        <div className="acciones">
          <span className="chip-tipo">Urbanización</span>
          {cambios ? <span className="tenue">Cambios sin guardar</span> : null}
          <button className="primario" disabled={!cambios || guardar.isPending} onClick={() => guardar.mutate()}>
            {guardar.isPending ? "Guardando…" : "Guardar y calcular"}
          </button>
        </div>
      </div>
      {guardar.isError ? <MensajeError error={guardar.error} /> : null}
      {listo ? (
        <div className="resumen compacto franja">
          <div className="dato"><span className="etiqueta">Lotes</span><span className="valor">{listo.lotes}</span></div>
          <div className="dato"><span className="etiqueta">Demanda en MT</span><span className="valor">{num(listo.demanda_kva)} kVA</span></div>
          <div className="dato"><span className="etiqueta">Corriente MT</span><span className="valor">{num(listo.corriente_mt_a, 2)} A</span></div>
          <div className="dato"><span className="etiqueta">Transformadores</span><span className="valor">{listo.sectores.length} · {num(listo.kva_instalados)} kVA</span></div>
          <div className="dato"><span className="etiqueta">Alumbrado</span><span className="valor">{listo.luminarias} luminarias</span></div>
        </div>
      ) : null}
      <Pestanas items={pestanas} activa={activa} base={`#/urbanizaciones/${id}`} />

      {activa === "datos" ? (
        <>
          <section className="tarjeta">
            <h2>Datos generales</h2>
            <div className="rejilla">
              <Campo etiqueta="Nombre"><input value={datos.nombre} onChange={(e) => cambiar({ nombre: e.target.value })} /></Campo>
              <Campo etiqueta="Promotor"><input value={datos.propietario ?? ""} onChange={(e) => cambiar({ propietario: e.target.value })} /></Campo>
              <Campo etiqueta="Estrato de los lotes">
                <select value={datos.estrato ?? "C"} onChange={(e) => cambiar({ estrato: e.target.value })}>
                  {(opciones.data?.usuarios ?? []).filter((u) => u.kva !== null).map((u) => (
                    <option key={u.id} value={u.id}>{u.id} · {num(u.kva)} kVA · {u.nombre}</option>
                  ))}
                </select>
              </Campo>
              <Campo etiqueta="Transformadores">
                <select value={datos.fases_transformador ?? 1}
                  onChange={(e) => {
                    const f = Number(e.target.value) as 1 | 3;
                    cambiar({ fases_transformador: f, sistema: f === 3 ? "trifasico_127_220" : "monofasico_trifilar_120_240" });
                  }}>
                  <option value={1}>Monofásicos 120/240 V</option>
                  <option value={3}>Trifásicos 220/127 V</option>
                </select>
              </Campo>
              <Campo etiqueta="Mayor transformador (kVA)" ayuda="Vacío: 50 kVA monofásico, 112,5 kVA trifásico.">
                <input inputMode="decimal" value={datos.kva_max_transformador ?? ""} onChange={(e) => cambiar({ kva_max_transformador: vacio(e.target.value) })} />
              </Campo>
              <Campo etiqueta="Ancho de calle (m)">
                <input inputMode="decimal" value={datos.ancho_calle_m ?? "10"} onChange={(e) => cambiar({ ancho_calle_m: e.target.value })} />
              </Campo>
              <Campo etiqueta="Separación de luminarias (m)" ayuda="Vacío: 30 m.">
                <input inputMode="decimal" value={datos.separacion_luminarias_m ?? ""} onChange={(e) => cambiar({ separacion_luminarias_m: vacio(e.target.value) })} />
              </Campo>
              <Campo etiqueta="Potencia de luminaria (W)" ayuda="Vacío: LED de 60 W.">
                <input inputMode="decimal" value={datos.potencia_luminaria_w ?? ""} onChange={(e) => cambiar({ potencia_luminaria_w: vacio(e.target.value) })} />
              </Campo>
            </div>
          </section>
          <section className="tarjeta">
            <h2>Manzanas</h2>
            <p className="tenue">
              De arriba hacia abajo; cada manzana tiene dos filas de lotes espalda con espalda, con calles entre manzanas
              (calle 0 arriba de la primera).
            </p>
            <div className="tabla-ancha">
              <table className="editable">
                <thead><tr><th>Manzana</th><th>Lotes</th><th>Frente (m)</th><th>Fondo (m)</th><th /></tr></thead>
                <tbody>
                  {datos.manzanas.map((m, i) => (
                    <tr key={i}>
                      <td><input value={m.id} onChange={(e) => cambiarManzana(i, { id: e.target.value })} /></td>
                      <td><input inputMode="numeric" value={m.lotes} onChange={(e) => cambiarManzana(i, { lotes: Math.max(1, Number(e.target.value) || 1) })} /></td>
                      <td><input inputMode="decimal" value={m.frente_m ?? "10"} onChange={(e) => cambiarManzana(i, { frente_m: e.target.value })} /></td>
                      <td><input inputMode="decimal" value={m.fondo_m ?? "20"} onChange={(e) => cambiarManzana(i, { fondo_m: e.target.value })} /></td>
                      <td><button className="discreto" onClick={() => cambiar({ manzanas: datos.manzanas.filter((_, j) => j !== i) })}>Quitar</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button onClick={() => cambiar({ manzanas: [...datos.manzanas, { id: String.fromCharCode(65 + datos.manzanas.length), lotes: 20, frente_m: "10", fondo_m: "20" }] })}>
              Agregar manzana
            </button>
          </section>
          <section className="tarjeta">
            <h2>Cargas comunales</h2>
            <div className="tabla-ancha">
              <table className="editable">
                <thead><tr><th>Carga</th><th>kVA</th><th>Calle</th><th /></tr></thead>
                <tbody>
                  {datos.comunales.map((c, i) => (
                    <tr key={i}>
                      <td><input value={c.descripcion} onChange={(e) => cambiarComunal(i, { descripcion: e.target.value })} /></td>
                      <td><input inputMode="decimal" value={c.kva} onChange={(e) => cambiarComunal(i, { kva: e.target.value })} /></td>
                      <td><input inputMode="numeric" value={c.calle ?? 0} onChange={(e) => cambiarComunal(i, { calle: Math.max(0, Number(e.target.value) || 0) })} /></td>
                      <td><button className="discreto" onClick={() => cambiar({ comunales: datos.comunales.filter((_, j) => j !== i) })}>Quitar</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <button onClick={() => cambiar({ comunales: [...datos.comunales, { descripcion: "Casa comunal", kva: "10", calle: 0 }] })}>
              Agregar carga comunal
            </button>
          </section>
        </>
      ) : null}
      {calculo.data?.estado === "incompleto" && activa !== "datos" ? <Aviso tipo="nota">{calculo.data.pendientes.join(" ")}</Aviso> : null}
      {listo && activa === "sectores" ? <Sectores c={listo} /> : null}
      {listo && activa === "plano" ? (
        <section className="tarjeta">
          <h2>Plano esquemático</h2>
          <div className="acciones izquierda">
            <a className="boton" href={api.urlPlanoUrbanizacion(id, "dxf", listo.revision)}>Descargar DXF</a>
            <a className="boton" href={api.urlPlanoUrbanizacion(id, "pdf", listo.revision)} target="_blank" rel="noreferrer">Abrir PDF</a>
          </div>
          <img className="unifilar" src={api.urlPlanoUrbanizacion(id, "png", listo.revision)} alt="Plano de la urbanización" />
          <p className="tenue">
            MT en rojo por la avenida lateral, transformadores en magenta, circuitos de BT en verde y luminarias en amarillo. Para
            el trazado real de la MT sobre el mapa use una extensión de red. {listo.aviso}
          </p>
        </section>
      ) : null}
      {listo && activa === "memoria" ? (
        <section className="tarjeta">
          <h2>Memoria de cálculo</h2>
          <div className="tabla-ancha">
            <table>
              <thead><tr><th>Cálculo</th><th>Sujeto</th><th>Resultado</th></tr></thead>
              <tbody>
                {listo.resultados.map((r) => (
                  <tr key={`${r.id}-${r.sujeto}`} className="seleccionable" onClick={() => setSeleccion(r)}>
                    <td>{r.nombre}</td><td>{r.sujeto}</td><td>{r.texto}</td>
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

function Sectores({ c }: { c: CalculoUrbanizacion }) {
  return (
    <section className="tarjeta">
      <h2>Transformadores por sector y red de baja tensión</h2>
      <p className="tenue">
        Demanda de {c.lotes} lotes con DMU de {num(c.dmu_kva)} kVA y factor de coincidencia por sector; alumbrado público de{" "}
        {c.luminarias} luminarias ({num(c.alumbrado_kva, 2)} kVA). La demanda en MT usa la coincidencia de todos los lotes.
      </p>
      <div className="tabla-ancha">
        <table>
          <thead>
            <tr>
              <th>Sector</th><th className="num">Calle</th><th className="num">Lotes</th><th className="num">Luminarias</th>
              <th className="num">Demanda (kVA)</th><th className="num">Transformador</th><th>Circuitos de BT</th>
            </tr>
          </thead>
          <tbody>
            {c.sectores.map((s) => (
              <tr key={s.id}>
                <td>{s.id}</td><td className="num">{s.calle}</td><td className="num">{s.lotes}</td><td className="num">{s.luminarias}</td>
                <td className="num">{num(s.demanda_kva)}{s.comunal_kva ? ` (incl. ${num(s.comunal_kva)} comunal)` : ""}</td>
                <td className="num">{s.kva ? `${num(s.kva)} kVA` : "—"}</td>
                <td>
                  {s.circuitos.map((x) => (
                    <div key={x.lado} className={x.conductor ? undefined : "mal"}>
                      {x.lado}: {x.lotes} lotes · {num(x.longitud_m, 0)} m · {x.conductor ?? "sin solución"} · ΔV {num(x.caida_pct, 2)} %
                    </div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {c.avisos.length ? <Aviso tipo="alerta"><ul>{c.avisos.map((a) => <li key={a}>{a}</li>)}</ul></Aviso> : null}
      <p className="tenue">Conductores de la tabla del perfil; reemplácela por la de red aérea (dúplex/tríplex) de CNEL antes de presentar.</p>
    </section>
  );
}
