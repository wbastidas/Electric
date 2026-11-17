import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ChangeEvent, useEffect, useState } from "react";
import {
  api,
  type AnalisisIndustrial,
  type BorradorIndustria,
  type OpcionesIndustriales,
  type Resultado,
} from "../api/cliente";
import { Detalle } from "./Calculos";
import { Aviso, Campo, Insignia, MensajeError } from "./comunes";

type Existente = NonNullable<BorradorIndustria["existente"]>;

const num = (v: number | string | null | undefined, d = 1) =>
  v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("es-EC", { maximumFractionDigits: d });

const EXISTENTE_VACIO: Existente = {
  codigo: "",
  kva: "50",
  fases: 3,
  demanda_kva: null,
  clientes: {},
  distancia_m: "50",
  origen: "manual",
};

/** Proyecto industrial: cuadro de cargas, transformador existente y decisión. */
export function Industria({ id }: { id: string }) {
  const consultas = useQueryClient();
  const industria = useQuery({ queryKey: ["industria", id], queryFn: () => api.industria(id) });
  const opciones = useQuery({ queryKey: ["opciones-industriales"], queryFn: api.opcionesIndustriales });
  const revision = industria.data?.revision ?? 0;
  const analisis = useQuery({
    queryKey: ["analisis-industria", id, revision],
    queryFn: () => api.analisisIndustria(id),
    enabled: revision > 0,
  });
  const [datos, setDatos] = useState<BorradorIndustria | null>(null);
  const [cambios, setCambios] = useState(false);
  const [seleccion, setSeleccion] = useState<Resultado | null>(null);

  useEffect(() => {
    if (industria.data && !cambios) setDatos(industria.data.datos);
  }, [industria.data, cambios]);

  const alGuardar = (detalle: { revision: number; datos: BorradorIndustria }) => {
    consultas.setQueryData(["industria", id], detalle);
    consultas.invalidateQueries({ queryKey: ["industrias"] });
    setCambios(false);
    setDatos(detalle.datos);
  };
  const guardar = useMutation({
    mutationFn: () => api.guardarIndustria(id, revision, datos as BorradorIndustria),
    onSuccess: alGuardar,
  });
  const subir = useMutation({
    mutationFn: (archivo: File) => api.subirCuadro(id, revision, archivo),
    onSuccess: alGuardar,
  });

  if (industria.isError) return <div className="pagina"><MensajeError error={industria.error} /></div>;
  if (!datos || !opciones.data) return <div className="pagina">Cargando…</div>;

  const cambiar = (parcial: Partial<BorradorIndustria>) => {
    setDatos({ ...datos, ...parcial });
    setCambios(true);
  };
  const existente = datos.existente ?? null;
  const cambiarExistente = (parcial: Partial<Existente>) =>
    cambiar({ existente: { ...(existente ?? EXISTENTE_VACIO), ...parcial } });

  const alElegirArchivo = (e: ChangeEvent<HTMLInputElement>) => {
    const archivo = e.target.files?.[0];
    e.target.value = "";
    if (!archivo) return;
    if (cambios && !window.confirm("Hay cambios sin guardar; el cuadro se carga sobre la última versión guardada. ¿Continuar?"))
      return;
    setCambios(false);
    subir.mutate(archivo);
  };

  const lat = datos.ubicacion?.lat ?? "";
  const lon = datos.ubicacion?.lon ?? "";
  const ubicar = (campo: "lat" | "lon", valor: string) => {
    const otra = { lat: String(lat), lon: String(lon), [campo]: valor };
    cambiar({ ubicacion: otra.lat === "" && otra.lon === "" ? null : { lat: otra.lat, lon: otra.lon } });
  };

  return (
    <div className="pagina">
      <p className="miga">
        <a href="#/">Proyectos</a> › Industria
      </p>
      <div className="titulo-proyecto">
        <h1>{industria.data?.datos.nombre}</h1>
        <div className="acciones">
          {cambios ? <span className="tenue">Cambios sin guardar</span> : null}
          <button className="primario" disabled={!cambios || guardar.isPending} onClick={() => guardar.mutate()}>
            {guardar.isPending ? "Guardando…" : "Guardar y analizar"}
          </button>
        </div>
      </div>
      {guardar.isError ? <MensajeError error={guardar.error} /> : null}

      <div className="columnas">
        <section className="tarjeta">
          <h2>Datos y ubicación</h2>
          <div className="rejilla">
            <Campo etiqueta="Nombre">
              <input value={datos.nombre} onChange={(e) => cambiar({ nombre: e.target.value })} />
            </Campo>
            <Campo etiqueta="Propietario">
              <input value={datos.propietario} onChange={(e) => cambiar({ propietario: e.target.value })} />
            </Campo>
            <Campo etiqueta="Dirección">
              <input value={datos.direccion} onChange={(e) => cambiar({ direccion: e.target.value })} />
            </Campo>
            <Campo etiqueta="Sistema de tensión">
              <select value={datos.sistema} onChange={(e) => cambiar({ sistema: e.target.value })}>
                {opciones.data.sistemas.map((s) => (
                  <option key={s.id} value={s.id}>{s.nombre}</option>
                ))}
              </select>
            </Campo>
            <Campo etiqueta="FP objetivo" ayuda="Vacío: el del perfil (0,92).">
              <input
                inputMode="decimal"
                value={datos.fp_objetivo ?? ""}
                onChange={(e) => cambiar({ fp_objetivo: e.target.value === "" ? null : e.target.value })}
              />
            </Campo>
            <Campo etiqueta="Scc de la red (MVA)" ayuda="Dato de la factibilidad de CNEL; vacío: 250 MVA.">
              <input
                inputMode="decimal"
                value={datos.scc_red_mva ?? ""}
                onChange={(e) => cambiar({ scc_red_mva: e.target.value === "" ? null : e.target.value })}
              />
            </Campo>
            <Campo etiqueta="Latitud">
              <input inputMode="decimal" value={lat} placeholder="-2.1709" onChange={(e) => ubicar("lat", e.target.value)} />
            </Campo>
            <Campo etiqueta="Longitud">
              <input inputMode="decimal" value={lon} placeholder="-79.9224" onChange={(e) => ubicar("lon", e.target.value)} />
            </Campo>
          </div>
          {lat !== "" && lon !== "" ? (
            <p>
              <a href={`https://www.openstreetmap.org/?mlat=${lat}&mlon=${lon}#map=18/${lat}/${lon}`} target="_blank" rel="noreferrer">
                Ver la ubicación en el mapa
              </a>
            </p>
          ) : null}
          <p className="tenue">
            La búsqueda automática del transformador más cercano en el geoportal de CNEL está pendiente; por ahora
            ingrese sus datos en «Transformador existente».
          </p>
        </section>

        <ExistenteForm
          existente={existente}
          opciones={opciones.data}
          activar={(si) => cambiar({ existente: si ? EXISTENTE_VACIO : null })}
          cambiar={cambiarExistente}
        />
      </div>

      <section className="tarjeta">
        <h2>Cuadro de cargas</h2>
        <div className="acciones izquierda">
          <label className="boton primario">
            {subir.isPending ? "Leyendo…" : "Cargar Excel o CSV"}
            <input type="file" accept=".xlsx,.xlsm,.csv" hidden onChange={alElegirArchivo} />
          </label>
          <a className="boton" href={api.urlPlantillaIndustrial}>Descargar la plantilla</a>
          <span className="tenue">
            {datos.cuadro ? `Cargado: ${datos.cuadro} · ${datos.maquinas.length} filas` : "Una fila por máquina; solo la potencia es obligatoria."}
          </span>
        </div>
        {subir.isError ? <MensajeError error={subir.error} /> : null}
        {analisis.data?.estado === "listo" ? <TablaMaquinas analisis={analisis.data} /> : null}
      </section>

      {analisis.isError ? <MensajeError error={analisis.error} /> : null}
      {analisis.data?.estado === "incompleto" ? (
        <Aviso tipo="nota">{analisis.data.pendientes.join(" ")}</Aviso>
      ) : null}
      {analisis.data?.estado === "listo" ? (
        <Resultados
          id={id}
          analisis={analisis.data}
          elegir={setSeleccion}
          distancias={datos.distancias_m ?? {}}
          cambiarDistancia={(tablero, valor) => {
            const otras = { ...(datos.distancias_m ?? {}) };
            if (valor.trim() === "") delete otras[tablero];
            else otras[tablero] = valor;
            cambiar({ distancias_m: otras });
          }}
        />
      ) : null}
      {seleccion ? <Detalle resultado={seleccion} cerrar={() => setSeleccion(null)} /> : null}
    </div>
  );
}

function ExistenteForm({
  existente,
  opciones,
  activar,
  cambiar,
}: {
  existente: Existente | null;
  opciones: OpcionesIndustriales;
  activar: (si: boolean) => void;
  cambiar: (parcial: Partial<Existente>) => void;
}) {
  const clientes = existente?.clientes ?? {};
  return (
    <section className="tarjeta">
      <h2>Transformador existente</h2>
      <label className="casilla">
        <input type="checkbox" checked={existente !== null} onChange={(e) => activar(e.target.checked)} />
        Hay un transformador de CNEL cerca de la industria
      </label>
      {existente ? (
        <>
          <div className="rejilla">
            <Campo etiqueta="Código">
              <input value={existente.codigo ?? ""} onChange={(e) => cambiar({ codigo: e.target.value || null })} />
            </Campo>
            <Campo etiqueta="Potencia (kVA)">
              <input inputMode="decimal" value={existente.kva} onChange={(e) => cambiar({ kva: e.target.value })} />
            </Campo>
            <Campo etiqueta="Fases">
              <select value={existente.fases} onChange={(e) => cambiar({ fases: Number(e.target.value) as 1 | 3 })}>
                <option value={3}>Trifásico</option>
                <option value={1}>Monofásico</option>
              </select>
            </Campo>
            <Campo etiqueta="Distancia a la industria (m)">
              <input inputMode="decimal" value={existente.distancia_m} onChange={(e) => cambiar({ distancia_m: e.target.value })} />
            </Campo>
            <Campo etiqueta="Demanda medida (kVA)" ayuda="Si CNEL la entrega; si no, se estima por clientes.">
              <input
                inputMode="decimal"
                value={existente.demanda_kva ?? ""}
                onChange={(e) => cambiar({ demanda_kva: e.target.value === "" ? null : e.target.value })}
              />
            </Campo>
          </div>
          <h3>Clientes conectados por estrato</h3>
          <div className="rejilla estratos">
            {opciones.estratos.map((e) => (
              <Campo key={e.id} etiqueta={e.id.length === 1 ? `Estrato ${e.id}` : e.id.charAt(0).toUpperCase() + e.id.slice(1)} ayuda={e.nombre}>
                <input
                  inputMode="numeric"
                  value={clientes[e.id] ?? ""}
                  onChange={(ev) => {
                    const otros = { ...clientes };
                    const n = parseInt(ev.target.value, 10);
                    if (Number.isNaN(n) || n <= 0) delete otros[e.id];
                    else otros[e.id] = n;
                    cambiar({ clientes: otros });
                  }}
                />
              </Campo>
            ))}
          </div>
        </>
      ) : (
        <p className="tenue">Sin transformador indicado, la decisión propone uno particular o queda pendiente.</p>
      )}
    </section>
  );
}

function TablaMaquinas({ analisis }: { analisis: AnalisisIndustrial }) {
  const circuito = (id: string) => analisis.circuitos.find((c) => c.maquina === id);
  return (
    <div className="tabla-ancha">
      <table>
        <thead>
          <tr>
            <th>Código</th>
            <th>Descripción</th>
            <th>Tablero</th>
            <th>Tipo</th>
            <th className="derecha">Cant.</th>
            <th>Placa</th>
            <th className="derecha">FP</th>
            <th className="derecha">Fu × Fs</th>
            <th className="derecha">Instalada kW</th>
            <th className="derecha">In A</th>
            <th className="derecha">Demanda kW</th>
            <th>Arranque</th>
            <th>Breaker</th>
            <th>Conductor</th>
          </tr>
        </thead>
        <tbody>
          {analisis.filas.map((f) => (
            <tr key={f.id} title={f.supuestos.length ? `Valores típicos: ${f.supuestos.join("; ")}` : undefined}>
              <td>{f.id}{f.supuestos.length ? <span className="tenue" aria-label="usa valores típicos"> *</span> : null}</td>
              <td>{f.descripcion || "—"}</td>
              <td>{f.tablero}</td>
              <td>{f.tipo_nombre}</td>
              <td className="derecha">{f.cantidad}</td>
              <td>{f.placa} · {f.fases}F</td>
              <td className="derecha">{num(f.fp, 2)}</td>
              <td className="derecha">{num(f.factor_utilizacion * f.factor_simultaneidad, 2)}</td>
              <td className="derecha">{num(f.instalada_kw, 2)}</td>
              <td className="derecha">{num(f.corriente_a)}</td>
              <td className="derecha">{num(f.demanda_kw, 2)}</td>
              <td>{f.arranque ? `${f.arranque.replaceAll("_", " ")} (${num(f.corriente_arranque_a, 0)} A)` : "—"}</td>
              <td>{circuito(f.id)?.breaker_a ? `${circuito(f.id)?.polos}P ${num(circuito(f.id)?.breaker_a, 0)} A` : "—"}</td>
              <td>{circuito(f.id)?.conductor ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="tenue">
        * Usa valores típicos del perfil en las celdas vacías; pase el cursor para ver cuáles. Circuitos de máquinas
        calculados con 15 m desde su tablero.
      </p>
    </div>
  );
}

function Resultados({
  id,
  analisis,
  elegir,
  distancias,
  cambiarDistancia,
}: {
  id: string;
  analisis: AnalisisIndustrial;
  elegir: (r: Resultado) => void;
  distancias: Record<string, number | string>;
  cambiarDistancia: (tablero: string, valor: string) => void;
}) {
  const d = analisis.decision;
  const alimentador = (t: string) => analisis.alimentadores.find((a) => a.tablero === t);
  const cc = (punto: string) => analisis.cortocircuito.find((c) => c.punto === punto);
  const tp = cc("TP");
  return (
    <>
      <div className="columnas">
        {d ? (
          <section className={`tarjeta decision ${d.opcion}`}>
            <h2>Decisión: {d.titulo}</h2>
            <p className="tenue">Nivel de servicio por norma: {d.nivel_nombre} · medición en {d.medicion}</p>
            <ul>
              {d.motivos.map((m) => <li key={m}>{m}</li>)}
            </ul>
            {d.comprobaciones.length ? (
              <ul className="comprobaciones">
                {d.comprobaciones.map((c) => (
                  <li key={c.nombre} className={c.cumple ? "cumple" : "falla"}>
                    <strong>{c.cumple ? "✓" : "✗"} {c.nombre}:</strong> {c.detalle}
                  </li>
                ))}
              </ul>
            ) : null}
            {d.transformador && d.opcion !== "existente" ? (
              <p className="cifra-media">
                Transformador propuesto: {num(d.transformador.kva)} kVA {d.transformador.fases === 3 ? "trifásico" : "monofásico"},
                {" "}{d.transformador.montaje}, Z {num(d.transformador.z_pct, 2)} %
              </p>
            ) : null}
          </section>
        ) : null}
        <section className="tarjeta">
          <h2>Resultados</h2>
          <p className="tenue">{analisis.sistema}. Pulse un resultado para ver fórmula, entradas y tablas.</p>
          <ul className="lista-resultados">
            {analisis.resultados.map((r) => (
              <li key={`${r.sujeto}-${r.id}`}>
                <button className="discreto" onClick={() => elegir(r)}>
                  {r.nombre}: <strong>{r.texto}</strong>
                </button>{" "}
                <Insignia estado={r.estado} />
                {r.avisos.map((a) => <div key={a} className="aviso-linea">{a}</div>)}
              </li>
            ))}
          </ul>
        </section>
      </div>
      <section className="tarjeta">
        <h2>Tableros</h2>
        <div className="tabla-ancha">
          <table>
            <thead>
              <tr>
                <th>Tablero</th>
                <th className="derecha">Máquinas</th>
                <th className="derecha">Instalada kW</th>
                <th className="derecha">Demanda kW</th>
                <th className="derecha">kVA</th>
                <th className="derecha">FP</th>
                <th className="derecha">Corriente A</th>
                <th className="derecha">Breaker</th>
                <th>Distancia (m)</th>
                <th>Alimentador</th>
                <th className="derecha">ΔV</th>
                <th className="derecha">Ik</th>
                <th className="derecha">Icu</th>
              </tr>
            </thead>
            <tbody>
              {tp ? (
                <tr className="principal">
                  <td>TP (principal)</td>
                  <td colSpan={10} className="tenue">{analisis.fuente_cortocircuito}</td>
                  <td className="derecha">{num(tp.ik_ka, 2)} kA</td>
                  <td className="derecha">{tp.capacidad_ka ? `${num(tp.capacidad_ka, 0)} kA` : "fuera de serie"}</td>
                </tr>
              ) : null}
              {analisis.tableros.map((t) => (
                <tr key={t.tablero}>
                  <td>{t.tablero}</td>
                  <td className="derecha">{t.maquinas}</td>
                  <td className="derecha">{num(t.instalada_kw, 2)}</td>
                  <td className="derecha">{num(t.demanda_kw, 2)}</td>
                  <td className="derecha">{num(t.demanda_kva, 2)}</td>
                  <td className="derecha">{num(t.fp, 2)}</td>
                  <td className="derecha">{num(t.corriente_a)}</td>
                  <td className="derecha">{t.breaker_a ? `${num(t.breaker_a, 0)} A` : "fuera de serie"}</td>
                  <td>
                    <input
                      className="corto"
                      inputMode="decimal"
                      aria-label={`Distancia a ${t.tablero}`}
                      placeholder={`${num(alimentador(t.tablero)?.longitud_m)} (supuesta)`}
                      value={distancias[t.tablero] ?? ""}
                      onChange={(e) => cambiarDistancia(t.tablero, e.target.value)}
                    />
                  </td>
                  <td>{alimentador(t.tablero)?.conductor ?? "sin solución"}</td>
                  <td className="derecha">{num(alimentador(t.tablero)?.caida_pct, 2)} %</td>
                  <td className="derecha">{cc(t.tablero) ? `${num(cc(t.tablero)?.ik_ka, 2)} kA` : "—"}</td>
                  <td className="derecha">
                    {cc(t.tablero)?.capacidad_ka ? `${num(cc(t.tablero)?.capacidad_ka, 0)} kA` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {analisis.avisos.length ? (
          <Aviso tipo="alerta">
            <ul>{analisis.avisos.map((a) => <li key={a}>{a}</li>)}</ul>
          </Aviso>
        ) : null}
        <p className="tenue">
          Escriba la distancia real de cada tablero y pulse «Guardar y analizar»; sin ella se supone 20 m. Ik:
          cortocircuito trifásico con aporte de motores; Icu: capacidad de interrupción mínima de los breakers.
        </p>
      </section>
      <section className="tarjeta">
        <h2>Diagrama unifilar</h2>
        <div className="acciones izquierda">
          <a className="boton" href={api.urlUnifilar(id, "dxf", analisis.revision)}>Descargar DXF</a>
          <a className="boton" href={api.urlUnifilar(id, "pdf", analisis.revision)} target="_blank" rel="noreferrer">
            Abrir PDF
          </a>
        </div>
        <img
          className="unifilar"
          src={api.urlUnifilar(id, "png", analisis.revision)}
          alt="Diagrama unifilar de la industria"
        />
        <p className="tenue">{analisis.aviso}</p>
      </section>
    </>
  );
}
