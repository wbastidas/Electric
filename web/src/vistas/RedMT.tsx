import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { api, type BorradorRedMT, type RedMTDetalle, type Resultado } from "../api/cliente";
import { Detalle } from "./Calculos";
import { Aviso, Campo, elegirPestana, Insignia, MensajeError, type Pestana, Pestanas } from "./comunes";
import { Mapa } from "./Mapa";

type Poste = BorradorRedMT["postes"][number];

const num = (v: number | string | null | undefined, d = 1) =>
  v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("es-EC", { maximumFractionDigits: d });
const redondo = (v: number) => Math.round(v * 1e6) / 1e6;

/** Lee líneas «lat, lon[, kVA]» (o separadas por punto y coma o tabulador). */
export function leerCoordenadas(texto: string): { lat: number; lon: number; kva?: number }[] {
  const salida: { lat: number; lon: number; kva?: number }[] = [];
  for (const linea of texto.split(/\r?\n/)) {
    const partes = linea
      .split(/[;\t]|,(?=\s*-?\d)/)
      .map((x) => x.trim())
      .filter(Boolean);
    if (partes.length < 2) continue;
    const [lat, lon, kva] = partes.map((x) => Number(x.replace(",", ".")));
    if (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180)
      salida.push({ lat, lon, kva: Number.isFinite(kva) && kva > 0 ? kva : undefined });
  }
  return salida;
}

/** Extensión de red de media tensión: trazado sobre el mapa, cálculos y planos. */
export function RedMT({ id, pestana }: { id: string; pestana?: string }) {
  const consultas = useQueryClient();
  const red = useQuery({ queryKey: ["red-mt", id], queryFn: () => api.redMT(id) });
  const opciones = useQuery({ queryKey: ["opciones-mt"], queryFn: api.opcionesMT });
  const revision = red.data?.revision ?? 0;
  const calculo = useQuery({
    queryKey: ["calculo-mt", id, revision],
    queryFn: () => api.calculoRedMT(id),
    enabled: revision > 0,
  });
  const [datos, setDatos] = useState<BorradorRedMT | null>(null);
  const [cambios, setCambios] = useState(false);
  const [modo, setModo] = useState<"arranque" | "postes" | "mirar">("postes");
  const [seleccion, setSeleccion] = useState<Resultado | null>(null);

  useEffect(() => {
    if (red.data && !cambios) setDatos(red.data.datos);
  }, [red.data, cambios]);
  useEffect(() => {
    if (red.data && !red.data.datos.arranque) setModo("arranque");
  }, [red.data]);

  const alGuardar = (detalle: RedMTDetalle) => {
    consultas.setQueryData(["red-mt", id], detalle);
    consultas.invalidateQueries({ queryKey: ["redes-mt"] });
    setCambios(false);
    setDatos(detalle.datos);
  };
  const guardar = useMutation({
    mutationFn: () => api.guardarRedMT(id, revision, datos as BorradorRedMT),
    onSuccess: alGuardar,
  });

  const puntosMapa = useMemo(
    () =>
      (datos?.postes ?? []).map((p) => ({
        id: p.id,
        lat: Number(p.lat),
        lon: Number(p.lon),
        transformador: !!p.transformador_kva,
      })),
    [datos?.postes],
  );
  const arranqueMapa = useMemo(
    () =>
      datos?.arranque
        ? { lat: Number(datos.arranque.lat), lon: Number(datos.arranque.lon), poste: datos.arranque.poste }
        : null,
    [datos?.arranque],
  );

  if (red.isError) return <div className="pagina"><MensajeError error={red.error} /></div>;
  if (!datos || !red.data) return <div className="pagina">Cargando…</div>;

  const cambiar = (parcial: Partial<BorradorRedMT>) => {
    setDatos({ ...datos, ...parcial });
    setCambios(true);
  };
  const siguienteId = () => {
    const usados = new Set(datos.postes.map((p) => p.id));
    let n = datos.postes.length + 1;
    while (usados.has(`PN-${n}`)) n += 1;
    return `PN-${n}`;
  };
  const agregar = (nuevos: { lat: number; lon: number; kva?: number }[]) => {
    const usados = new Set(datos.postes.map((p) => p.id));
    let n = datos.postes.length;
    const postes: Poste[] = nuevos.map((c) => {
      n += 1;
      while (usados.has(`PN-${n}`)) n += 1;
      usados.add(`PN-${n}`);
      return { id: `PN-${n}`, lat: redondo(c.lat), lon: redondo(c.lon), transformador_kva: c.kva ?? null, estructura: null };
    });
    cambiar({ postes: [...datos.postes, ...postes] });
  };
  const cambiarPoste = (indice: number, parcial: Partial<Poste>) =>
    cambiar({ postes: datos.postes.map((p, n) => (n === indice ? { ...p, ...parcial } : p)) });

  const c = calculo.data?.estado === "listo" ? calculo.data : null;
  const pestanas: Pestana[] = [
    { id: "trazado", titulo: "Trazado", marca: datos.postes.length || null },
    { id: "datos", titulo: "Datos de la red" },
    {
      id: "existente",
      titulo: "Red existente",
      marca: red.data.existente ? red.data.existente.postes.length : null,
    },
    { id: "calculos", titulo: "Cálculos", marca: c?.avisos.length ? `${c.avisos.length} !` : null, alerta: !!c?.avisos.length },
    { id: "planos", titulo: "Planos" },
  ];
  const activa = elegirPestana(pestana, pestanas);

  return (
    <div className="pagina">
      <p className="miga">
        <a href="#/redes-mt">Redes MT</a> › {red.data.datos.nombre}
      </p>
      <div className="titulo-proyecto">
        <h1>{red.data.datos.nombre}</h1>
        <div className="acciones">
          {cambios ? <span className="tenue">Cambios sin guardar</span> : null}
          <button className="primario" disabled={!cambios || guardar.isPending} onClick={() => guardar.mutate()}>
            {guardar.isPending ? "Guardando…" : "Guardar y calcular"}
          </button>
        </div>
      </div>
      {guardar.isError ? <MensajeError error={guardar.error} /> : null}
      {c ? (
        <div className="resumen compacto franja">
          <div className="dato">
            <span className="etiqueta">Longitud</span>
            <span className="valor">{num(c.longitud_m)} m</span>
          </div>
          <div className="dato">
            <span className="etiqueta">Transformadores</span>
            <span className="valor">{num(c.kva_total)} kVA</span>
          </div>
          <div className="dato">
            <span className="etiqueta">Caída al final</span>
            <span className="valor">{num(c.caida_pct, 3)} %</span>
          </div>
          <div className="dato">
            <span className="etiqueta">Ik arranque</span>
            <span className="valor">{num(c.ik_arranque_ka, 2)} kA</span>
          </div>
          <div className="dato">
            <span className="etiqueta">Seccionador fusible</span>
            <span className="valor">{c.fusible_derivacion ?? "—"}</span>
          </div>
        </div>
      ) : null}
      <Pestanas items={pestanas} activa={activa} base={`#/redes-mt/${id}`} />

      {activa === "trazado" ? (
        <>
          <section className="tarjeta">
            <div className="barra-edicion" role="toolbar" aria-label="Qué hace un clic en el mapa">
              <button aria-pressed={modo === "arranque"} onClick={() => setModo("arranque")}>
                Marcar el arranque
              </button>
              <button aria-pressed={modo === "postes"} onClick={() => setModo("postes")}>
                Agregar postes
              </button>
              <button aria-pressed={modo === "mirar"} onClick={() => setModo("mirar")}>
                Solo mirar
              </button>
              <span className="tenue">
                {modo === "arranque"
                  ? "Clic en un poste existente (gris) o en el punto de conexión."
                  : modo === "postes"
                    ? "Cada clic agrega el poste siguiente; arrastre un poste para moverlo."
                    : "Arrastre los postes para moverlos."}
              </span>
            </div>
            <Mapa
              arranque={arranqueMapa}
              postes={puntosMapa}
              existente={red.data.existente ?? null}
              modo={modo}
              alClic={(lat, lon) => {
                if (modo === "arranque") {
                  cambiar({
                    arranque: {
                      caida_previa_pct: 0,
                      ...(datos.arranque ?? {}),
                      lat: redondo(lat),
                      lon: redondo(lon),
                      poste: null,
                    },
                  });
                  setModo("postes");
                } else agregar([{ lat, lon }]);
              }}
              alMover={(posteId, lat, lon) =>
                cambiar({
                  postes: datos.postes.map((p) => (p.id === posteId ? { ...p, lat: redondo(lat), lon: redondo(lon) } : p)),
                })
              }
              alElegirExistente={(p) => {
                cambiar({
                  arranque: {
                    caida_previa_pct: 0,
                    ...(datos.arranque ?? {}),
                    lat: p.lat,
                    lon: p.lon,
                    poste: p.id,
                    alimentador: p.alimentador ?? datos.arranque?.alimentador ?? null,
                  },
                });
                setModo("postes");
              }}
            />
            <p className="tenue">
              Mapa base de OpenStreetMap. La red existente aparece cuando se carga en «Red existente».
            </p>
          </section>
          <div className="columnas dos">
            <TablaPostes
              postes={datos.postes}
              estructuras={opciones.data?.estructuras ?? []}
              cambiar={cambiarPoste}
              quitar={(n) => cambiar({ postes: datos.postes.filter((_, k) => k !== n) })}
              mover={(n, paso) => {
                const otros = [...datos.postes];
                const destino = n + paso;
                if (destino < 0 || destino >= otros.length) return;
                [otros[n], otros[destino]] = [otros[destino], otros[n]];
                cambiar({ postes: otros });
              }}
            />
            <PegarCoordenadas agregar={agregar} siguiente={siguienteId()} />
          </div>
        </>
      ) : null}

      {activa === "datos" ? (
        <div className="columnas dos">
          <section className="tarjeta">
            <h2>Red nueva</h2>
            <div className="rejilla">
              <Campo etiqueta="Nombre">
                <input value={datos.nombre} onChange={(e) => cambiar({ nombre: e.target.value })} />
              </Campo>
              <Campo etiqueta="Propietario o solicitante">
                <input value={datos.propietario} onChange={(e) => cambiar({ propietario: e.target.value })} />
              </Campo>
              <Campo etiqueta="Tensión (kV)">
                <input inputMode="decimal" value={String(datos.tension_kv)} onChange={(e) => cambiar({ tension_kv: e.target.value })} />
              </Campo>
              <Campo etiqueta="Fases">
                <select value={datos.fases} onChange={(e) => cambiar({ fases: Number(e.target.value) as 1 | 3 })}>
                  <option value={3}>Trifásica</option>
                  <option value={1}>Monofásica</option>
                </select>
              </Campo>
              <Campo etiqueta="Conductor">
                <select value={datos.conductor} onChange={(e) => cambiar({ conductor: e.target.value })}>
                  {opciones.data?.conductores.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.nombre}
                    </option>
                  ))}
                </select>
              </Campo>
              <Campo etiqueta="Zona" ayuda="Define el vano máximo.">
                <select value={datos.zona} onChange={(e) => cambiar({ zona: e.target.value as "urbana" | "rural" })}>
                  <option value="urbana">Urbana</option>
                  <option value="rural">Rural</option>
                </select>
              </Campo>
              <Campo etiqueta="Factor de potencia">
                <input inputMode="decimal" value={String(datos.fp)} onChange={(e) => cambiar({ fp: e.target.value })} />
              </Campo>
            </div>
          </section>
          <section className="tarjeta">
            <h2>Punto de arranque</h2>
            {datos.arranque ? (
              <div className="rejilla">
                <Campo etiqueta="Latitud">
                  <input
                    inputMode="decimal"
                    value={String(datos.arranque.lat)}
                    onChange={(e) => cambiar({ arranque: { ...datos.arranque!, lat: e.target.value } })}
                  />
                </Campo>
                <Campo etiqueta="Longitud">
                  <input
                    inputMode="decimal"
                    value={String(datos.arranque.lon)}
                    onChange={(e) => cambiar({ arranque: { ...datos.arranque!, lon: e.target.value } })}
                  />
                </Campo>
                <Campo etiqueta="Poste existente">
                  <input
                    value={datos.arranque.poste ?? ""}
                    onChange={(e) => cambiar({ arranque: { ...datos.arranque!, poste: e.target.value || null } })}
                  />
                </Campo>
                <Campo etiqueta="Alimentador">
                  <input
                    value={datos.arranque.alimentador ?? ""}
                    onChange={(e) => cambiar({ arranque: { ...datos.arranque!, alimentador: e.target.value || null } })}
                  />
                </Campo>
                <Campo etiqueta="Scc en el arranque (MVA)" ayuda="Dato de la factibilidad; vacío: 250 MVA.">
                  <input
                    inputMode="decimal"
                    value={datos.arranque.scc_mva ?? ""}
                    onChange={(e) => cambiar({ arranque: { ...datos.arranque!, scc_mva: e.target.value || null } })}
                  />
                </Campo>
                <Campo etiqueta="Caída previa (%)" ayuda="Caída que ya existe hasta el arranque.">
                  <input
                    inputMode="decimal"
                    value={String(datos.arranque.caida_previa_pct ?? 0)}
                    onChange={(e) =>
                      cambiar({ arranque: { ...datos.arranque!, caida_previa_pct: e.target.value || "0" } })
                    }
                  />
                </Campo>
              </div>
            ) : (
              <p className="tenue">Márquelo en el mapa de la pestaña «Trazado».</p>
            )}
          </section>
        </div>
      ) : null}

      {activa === "existente" ? (
        <Existente
          id={id}
          detalle={red.data}
          geoportal={opciones.data?.geoportal_configurado ?? false}
          alCargar={() => consultas.invalidateQueries({ queryKey: ["red-mt", id] })}
        />
      ) : null}

      {calculo.data?.estado === "incompleto" && (activa === "calculos" || activa === "planos") ? (
        <Aviso tipo="nota">{calculo.data.pendientes.join(" ")}</Aviso>
      ) : null}

      {activa === "calculos" && c ? (
        <>
          {c.avisos.length ? (
            <Aviso tipo="alerta">
              <ul>
                {c.avisos.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </Aviso>
          ) : null}
          <div className="columnas dos">
            <section className="tarjeta">
              <h2>Resultados</h2>
              <ul className="lista-resultados">
                {c.resultados.map((r) => (
                  <li key={r.id}>
                    <button className="discreto" onClick={() => setSeleccion(r)}>
                      {r.nombre}: <strong>{r.texto}</strong>
                    </button>{" "}
                    <Insignia estado={r.estado} />
                  </li>
                ))}
              </ul>
            </section>
            <section className="tarjeta">
              <h2>Estructuras</h2>
              <div className="tabla-ancha">
                <table>
                  <thead>
                    <tr>
                      <th>N</th>
                      <th>Poste</th>
                      <th>Estructura</th>
                      <th className="derecha">Deflexión</th>
                      <th>Transformador</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.postes.map((p, n) => (
                      <tr key={p.id}>
                        <td>{n + 1}</td>
                        <td>{p.id}</td>
                        <td>
                          {p.estructura_nombre}
                          {p.codigo ? <span className="tenue"> · {p.codigo}</span> : null}
                        </td>
                        <td className="derecha">{p.angulo !== null ? `${num(p.angulo, 0)}°` : "—"}</td>
                        <td>{p.transformador_kva ? `${num(p.transformador_kva)} kVA · ${p.fusible ?? ""}` : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="tenue">Los códigos de las unidades de propiedad se toman del catálogo de CNEL.</p>
            </section>
          </div>
          <section className="tarjeta">
            <h2>Vanos y caída de tensión</h2>
            <div className="tabla-ancha">
              <table>
                <thead>
                  <tr>
                    <th>Vano</th>
                    <th className="derecha">Longitud</th>
                    <th className="derecha">Carga aguas abajo</th>
                    <th className="derecha">Caída</th>
                    <th className="derecha">Acumulada</th>
                  </tr>
                </thead>
                <tbody>
                  {c.vanos.map((v) => (
                    <tr key={`${v.desde}-${v.hasta}`} className={v.excede ? "dudoso" : ""}>
                      <td>
                        {v.desde} → {v.hasta}
                      </td>
                      <td className="derecha">
                        {num(v.longitud_m)} m{v.excede ? " (excede)" : ""}
                      </td>
                      <td className="derecha">{num(v.carga_kva)} kVA</td>
                      <td className="derecha">{num(v.caida_pct, 3)} %</td>
                      <td className="derecha">{num(v.caida_acumulada_pct, 3)} %</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="tenue">{c.aviso}</p>
          </section>
        </>
      ) : null}

      {activa === "planos" && c ? (
        <>
          {(["planimetria", "unifilar"] as const).map((plano) => (
            <section className="tarjeta" key={plano}>
              <h2>{plano === "planimetria" ? "Planimetría" : "Diagrama unifilar"}</h2>
              <div className="acciones izquierda">
                <a className="boton" href={api.urlPlanoMT(id, plano, "dxf", revision)}>
                  Descargar DXF
                </a>
                <a className="boton" href={api.urlPlanoMT(id, plano, "pdf", revision)} target="_blank" rel="noreferrer">
                  Abrir PDF
                </a>
                {plano === "planimetria" ? (
                  <a className="boton" href={api.urlKML(id)}>
                    Descargar KML
                  </a>
                ) : null}
              </div>
              <img
                className="unifilar"
                src={api.urlPlanoMT(id, plano, "png", revision)}
                alt={plano === "planimetria" ? "Planimetría de la red" : "Unifilar de la red"}
              />
            </section>
          ))}
        </>
      ) : null}
      {seleccion ? <Detalle resultado={seleccion} cerrar={() => setSeleccion(null)} /> : null}
    </div>
  );
}

function TablaPostes({
  postes,
  estructuras,
  cambiar,
  quitar,
  mover,
}: {
  postes: Poste[];
  estructuras: { id: string; nombre: string }[];
  cambiar: (n: number, parcial: Partial<Poste>) => void;
  quitar: (n: number) => void;
  mover: (n: number, paso: number) => void;
}) {
  return (
    <section className="tarjeta">
      <h2>Postes nuevos</h2>
      {postes.length ? (
        <div className="tabla-ancha">
          <table>
            <thead>
              <tr>
                <th>N</th>
                <th>Poste</th>
                <th>Latitud</th>
                <th>Longitud</th>
                <th>Transformador (kVA)</th>
                <th>Estructura</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {postes.map((p, n) => (
                <tr key={`${p.id}-${n}`}>
                  <td>{n + 1}</td>
                  <td>
                    <input className="corto" value={p.id} aria-label={`Código del poste ${n + 1}`} onChange={(e) => cambiar(n, { id: e.target.value })} />
                  </td>
                  <td>
                    <input className="corto" inputMode="decimal" value={String(p.lat)} aria-label={`Latitud del poste ${n + 1}`} onChange={(e) => cambiar(n, { lat: e.target.value })} />
                  </td>
                  <td>
                    <input className="corto" inputMode="decimal" value={String(p.lon)} aria-label={`Longitud del poste ${n + 1}`} onChange={(e) => cambiar(n, { lon: e.target.value })} />
                  </td>
                  <td>
                    <input
                      className="corto"
                      inputMode="decimal"
                      value={p.transformador_kva ?? ""}
                      aria-label={`Transformador del poste ${n + 1}`}
                      onChange={(e) => cambiar(n, { transformador_kva: e.target.value || null })}
                    />
                  </td>
                  <td>
                    <select
                      value={p.estructura ?? ""}
                      aria-label={`Estructura del poste ${n + 1}`}
                      onChange={(e) => cambiar(n, { estructura: e.target.value || null })}
                    >
                      <option value="">Automática</option>
                      {estructuras
                        .filter((x) => x.id !== "arranque")
                        .map((x) => (
                          <option key={x.id} value={x.id}>
                            {x.nombre}
                          </option>
                        ))}
                    </select>
                  </td>
                  <td className="derecha nowrap">
                    <button className="discreto" aria-label="Subir" onClick={() => mover(n, -1)}>
                      ↑
                    </button>
                    <button className="discreto" aria-label="Bajar" onClick={() => mover(n, 1)}>
                      ↓
                    </button>
                    <button className="discreto" onClick={() => quitar(n)}>
                      Quitar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="tenue">Marque los postes en el mapa o pegue sus coordenadas.</p>
      )}
    </section>
  );
}

function PegarCoordenadas({
  agregar,
  siguiente,
}: {
  agregar: (c: { lat: number; lon: number; kva?: number }[]) => void;
  siguiente: string;
}) {
  const [texto, setTexto] = useState("");
  const leidas = leerCoordenadas(texto);
  return (
    <section className="tarjeta">
      <h2>Pegar coordenadas</h2>
      <Campo
        etiqueta="Una línea por poste: latitud, longitud y, si lleva, kVA del transformador"
        ayuda="Por ejemplo: -2.170000, -79.899660 o -2.171530; -79.898800; 100. Se pueden pegar desde Excel."
      >
        <textarea rows={6} value={texto} onChange={(e) => setTexto(e.target.value)} />
      </Campo>
      <div className="acciones izquierda">
        <button
          className="primario"
          disabled={!leidas.length}
          onClick={() => {
            agregar(leidas);
            setTexto("");
          }}
        >
          Agregar {leidas.length || ""} postes
        </button>
        <span className="tenue">Se numeran desde {siguiente}, después del último.</span>
      </div>
    </section>
  );
}

function Existente({
  id,
  detalle,
  geoportal,
  alCargar,
}: {
  id: string;
  detalle: RedMTDetalle;
  geoportal: boolean;
  alCargar: () => void;
}) {
  const [radio, setRadio] = useState(300);
  const centro = detalle.datos.arranque ?? detalle.datos.postes[0] ?? null;
  const consultar = useMutation({
    mutationFn: () => api.existenteGeoportal(id, Number(centro?.lat), Number(centro?.lon), radio),
    onSuccess: alCargar,
  });
  const archivo = useMutation({ mutationFn: (f: File) => api.existenteArchivo(id, f), onSuccess: alCargar });
  const red = detalle.existente;
  const avisos = consultar.data?.avisos ?? archivo.data?.avisos ?? [];
  return (
    <div className="columnas dos">
      <section className="tarjeta">
        <h2>Geoportal de CNEL</h2>
        <p className="tenue">
          Lee postes con su estructura, tramos de MT, transformadores y protecciones alrededor del arranque.
        </p>
        {!geoportal ? (
          <Aviso tipo="alerta">
            Falta la dirección del servicio del geoportal en el perfil (tabla «sig»). Mientras tanto, cargue la red
            desde un archivo.
          </Aviso>
        ) : null}
        <Diagnostico />
        <div className="fila-formulario">
          <Campo etiqueta="Radio de búsqueda (m)">
            <input type="number" min={20} max={3000} value={radio} onChange={(e) => setRadio(Number(e.target.value))} />
          </Campo>
          <button disabled={!centro || consultar.isPending} onClick={() => consultar.mutate()}>
            {consultar.isPending ? "Consultando…" : "Leer del geoportal"}
          </button>
        </div>
        {!centro ? <p className="tenue">Marque primero el arranque o un poste en el mapa.</p> : null}
        {consultar.isError ? <MensajeError error={consultar.error} /> : null}
        <h3>Desde un archivo</h3>
        <label className="boton">
          {archivo.isPending ? "Leyendo…" : "Cargar GeoJSON exportado del SIG"}
          <input
            type="file"
            accept=".geojson,.json"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) archivo.mutate(f);
            }}
          />
        </label>
        {archivo.isError ? <MensajeError error={archivo.error} /> : null}
      </section>
      <section className="tarjeta">
        <h2>Red cargada</h2>
        {red ? (
          <>
            <div className="resumen compacto">
              <div className="dato">
                <span className="etiqueta">Postes</span>
                <span className="valor">{red.postes.length}</span>
              </div>
              <div className="dato">
                <span className="etiqueta">Tramos de MT</span>
                <span className="valor">{red.tramos.length}</span>
              </div>
              <div className="dato">
                <span className="etiqueta">Transformadores</span>
                <span className="valor">{red.transformadores.length}</span>
              </div>
              <div className="dato">
                <span className="etiqueta">Protecciones</span>
                <span className="valor">{red.protecciones.length}</span>
              </div>
            </div>
            <p className="tenue">Origen: {red.origen}. En el mapa, un clic en un poste existente lo toma como arranque.</p>
            {avisos.length ? (
              <Aviso tipo="alerta">
                <ul>
                  {avisos.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              </Aviso>
            ) : null}
          </>
        ) : (
          <p className="tenue">Todavía no se cargó la red existente.</p>
        )}
      </section>
    </div>
  );
}

function Diagnostico() {
  const diagnostico = useMutation({ mutationFn: api.diagnosticoGeoportal });
  const d = diagnostico.data;
  return (
    <details className="diagnostico">
      <summary>Diagnóstico de la conexión</summary>
      <p className="tenue">
        Muestra qué capas y campos del geoportal reconoce la plataforma. El servidor necesita acceso a
        geoportal.cnelep.gob.ec.
      </p>
      <button disabled={diagnostico.isPending} onClick={() => diagnostico.mutate()}>
        {diagnostico.isPending ? "Probando…" : "Probar la conexión"}
      </button>
      {diagnostico.isError ? <MensajeError error={diagnostico.error} /> : null}
      {d && !d.conectado ? (
        <Aviso tipo="error">
          <strong>No se pudo conectar.</strong> {d.error}
        </Aviso>
      ) : null}
      {d?.conectado ? (
        <>
          <p className="tenue">Capas del servicio: {d.capas_servicio.join(", ") || "ninguna"}</p>
          <div className="tabla-ancha">
            <table>
              <thead>
                <tr>
                  <th>Dato</th>
                  <th>Capa reconocida</th>
                  <th>Campos</th>
                </tr>
              </thead>
              <tbody>
                {d.capas.map((c) => (
                  <tr key={c.capa} className={c.url ? "" : "dudoso"}>
                    <td>{c.capa.replace("_", " ")}</td>
                    <td>{c.nombre ?? "no encontrada"}</td>
                    <td>
                      {Object.entries(c.campos)
                        .map(([dato, campo]) => `${dato}: ${campo ?? "—"}`)
                        .join(" · ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.avisos.length ? (
            <Aviso tipo="alerta">
              <ul>
                {d.avisos.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            </Aviso>
          ) : null}
        </>
      ) : null}
    </details>
  );
}
