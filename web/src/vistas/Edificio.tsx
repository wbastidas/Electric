import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, type BorradorEdificio, type CalculoEdificio, type OpcionesEdificio, type Resultado } from "../api/cliente";
import { Detalle } from "./Calculos";
import { Aviso, Campo, elegirPestana, MensajeError, type Pestana, Pestanas } from "./comunes";
import { TarjetaCamara } from "./Industria";

type Unidad = BorradorEdificio["unidades"][number];
type Servicio = BorradorEdificio["servicios"][number];

const num = (v: number | string | null | undefined, d = 1) =>
  v === null || v === undefined || v === "" ? "—" : Number(v).toLocaleString("es-EC", { maximumFractionDigits: d });

export const TIPOS_EDIFICIO: Record<BorradorEdificio["tipo"], string> = {
  departamentos: "Edificio de departamentos",
  locales_oficinas: "Locales y oficinas",
  comercial: "Comercial grande",
};

/** «1-8», «0», «1,3,5-7» → pisos. */
export const leerPisos = (texto: string): number[] | null => {
  const pisos: number[] = [];
  for (const parte of texto.split(",").map((p) => p.trim()).filter(Boolean)) {
    const rango = parte.match(/^(-?\d+)\s*-\s*(-?\d+)$/);
    if (rango) {
      const [a, b] = [Number(rango[1]), Number(rango[2])];
      if (b < a || b - a > 100) return null;
      for (let p = a; p <= b; p++) pisos.push(p);
    } else if (/^-?\d+$/.test(parte)) pisos.push(Number(parte));
    else return null;
  }
  return pisos.length && new Set(pisos).size === pisos.length ? pisos : null;
};

const escribirPisos = (pisos: number[]): string => {
  const orden = [...pisos].sort((a, b) => a - b);
  const partes: string[] = [];
  for (let i = 0; i < orden.length; ) {
    let j = i;
    while (j + 1 < orden.length && orden[j + 1] === orden[j] + 1) j++;
    partes.push(j > i ? `${orden[i]}-${orden[j]}` : `${orden[i]}`);
    i = j + 1;
  }
  return partes.join(", ");
};

const nuevaUnidad = (tipo: BorradorEdificio["tipo"], n: number): Unidad =>
  tipo === "departamentos"
    ? { id: `Tipo ${String.fromCharCode(64 + n)}`, uso: "departamento", estrato: "C", fases: 2, pisos: [1], por_piso: 2, area_m2: null, demanda_kva: null }
    : { id: `Local ${n}`, uso: tipo === "locales_oficinas" ? "oficina" : "local", estrato: "C", fases: 3, pisos: [0], por_piso: 1, area_m2: "80", demanda_kva: null };

/** Edificio de departamentos, locales u oficinas con centro de medición. */
export function Edificio({ id, pestana }: { id: string; pestana?: string }) {
  const consultas = useQueryClient();
  const edificio = useQuery({ queryKey: ["edificio", id], queryFn: () => api.edificio(id) });
  const opciones = useQuery({ queryKey: ["opciones-edificio"], queryFn: api.opcionesEdificio });
  const revision = edificio.data?.revision ?? 0;
  const calculo = useQuery({
    queryKey: ["calculo-edificio", id, revision],
    queryFn: () => api.calculoEdificio(id),
    enabled: revision > 0,
  });
  const [datos, setDatos] = useState<BorradorEdificio | null>(null);
  const [cambios, setCambios] = useState(false);
  const [seleccion, setSeleccion] = useState<Resultado | null>(null);

  useEffect(() => {
    if (edificio.data && !cambios) setDatos(edificio.data.datos);
  }, [edificio.data, cambios]);

  const guardar = useMutation({
    mutationFn: () => api.guardarEdificio(id, revision, datos as BorradorEdificio),
    onSuccess: (detalle) => {
      consultas.setQueryData(["edificio", id], detalle);
      consultas.invalidateQueries({ queryKey: ["edificios"] });
      setCambios(false);
      setDatos(detalle.datos);
    },
  });

  if (edificio.isError) return <div className="pagina"><MensajeError error={edificio.error} /></div>;
  if (!datos || !opciones.data) return <div className="pagina">Cargando…</div>;

  const cambiar = (parcial: Partial<BorradorEdificio>) => {
    setDatos({ ...datos, ...parcial });
    setCambios(true);
  };
  const listo = calculo.data?.estado === "listo" ? calculo.data : null;
  const unidades = datos.unidades.reduce((n, u) => n + u.pisos.length * (u.por_piso ?? 1), 0);
  const pestanas: Pestana[] = [
    { id: "datos", titulo: "Datos del edificio" },
    { id: "unidades", titulo: "Unidades y servicios", marca: unidades || null },
    { id: "demanda", titulo: "Demanda y transformador" },
    { id: "medicion", titulo: "Centro de medición", marca: listo?.medidores ?? null },
    { id: "unifilar", titulo: "Unifilar" },
    ...(listo?.camara ? [{ id: "camara", titulo: "Cámara MT", marca: listo.camara.cumple ? null : "✗", alerta: !listo.camara.cumple }] : []),
    { id: "memoria", titulo: "Memoria de cálculo", marca: listo?.resultados.length ?? null },
  ];
  const activa = elegirPestana(pestana ?? (datos.unidades.length ? "demanda" : "unidades"), pestanas);

  return (
    <div className="pagina">
      <p className="miga">
        <a href="#/no-residencial">No residencial</a> › {edificio.data?.datos.nombre}
      </p>
      <div className="titulo-proyecto">
        <h1>{edificio.data?.datos.nombre}</h1>
        <div className="acciones">
          <span className="chip-tipo">{TIPOS_EDIFICIO[datos.tipo]}</span>
          {cambios ? <span className="tenue">Cambios sin guardar</span> : null}
          <button className="primario" disabled={!cambios || guardar.isPending} onClick={() => guardar.mutate()}>
            {guardar.isPending ? "Guardando…" : "Guardar y calcular"}
          </button>
        </div>
      </div>
      {guardar.isError ? <MensajeError error={guardar.error} /> : null}
      {listo ? <ResumenEdificio c={listo} /> : null}
      <Pestanas items={pestanas} activa={activa} base={`#/edificios/${id}`} />

      {activa === "datos" ? <DatosGenerales datos={datos} cambiar={cambiar} opciones={opciones.data} /> : null}
      {activa === "unidades" ? <UnidadesServicios datos={datos} cambiar={cambiar} opciones={opciones.data} /> : null}
      {calculo.isError ? <MensajeError error={calculo.error} /> : null}
      {calculo.data?.estado === "incompleto" && activa !== "datos" && activa !== "unidades" ? (
        <Aviso tipo="nota">{calculo.data.pendientes.join(" ")}</Aviso>
      ) : null}
      {listo && activa === "demanda" ? <Demanda c={listo} /> : null}
      {listo && activa === "medicion" ? <Medicion c={listo} /> : null}
      {listo && activa === "unifilar" ? (
        <section className="tarjeta">
          <h2>Diagrama unifilar</h2>
          <div className="acciones izquierda">
            <a className="boton" href={api.urlPlanoEdificio(id, "unifilar", "dxf", listo.revision)}>Descargar DXF</a>
            <a className="boton" href={api.urlPlanoEdificio(id, "unifilar", "pdf", listo.revision)} target="_blank" rel="noreferrer">
              Abrir PDF
            </a>
          </div>
          <img className="unifilar" src={api.urlPlanoEdificio(id, "unifilar", "png", listo.revision)} alt="Diagrama unifilar del edificio" />
          <p className="tenue">{listo.aviso}</p>
        </section>
      ) : null}
      {listo?.camara && activa === "camara" ? (
        <TarjetaCamara
          camara={listo.camara}
          url={(f) => api.urlPlanoEdificio(id, "camara", f, listo.revision)}
          aviso={listo.aviso}
          dondeResistividad="«Datos del edificio»"
        />
      ) : null}
      {listo && activa === "memoria" ? (
        <section className="tarjeta">
          <h2>Memoria de cálculo</h2>
          <p className="tenue">Cada resultado muestra su fórmula, datos, tablas del perfil y supuestos. Pulse uno para ver el detalle.</p>
          <div className="tabla-ancha">
            <table>
              <thead>
                <tr><th>Cálculo</th><th>Sujeto</th><th>Resultado</th><th>Estado</th></tr>
              </thead>
              <tbody>
                {listo.resultados.map((r) => (
                  <tr key={`${r.id}-${r.sujeto}`} className="seleccionable" onClick={() => setSeleccion(r)}>
                    <td>{r.nombre}</td>
                    <td>{r.sujeto}</td>
                    <td>{r.texto}</td>
                    <td>{r.estado === "verificado" ? "verificado" : "por verificar"}</td>
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

function DatosGenerales({
  datos,
  cambiar,
  opciones,
}: {
  datos: BorradorEdificio;
  cambiar: (p: Partial<BorradorEdificio>) => void;
  opciones: OpcionesEdificio;
}) {
  const decimal = (v: string) => (v.trim() === "" ? null : v);
  return (
    <div className="columnas dos">
      <section className="tarjeta">
        <h2>Datos del edificio</h2>
        <div className="rejilla">
          <Campo etiqueta="Nombre">
            <input value={datos.nombre} onChange={(e) => cambiar({ nombre: e.target.value })} />
          </Campo>
          <Campo etiqueta="Propietario">
            <input value={datos.propietario ?? ""} onChange={(e) => cambiar({ propietario: e.target.value })} />
          </Campo>
          <Campo etiqueta="Dirección">
            <input value={datos.direccion ?? ""} onChange={(e) => cambiar({ direccion: e.target.value })} />
          </Campo>
          <Campo etiqueta="Tipo de proyecto">
            <select value={datos.tipo} onChange={(e) => cambiar({ tipo: e.target.value as BorradorEdificio["tipo"] })}>
              {Object.entries(TIPOS_EDIFICIO).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </Campo>
          <Campo etiqueta="Sistema de tensión">
            <select value={datos.sistema ?? "trifasico_127_220"} onChange={(e) => cambiar({ sistema: e.target.value })}>
              {opciones.sistemas.map((s) => (
                <option key={s.id} value={s.id}>{s.nombre}</option>
              ))}
            </select>
          </Campo>
          <Campo etiqueta="Respaldo con generador">
            <select value={datos.respaldo ?? "ninguno"} onChange={(e) => cambiar({ respaldo: e.target.value as BorradorEdificio["respaldo"] })}>
              <option value="ninguno">Sin generador</option>
              <option value="servicios_generales">Servicios generales</option>
              <option value="total">Todo el edificio</option>
            </select>
          </Campo>
        </div>
      </section>
      <section className="tarjeta">
        <h2>Recorridos</h2>
        <div className="rejilla">
          <Campo etiqueta="Piso del centro de medición" ayuda="0: planta baja; -1: subsuelo.">
            <input inputMode="numeric" value={datos.nivel_medidores ?? 0}
              onChange={(e) => cambiar({ nivel_medidores: Number(e.target.value) || 0 })} />
          </Campo>
          <Campo etiqueta="Altura entre pisos (m)" ayuda="Vacío: 3 m.">
            <input inputMode="decimal" value={datos.altura_piso_m ?? ""} onChange={(e) => cambiar({ altura_piso_m: decimal(e.target.value) })} />
          </Campo>
          <Campo etiqueta="Recorrido horizontal (m)" ayuda="Del ducto al tablero de cada unidad; vacío: 10 m.">
            <input inputMode="decimal" value={datos.recorrido_horizontal_m ?? ""}
              onChange={(e) => cambiar({ recorrido_horizontal_m: decimal(e.target.value) })} />
          </Campo>
          <Campo etiqueta="Transformador → centro de medición (m)" ayuda="Vacío: 15 m.">
            <input inputMode="decimal" value={datos.distancia_transformador_m ?? ""}
              onChange={(e) => cambiar({ distancia_transformador_m: decimal(e.target.value) })} />
          </Campo>
          <Campo etiqueta="Resistividad del suelo (Ω·m)" ayuda="Para la malla de la cámara, si la lleva; vacío: 100.">
            <input inputMode="decimal" value={datos.resistividad_ohm_m ?? ""}
              onChange={(e) => cambiar({ resistividad_ohm_m: decimal(e.target.value) })} />
          </Campo>
        </div>
      </section>
    </div>
  );
}

function CampoPisos({ pisos, cambiar }: { pisos: number[]; cambiar: (p: number[]) => void }) {
  const [texto, setTexto] = useState(escribirPisos(pisos));
  const valido = leerPisos(texto) !== null;
  return (
    <input
      className={valido ? undefined : "invalido"}
      value={texto}
      placeholder="1-8"
      aria-invalid={!valido}
      onChange={(e) => {
        setTexto(e.target.value);
        const leidos = leerPisos(e.target.value);
        if (leidos) cambiar(leidos);
      }}
    />
  );
}

function UnidadesServicios({
  datos,
  cambiar,
  opciones,
}: {
  datos: BorradorEdificio;
  cambiar: (p: Partial<BorradorEdificio>) => void;
  opciones: OpcionesEdificio;
}) {
  const estratos = opciones.usuarios.filter((u) => u.kva !== null);
  const cambiarUnidad = (i: number, parcial: Partial<Unidad>) =>
    cambiar({ unidades: datos.unidades.map((u, j) => (j === i ? { ...u, ...parcial } : u)) });
  const cambiarServicio = (i: number, parcial: Partial<Servicio>) =>
    cambiar({ servicios: datos.servicios.map((s, j) => (j === i ? { ...s, ...parcial } : s)) });
  const vacio = (v: string) => (v.trim() === "" ? null : v);
  return (
    <>
      <section className="tarjeta">
        <h2>Tipos de unidad</h2>
        <p className="tenue">
          Una fila por tipo que se repite. Pisos: «1-8», «0» (planta baja) o «1, 3, 5». Cada unidad recibe su número (101, 102…) y
          su medidor en el centro de medición.
        </p>
        <div className="tabla-ancha">
          <table className="editable">
            <thead>
              <tr>
                <th>Nombre</th><th>Uso</th><th>Estrato</th><th>Área (m²)</th><th>Demanda propia (kVA)</th>
                <th>Fases</th><th>Pisos</th><th>Por piso</th><th />
              </tr>
            </thead>
            <tbody>
              {datos.unidades.map((u, i) => (
                <tr key={i}>
                  <td><input value={u.id} onChange={(e) => cambiarUnidad(i, { id: e.target.value })} /></td>
                  <td>
                    <select value={u.uso ?? "departamento"} onChange={(e) => cambiarUnidad(i, { uso: e.target.value as Unidad["uso"] })}>
                      <option value="departamento">Departamento</option>
                      <option value="local">Local</option>
                      <option value="oficina">Oficina</option>
                      <option value="bodega">Bodega</option>
                    </select>
                  </td>
                  <td>
                    <select value={u.estrato ?? "C"} disabled={u.uso !== "departamento" && u.uso !== undefined}
                      onChange={(e) => cambiarUnidad(i, { estrato: e.target.value })}>
                      {estratos.map((s) => (
                        <option key={s.id} value={s.id} title={s.nombre}>{s.id} · {num(s.kva)} kVA</option>
                      ))}
                    </select>
                  </td>
                  <td><input inputMode="decimal" value={u.area_m2 ?? ""} onChange={(e) => cambiarUnidad(i, { area_m2: vacio(e.target.value) })} /></td>
                  <td><input inputMode="decimal" value={u.demanda_kva ?? ""} placeholder="de la tabla"
                    onChange={(e) => cambiarUnidad(i, { demanda_kva: vacio(e.target.value) })} /></td>
                  <td>
                    <select value={u.fases ?? 2} onChange={(e) => cambiarUnidad(i, { fases: Number(e.target.value) as 1 | 2 | 3 })}>
                      <option value={1}>1F 127 V</option>
                      <option value={2}>2F 220 V</option>
                      <option value={3}>3F 220 V</option>
                    </select>
                  </td>
                  <td><CampoPisos pisos={u.pisos} cambiar={(p) => cambiarUnidad(i, { pisos: p })} /></td>
                  <td><input inputMode="numeric" value={u.por_piso ?? 1}
                    onChange={(e) => cambiarUnidad(i, { por_piso: Math.max(1, Number(e.target.value) || 1) })} /></td>
                  <td>
                    <button className="discreto" onClick={() => cambiar({ unidades: datos.unidades.filter((_, j) => j !== i) })}>Quitar</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button onClick={() => cambiar({ unidades: [...datos.unidades, nuevaUnidad(datos.tipo, datos.unidades.length + 1)] })}>
          Agregar tipo de unidad
        </button>
        <p className="tenue">
          Departamentos: demanda máxima unitaria del estrato. Locales y oficinas: área × densidad de carga ({opciones.usuarios
            .filter((u) => u.va_m2)
            .map((u) => `${u.id} ${num(u.va_m2, 0)} VA/m²`)
            .join(", ")}). «Demanda propia» reemplaza ambos, por ejemplo con la demanda calculada del plano del departamento.
        </p>
      </section>
      <section className="tarjeta">
        <h2>Servicios generales</h2>
        <div className="tabla-ancha">
          <table className="editable">
            <thead>
              <tr><th>Carga</th><th>kW</th><th>Cantidad</th><th>FP</th><th>Motor</th><th>En generador</th><th /></tr>
            </thead>
            <tbody>
              {datos.servicios.map((s, i) => (
                <tr key={i}>
                  <td><input value={s.descripcion} onChange={(e) => cambiarServicio(i, { descripcion: e.target.value })} /></td>
                  <td><input inputMode="decimal" value={s.kw} onChange={(e) => cambiarServicio(i, { kw: e.target.value })} /></td>
                  <td><input inputMode="numeric" value={s.cantidad ?? 1}
                    onChange={(e) => cambiarServicio(i, { cantidad: Math.max(1, Number(e.target.value) || 1) })} /></td>
                  <td><input inputMode="decimal" value={s.fp ?? "0.85"} onChange={(e) => cambiarServicio(i, { fp: e.target.value })} /></td>
                  <td><input type="checkbox" checked={s.motor ?? false} onChange={(e) => cambiarServicio(i, { motor: e.target.checked })} /></td>
                  <td><input type="checkbox" checked={s.respaldo ?? true} onChange={(e) => cambiarServicio(i, { respaldo: e.target.checked })} /></td>
                  <td>
                    <button className="discreto" onClick={() => cambiar({ servicios: datos.servicios.filter((_, j) => j !== i) })}>Quitar</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="acciones izquierda">
          {[
            ["Ascensor", "7.5", true],
            ["Bomba de agua", "3.7", true],
            ["Iluminación de áreas comunes", "3", false],
          ].map(([d, kw, motor]) => (
            <button key={String(d)}
              onClick={() => cambiar({ servicios: [...datos.servicios, { descripcion: String(d), kw: String(kw), motor: Boolean(motor), cantidad: 1, fp: motor ? "0.85" : "0.95", respaldo: true }] })}>
              + {String(d)}
            </button>
          ))}
          <button onClick={() => cambiar({ servicios: [...datos.servicios, { descripcion: "Carga", kw: "1", cantidad: 1, fp: "0.9", motor: false, respaldo: true }] })}>
            + Otra carga
          </button>
        </div>
      </section>
    </>
  );
}

function ResumenEdificio({ c }: { c: CalculoEdificio }) {
  return (
    <div className="resumen compacto franja">
      <div className="dato"><span className="etiqueta">Demanda</span><span className="valor">{num(c.demanda_kva)} kVA</span></div>
      <div className="dato"><span className="etiqueta">Unidades</span><span className="valor">{c.unidades.length}</span></div>
      <div className="dato">
        <span className="etiqueta">Transformador</span>
        <span className="valor">{c.transformador ? `${num(c.transformador.kva)} kVA (${c.transformador.montaje})` : "Red de CNEL"}</span>
      </div>
      <div className="dato"><span className="etiqueta">Breaker principal</span><span className="valor">{c.principal?.breaker_a ? `${num(c.principal.breaker_a, 0)} A` : "—"}</span></div>
      <div className="dato"><span className="etiqueta">Medidores</span><span className="valor">{c.medidores}</span></div>
      {c.generador ? (
        <div className="dato"><span className="etiqueta">Generador</span><span className="valor">{c.generador.kva ? `${num(c.generador.kva, 0)} kVA` : "—"}</span></div>
      ) : null}
    </div>
  );
}

function Demanda({ c }: { c: CalculoEdificio }) {
  return (
    <>
      <div className="columnas dos">
        <section className="tarjeta">
          <h2>Demanda coincidente</h2>
          <div className="tabla-ancha">
          <table>
            <thead>
              <tr><th>Grupo</th><th className="num">Usuarios</th><th className="num">Σ demandas (kVA)</th><th className="num">FC</th><th className="num">Demanda (kVA)</th></tr>
            </thead>
            <tbody>
              {c.grupos.map((g) => (
                <tr key={g.nombre}>
                  <td>{g.nombre}</td><td className="num">{g.usuarios}</td><td className="num">{num(g.suma_kva)}</td>
                  <td className="num">{num(g.factor, 2)}</td><td className="num">{num(g.demanda_kva)}</td>
                </tr>
              ))}
              {c.servicios ? (
                <tr>
                  <td>Servicios generales</td><td className="num">1</td><td className="num">{num(c.servicios.instalada_kva)}</td>
                  <td className="num">fd</td><td className="num">{num(c.servicios.demanda_kva)}</td>
                </tr>
              ) : null}
              <tr className="total">
                <td>Total ({num(c.demanda_kw)} kW)</td><td /><td /><td /><td className="num">{num(c.demanda_kva)}</td>
              </tr>
            </tbody>
          </table>
          </div>
          <p className="tenue">Factores de coincidencia y demandas unitarias del perfil, por verificar con CNEL.</p>
        </section>
        <section className={`tarjeta decision ${c.transformador ? "particular" : "existente"}`}>
          <h2>Nivel de servicio</h2>
          <p className="cifra-media">{c.nivel}</p>
          {c.transformador ? (
            <p>
              Transformador trifásico de <strong>{num(c.transformador.kva)} kVA</strong> en {c.transformador.montaje}
              , Z = {num(c.transformador.z_pct, 2)} %. Medición en {c.medicion.toUpperCase()}.
              {c.camara ? " Requiere cámara de transformación (pestaña «Cámara MT»)." : ""}
            </p>
          ) : (
            <p>Atención desde la red de baja tensión de CNEL, sujeta a factibilidad.</p>
          )}
          {c.generador ? (
            <p>
              Generador de <strong>{c.generador.kva ? `${num(c.generador.kva, 0)} kVA` : "fuera de serie"}</strong> para{" "}
              {c.generador.alcance} ({num(c.generador.carga_kva)} kVA respaldados), con transferencia automática de{" "}
              {c.generador.transferencia_a ? `${num(c.generador.transferencia_a, 0)} A` : "—"}.
            </p>
          ) : null}
        </section>
      </div>
      {c.avisos.length ? (
        <Aviso tipo="alerta"><ul>{c.avisos.map((a) => <li key={a}>{a}</li>)}</ul></Aviso>
      ) : null}
    </>
  );
}

function Medicion({ c }: { c: CalculoEdificio }) {
  const p = c.principal;
  return (
    <section className="tarjeta">
      <h2>Centro de medición</h2>
      <p>
        {c.medidores} medidores en {c.modulos} módulo{c.modulos > 1 ? "s" : ""}. Acometida{" "}
        <strong>{p?.conductor ?? "sin solución"}</strong> ({num(p?.longitud_m, 0)} m, ΔV {num(p?.caida_pct, 2)} %), breaker principal{" "}
        <strong>{p?.breaker_a ? `3P ${num(p.breaker_a, 0)} A` : "fuera de serie"}</strong>, barra {p?.barra_a ? `${num(p.barra_a, 0)} A` : "—"}
        {p?.icc_ka ? `, Icc ${num(p.icc_ka, 1)} kA` : ""}.
      </p>
      <div className="tabla-ancha">
        <table>
          <thead>
            <tr>
              <th>Unidad</th><th>Tipo</th><th className="num">Piso</th><th className="num">Demanda (kVA)</th><th className="num">I (A)</th>
              <th>Breaker</th><th>Medidor</th><th>Alimentador</th><th className="num">L (m)</th><th className="num">ΔV %</th>
            </tr>
          </thead>
          <tbody>
            {c.servicios ? (
              <tr>
                <td>SG</td><td>Servicios generales</td><td className="num">—</td><td className="num">{num(c.servicios.demanda_kva)}</td>
                <td className="num">{num(c.servicios.corriente_a)}</td><td>3P {num(c.servicios.breaker_a, 0)} A</td>
                <td>{c.servicios.medidor}</td><td>{c.servicios.conductor ?? "sin solución"}</td><td /><td />
              </tr>
            ) : null}
            {c.unidades.map((u) => (
              <tr key={u.id}>
                <td>{u.id}</td><td>{u.tipo}</td><td className="num">{u.piso}</td><td className="num">{num(u.demanda_kva)}</td>
                <td className="num">{num(u.corriente_a)}</td><td>{u.fases}P {u.breaker_a ? `${num(u.breaker_a, 0)} A` : "fuera de serie"}</td>
                <td>{u.medidor}</td><td className={u.conductor ? undefined : "mal"}>{u.conductor ?? "sin solución"}</td>
                <td className="num">{num(u.longitud_m, 0)}</td><td className="num">{num(u.caida_pct, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="tenue">Alimentadores al 125 % de la corriente y caída menor a la mitad del margen de alimentadores (1 %).</p>
    </section>
  );
}
