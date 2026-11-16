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

export interface Elegido {
  id: string;
  tipo: string;
  circuito: string;
  altura: string;
  ambiente: string;
}

interface Props {
  fondo: Fondo | undefined;
  plano: Plano;
  datos: Borrador;
  capas: Capas;
  /** Circuito resaltado; los demás se atenúan. */
  resaltado: string | null;
  elegido: string | null;
  elegir: (elemento: Elegido | null) => void;
}

type Caja = [number, number, number, number];
const R = 0.12; // radio de símbolo, en metros
const n = (v: number | string) => Number(v);

export function Visor({ fondo, plano, datos, capas, resaltado, elegido, elegir }: Props) {
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
  const arrastre = useRef<{ x: number; y: number; caja: Caja; movido: boolean } | null>(null);

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
    arrastre.current = { x: e.clientX, y: e.clientY, caja, movido: false };
  };
  const alMover = (e: PointerEvent<SVGSVGElement>) => {
    const a = arrastre.current;
    const r = svg.current?.getBoundingClientRect();
    if (!a || !r) return;
    const [dx, dy] = [e.clientX - a.x, e.clientY - a.y];
    if (Math.abs(dx) + Math.abs(dy) < 4 && !a.movido) return;
    a.movido = true;
    const escala = Math.max(a.caja[2] / r.width, a.caja[3] / r.height);
    setCaja([a.caja[0] - dx * escala, a.caja[1] - dy * escala, a.caja[2], a.caja[3]]);
  };
  const alSoltar = () => {
    if (arrastre.current && !arrastre.current.movido) elegir(null);
    arrastre.current = null;
  };

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
  const nombreAmbiente = new Map(plano.ambientes.map((a) => [a.id, a.nombre || a.id]));
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
        onPointerLeave={() => (arrastre.current = null)}
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
          const [x, y] = [n(u.x), -n(u.y)];
          const circuito = circuitoDe.get(u.id) ?? "";
          const esTablero = u.id === (datos.tablero?.id ?? "TD-1");
          const esEspecial = especiales.has(u.id);
          const tipo = esTablero ? "tablero" : tipoDe.get(u.id);
          if (!tipo) return null; // ubicación de un punto que ya no existe
          const esLuz = tipo === "punto_luz";
          const visible = esTablero || (esEspecial ? capas.especiales : esLuz ? capas.iluminacion : capas.tomas);
          if (!visible) return null;
          const trazo = esTablero ? "#c62828" : color(circuito);
          const info: Elegido = {
            id: u.id,
            tipo: esTablero ? "Tablero de distribución" : esEspecial ? `Carga especial: ${tipo}` : esLuz ? "Luminaria" : "Tomacorriente",
            circuito,
            altura: String(u.altura_m),
            ambiente: nombreAmbiente.get(u.ambiente ?? "") ?? "",
          };
          return (
            <g
              key={u.id}
              className={`simbolo ${elegido === u.id ? "elegido" : ""}`}
              stroke={trazo}
              opacity={esTablero ? 1 : tenue(circuito)}
              onPointerUp={(e) => {
                if (arrastre.current?.movido) return;
                e.stopPropagation();
                arrastre.current = null;
                elegir(info);
              }}
            >
              <title>{`${u.id} · ${info.tipo}${circuito ? ` · ${circuito}` : ""}`}</title>
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
              const [x, y] = [n(s.x), -n(s.y)];
              return (
                <g key={s.id} className="simbolo" stroke={color(s.circuito)} opacity={tenue(s.circuito)}>
                  <title>{`${s.id} · Interruptor · ${s.circuito}`}</title>
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
