import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";
import type { RedExistente } from "../api/cliente";

export interface PuntoMapa {
  id: string;
  lat: number;
  lon: number;
  transformador?: boolean;
}

interface Props {
  arranque: { lat: number; lon: number; poste?: string | null } | null;
  postes: PuntoMapa[];
  existente: RedExistente | null;
  /** Qué hace un clic en el mapa. */
  modo: "arranque" | "postes" | "mirar";
  alClic: (lat: number, lon: number) => void;
  alMover: (id: string, lat: number, lon: number) => void;
  alElegirExistente: (poste: { id: string; lat: number; lon: number; alimentador?: string | null }) => void;
}

const CENTRO: L.LatLngTuple = [-2.17, -79.92];

const icono = (texto: string, clase: string) =>
  L.divIcon({ className: `marca-mapa ${clase}`, html: `<span>${texto}</span>`, iconSize: [22, 22] });

/** Mapa de OpenStreetMap con la red existente en gris y la extensión nueva. */
export function Mapa({ arranque, postes, existente, modo, alClic, alMover, alElegirExistente }: Props) {
  const contenedor = useRef<HTMLDivElement>(null);
  const mapa = useRef<L.Map | null>(null);
  const capas = useRef<L.LayerGroup | null>(null);
  const centrado = useRef(false);
  // Los manejadores cambian en cada render; el mapa usa siempre los últimos.
  const manejadores = useRef({ alClic, alMover, alElegirExistente, modo });
  manejadores.current = { alClic, alMover, alElegirExistente, modo };

  useEffect(() => {
    if (!contenedor.current || mapa.current) return;
    const m = L.map(contenedor.current, { zoomControl: true }).setView(CENTRO, 16);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 20,
      maxNativeZoom: 19,
      attribution: "© OpenStreetMap",
    }).addTo(m);
    m.on("click", (e: L.LeafletMouseEvent) => {
      if (manejadores.current.modo !== "mirar") manejadores.current.alClic(e.latlng.lat, e.latlng.lng);
    });
    capas.current = L.layerGroup().addTo(m);
    mapa.current = m;
    return () => {
      m.remove();
      mapa.current = null;
    };
  }, []);

  useEffect(() => {
    const m = mapa.current;
    const grupo = capas.current;
    if (!m || !grupo) return;
    grupo.clearLayers();
    const limites: L.LatLngExpression[] = [];

    for (const tramo of existente?.tramos ?? []) {
      const linea = tramo.puntos.map((c) => [Number(c.lat), Number(c.lon)] as L.LatLngTuple);
      L.polyline(linea, { color: "#7a8494", weight: 3, opacity: 0.8 })
        .bindTooltip(`${tramo.id}${tramo.conductor ? ` · ${tramo.conductor}` : ""}`)
        .addTo(grupo);
    }
    for (const poste of existente?.postes ?? []) {
      const lat = Number(poste.lat);
      const lon = Number(poste.lon);
      limites.push([lat, lon]);
      L.circleMarker([lat, lon], { radius: 5, color: "#5b6878", fillColor: "#c9d0da", fillOpacity: 1 })
        .bindTooltip(`${poste.id}${poste.estructura ? ` · ${poste.estructura}` : ""} (clic: arranque)`)
        .on("click", (e) => {
          L.DomEvent.stopPropagation(e);
          manejadores.current.alElegirExistente({ id: poste.id, lat, lon, alimentador: poste.alimentador });
        })
        .addTo(grupo);
    }
    for (const trafo of existente?.transformadores ?? []) {
      L.marker([Number(trafo.lat), Number(trafo.lon)], { icon: icono("T", "existente"), interactive: false })
        .bindTooltip(`${trafo.id} ${trafo.kva ?? ""} kVA`)
        .addTo(grupo);
    }

    const ruta: L.LatLngTuple[] = [];
    if (arranque) {
      ruta.push([arranque.lat, arranque.lon]);
      limites.push([arranque.lat, arranque.lon]);
      L.marker([arranque.lat, arranque.lon], { icon: icono("A", "arranque"), keyboard: false })
        .bindTooltip(`Arranque${arranque.poste ? ` ${arranque.poste}` : ""}`)
        .addTo(grupo);
    }
    postes.forEach((p, n) => {
      ruta.push([p.lat, p.lon]);
      limites.push([p.lat, p.lon]);
      const marcador = L.marker([p.lat, p.lon], {
        icon: icono(String(n + 1), p.transformador ? "nuevo transformador" : "nuevo"),
        draggable: true,
        keyboard: false,
      })
        .bindTooltip(p.id)
        .on("dragend", () => {
          const ll = marcador.getLatLng();
          manejadores.current.alMover(p.id, ll.lat, ll.lng);
        })
        .addTo(grupo);
    });
    if (ruta.length > 1) L.polyline(ruta, { color: "#d62828", weight: 4 }).addTo(grupo);

    if (!centrado.current && limites.length) {
      m.fitBounds(L.latLngBounds(limites), { padding: [40, 40], maxZoom: 18 });
      centrado.current = true;
    }
  }, [arranque, postes, existente]);

  return <div ref={contenedor} className={`mapa modo-${modo}`} role="application" aria-label="Mapa de la red" />;
}
