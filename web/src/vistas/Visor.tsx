import { type PointerEvent, useMemo, useRef, useState, type WheelEvent } from "react";
import type { Borrador, Fondo, Plano } from "../api/cliente";

export const COLORES = [
  "#d62728", "#2ca02c", "#1f77b4", "#9467bd", "#e6850e",
  "#17a2b8", "#c2185b", "#6d8f00", "#8c564b", "#5c6bc0",
];

export interface Capas {
  plano: boolean;
  ambientes: boolean;
  iluminacion: boolean;
  tomas: boolean;
  especiales: boolean;
  recorridos: boolean;
}

interface Props {
  fondo: Fondo | undefined;
  plano: Plano;
  datos: Borrador;
  capas: Capas;
  /** Circuito resaltado; los demás se atenúan. */
  resaltado: string | null;
  elegido: string | null;
  elegir: (id: string | null) => void;
  /** Si se puede arrastrar símbolos; `mover` recibe la posición en metros. */
  editable?: boolean;
  mover?: (id: string, x: number, y: number) => Promise<unknown>;
  /** Con un tipo de punto elegido, tocar el plano lo agrega ahí. */
  agregando?: string | null;
  agregarEn?: (x: number, y: number) => void;
}

type Arrastre =
  | { modo: "vista"; x: number; y: number; caja: Caja; movido: boolean }
  | { modo: "simbolo"; id: string; x: number; y: number; movido: boolean };

type Caja = [number, number, number, number];
const R = 0.12; // radio de símbolo, en metros
const n = (v: number | string) => Number(v);

export function Visor({
  fondo, plano, datos, capas, resaltado, elegido, elegir, editable = false, mover, agregando = null, agregarEn,
}: Props) {
  // El plano tiene el eje Y hacia arriba; SVG, hacia abajo: todo se dibuja con y negada.
  const inicial = useMemo<Caja>(() => {
    const xs = plano.ambientes.flatMap((a) => a.poligono.map((p) => n(p.x)));
    const ys = plano.ambientes.flatMap((a) => a.poligono.map((p) => n(p.y)));
    if (!xs.length) return [0, -10, 10, 10];
    const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const m = 0.8;
    return [x0 - m, -(y1 + m), x1 - x0 + 2 * m, y1 - y0 + 2 * m];
  }, [plano.ambientes]);
  const [caja, setCaja] = useState<Caja>(inicial);
  const svg = useRef<SVGSVGElement>(null);
  const arrastre = useRef<Arrastre | null>(null);
  // Posición provisional del símbolo que se arrastra, hasta que el servidor responde.
  const [fantasma, setFantasma] = useState<{ id: string; x: number; y: number } | null>(null);

  /** Del puntero a metros del plano, redondeado al centímetro. */
  const aMundo = (clientX: number, clientY: number): [number, number] | null => {
    const s = svg.current;
    const m = s?.getScreenCTM();
    if (!s || !m) return null;
    const p = new DOMPoint(clientX, clientY).matrixTransform(m.inverse());
    return [Math.round(p.x * 100) / 100, Math.round(-p.y * 100) / 100];
  };

  const acercar = (factor: number, cx = caja[0] + caja[2] / 2, cy = caja[1] + caja[3] / 2) =>
    setCaja(([x, y, w, h]) => {
      const nw = Math.min(Math.max(w * factor, 1), inicial[2] * 4);
      const k = nw / w;
      return [cx - (cx - x) * k, cy - (cy - y) * k, nw, h * k];
    });

  const alRodar = (e: WheelEvent<SVGSVGElement>) => {
    const r = svg.current?.getBoundingClientRect();
    if (!r) return;
    const escala = Math.max(caja[2] / r.width, caja[3] / r.height);
    const cx = caja[0] + caja[2] / 2 + (e.clientX - r.left - r.width / 2) * escala;
    const cy = caja[1] + caja[3] / 2 + (e.clientY - r.top - r.height / 2) * escala;
    acercar(e.deltaY > 0 ? 1.15 : 1 / 1.15, cx, cy);
  };
  const alBajar = (e: PointerEvent<SVGSVGElement>) => {
    arrastre.current = { modo: "vista", x: e.clientX, y: e.clientY, caja, movido: false };
  };
  const tomarSimbolo = (id: string) => (e: PointerEvent<SVGGElement>) => {
    e.stopPropagation();
    arrastre.current = { modo: "simbolo", id, x: e.clientX, y: e.clientY, movido: false };
    if (editable) svg.current?.setPointerCapture?.(e.pointerId);
  };
  const alMover = (e: PointerEvent<SVGSVGElement>) => {
    const a = arrastre.current;
    const r = svg.current?.getBoundingClientRect();
    if (!a || !r) return;
    const [dx, dy] = [e.clientX - a.x, e.clientY - a.y];
    if (Math.abs(dx) + Math.abs(dy) < 4 && !a.movido) return;
    if (a.modo === "simbolo") {
      if (!editable) return;
      a.movido = true;
      const p = aMundo(e.clientX, e.clientY);
      if (p) setFantasma({ id: a.id, x: p[0], y: p[1] });
      return;
    }
    a.movido = true;
    const escala = Math.max(a.caja[2] / r.width, a.caja[3] / r.height);
    setCaja([a.caja[0] - dx * escala, a.caja[1] - dy * escala, a.caja[2], a.caja[3]]);
  };
  const alSoltar = (e: PointerEvent<SVGSVGElement>) => {
    const a = arrastre.current;
    arrastre.current = null;
    if (!a) return;
    if (a.modo === "simbolo") {
      if (!a.movido) {
        elegir(a.id);
        return;
      }
      const p = aMundo(e.clientX, e.clientY);
      if (p && mover) {
        elegir(a.id);
        void mover(a.id, p[0], p[1]).finally(() => setFantasma(null));
      } else setFantasma(null);
      return;
    }
    if (a.movido) return;
    const p = aMundo(e.clientX, e.clientY);
    if (agregando && agregarEn && p) agregarEn(p[0], p[1]);
    else elegir(null);
  };
  const donde = (id: string, x: number | string, y: number | string): [number, number] =>
    fantasma?.id === id ? [fantasma.x, -fantasma.y] : [n(x), -n(y)];
  const fijos = new Set([
    ...(plano.ubicaciones ?? []).filter((u) => u.fijo).map((u) => u.id),
    ...(plano.interruptores ?? []).filter((s) => s.fijo).map((s) => s.id),
  ]);

  const orden = new Map(datos.circuitos.map((c, i) => [c.id, i]));
  const color = (circuito: string) => COLORES[(orden.get(circuito) ?? 0) % COLORES.length];
  const circuitoDe = new Map<string, string>([
    ...datos.puntos.map((p) => [p.id, p.circuito] as const),
    ...datos.cargas_especiales.map((c) => [c.id, c.circuito] as const),
  ]);
  const tipoDe = new Map<string, string>([
    ...datos.puntos.map((p) => [p.id, p.tipo] as const),
    ...datos.cargas_especiales.map((c) => [c.id, c.tipo] as const),
  ]);
  const especiales = new Set(datos.cargas_especiales.map((c) => c.id));
  const tenue = (circuito: string) => (resaltado && resaltado !== circuito ? 0.15 : 1);
  const puntos = (lista: { x: number | string; y: number | string }[]) =>
    lista.map((p) => `${n(p.x)},${-n(p.y)}`).join(" ");

  return (
    <div className="visor">
      <div className="controles-visor">
        <button aria-label="Acercar" onClick={() => acercar(1 / 1.3)}>+</button>
        <button aria-label="Alejar" onClick={() => acercar(1.3)}>−</button>
        <button onClick={() => setCaja(inicial)}>Ajustar</button>
      </div>
      <svg
        ref={svg}
        viewBox={caja.join(" ")}
        onWheel={alRodar}
        onPointerDown={alBajar}
        onPointerMove={alMover}
        onPointerUp={alSoltar}
        onPointerCancel={() => {
          arrastre.current = null;
          setFantasma(null);
        }}
        className={agregando ? "agregando" : editable ? "editable" : ""}
        role="img"
        aria-label="Plano con la instalación eléctrica"
      >
        {capas.ambientes
          ? plano.ambientes.map((a) => (
              <polygon key={a.id} className={`ambiente ${a.banderas?.length ? "dudoso" : ""}`} points={puntos(a.poligono)}>
                <title>{`${a.id} · ${a.nombre || "sin nombre"} · ${a.uso} · ${a.area_m2} m²`}</title>
              </polygon>
            ))
          : null}

        {capas.plano && fondo
          ? fondo.lineas.map((l, i) => (
              <polyline
                key={i}
                className={`fondo ${l.clase}`}
                points={l.puntos.map(([x, y]) => `${x},${-y}`).join(" ")}
              />
            ))
          : null}

        {capas.ambientes
          ? plano.ambientes.map((a) => {
              const cx = a.poligono.reduce((s, p) => s + n(p.x), 0) / a.poligono.length;
              const cy = a.poligono.reduce((s, p) => s + n(p.y), 0) / a.poligono.length;
              return (
                <text key={a.id} className="rotulo" x={cx} y={-cy} textAnchor="middle">
                  <tspan x={cx} dy="-0.05">{a.nombre || a.id}</tspan>
                  <tspan x={cx} dy="0.26" className="menor">{String(a.area_m2).replace(".", ",")} m²</tspan>
                </text>
              );
            })
          : null}

        {capas.recorridos
          ? plano.recorridos?.map((r) => (
              <g key={r.circuito} stroke={color(r.circuito)} opacity={tenue(r.circuito)} className="recorrido">
                <polyline points={puntos(r.puntos)} />
                {r.derivaciones?.map(([a, b], i) => (
                  <line key={i} x1={n(a.x)} y1={-n(a.y)} x2={n(b.x)} y2={-n(b.y)} className="derivacion" />
                ))}
              </g>
            ))
          : null}

        {plano.ubicaciones?.map((u) => {
          const [x, y] = donde(u.id, u.x, u.y);
          const circuito = circuitoDe.get(u.id) ?? "";
          const esTablero = u.id === (datos.tablero?.id ?? "TD-1");
          const esEspecial = especiales.has(u.id);
          const tipo = esTablero ? "tablero" : tipoDe.get(u.id);
          if (!tipo) return null; // ubicación de un punto que ya no existe
          const esLuz = tipo === "punto_luz";
          const visible = esTablero || (esEspecial ? capas.especiales : esLuz ? capas.iluminacion : capas.tomas);
          if (!visible) return null;
          const trazo = esTablero ? "#c62828" : color(circuito);
          const nombre = esTablero ? "Tablero" : esEspecial ? tipo : esLuz ? "Luminaria" : "Tomacorriente";
          return (
            <g
              key={u.id}
              className={`simbolo ${elegido === u.id ? "elegido" : ""} ${fantasma?.id === u.id ? "arrastrado" : ""}`}
              stroke={trazo}
              opacity={esTablero ? 1 : tenue(circuito)}
              onPointerDown={tomarSimbolo(u.id)}
              data-id={u.id}
            >
              <title>{`${u.id} · ${nombre}${circuito ? ` · ${circuito}` : ""}${fijos.has(u.id) ? " · fijado" : ""}`}</title>
              {fijos.has(u.id) ? <circle className="pin" cx={x + R * 1.1} cy={y - R * 1.1} r={R * 0.32} /> : null}
              {esTablero ? (
                <>
                  <rect x={x - R * 2} y={y - R} width={R * 4} height={R * 2} style={{ fill: "#c62828" }} />
                  <text x={x + R * 2.4} y={y + R * 0.5} className="etiqueta-tablero">{u.id}</text>
                </>
              ) : esEspecial ? (
                <>
                  <rect x={x - R} y={y - R} width={R * 2} height={R * 2} />
                  <line x1={x - R} y1={y + R} x2={x + R} y2={y - R} />
                </>
              ) : esLuz ? (
                <>
                  <circle cx={x} cy={y} r={R} />
                  <line x1={x - R * 0.7} y1={y - R * 0.7} x2={x + R * 0.7} y2={y + R * 0.7} />
                  <line x1={x - R * 0.7} y1={y + R * 0.7} x2={x + R * 0.7} y2={y - R * 0.7} />
                </>
              ) : (
                <>
                  <circle cx={x} cy={y} r={R} />
                  <line x1={x - R * 0.4} y1={y - R * 0.6} x2={x - R * 0.4} y2={y + R * 0.6} />
                  <line x1={x + R * 0.4} y1={y - R * 0.6} x2={x + R * 0.4} y2={y + R * 0.6} />
                </>
              )}
            </g>
          );
        })}

        {capas.iluminacion
          ? plano.interruptores?.map((s) => {
              const [x, y] = donde(s.id, s.x, s.y);
              return (
                <g
                  key={s.id}
                  className={`simbolo ${elegido === s.id ? "elegido" : ""} ${fantasma?.id === s.id ? "arrastrado" : ""}`}
                  stroke={color(s.circuito)}
                  opacity={tenue(s.circuito)}
                  onPointerDown={tomarSimbolo(s.id)}
                  data-id={s.id}
                >
                  <title>{`${s.id} · Interruptor · ${s.circuito}${fijos.has(s.id) ? " · fijado" : ""}`}</title>
                  {fijos.has(s.id) ? <circle className="pin" cx={x + R} cy={y + R} r={R * 0.32} /> : null}
                  <circle cx={x} cy={y} r={R * 0.55} />
                  <polyline points={`${x + R * 0.4},${y - R * 0.4} ${x + R * 1.3},${y - R * 1.3} ${x + R * 1.7},${y - R * 0.9}`} />
                </g>
              );
            })
          : null}
      </svg>
    </div>
  );
}
