import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api/cliente";
import { Asistente } from "./vistas/Asistente";
import { MensajeError } from "./vistas/comunes";
import { Edificacion } from "./vistas/Edificacion";
import { Edificio } from "./vistas/Edificio";
import { Editor } from "./vistas/Editor";
import { Industria } from "./vistas/Industria";
import { Inicio } from "./vistas/Inicio";
import { PaginaIndustrias, PaginaNoResidencial, PaginaPisos, PaginaRedesMT, Viviendas } from "./vistas/Lista";
import { RedMT } from "./vistas/RedMT";

type Modulo = "inicio" | "viviendas" | "pisos" | "industrias" | "no-residencial" | "redes-mt";

type Ruta =
  | { vista: "modulo"; modulo: Modulo }
  | { vista: "nuevo" }
  | { vista: "proyecto" | "asistente"; id: string }
  | { vista: "industria" | "edificacion" | "red-mt" | "edificio"; id: string; pestana?: string };

const MODULOS: Modulo[] = ["viviendas", "pisos", "industrias", "no-residencial", "redes-mt"];

const leerRuta = (): Ruta => {
  const hash = window.location.hash;
  if (hash === "#/nuevo") return { vista: "nuevo" };
  const asistente = hash.match(/^#\/proyectos\/([^/]+)\/asistente$/);
  if (asistente) return { vista: "asistente", id: asistente[1] };
  const edificacion = hash.match(/^#\/edificaciones\/([^/]+)(?:\/([\w-]+))?$/);
  if (edificacion) return { vista: "edificacion", id: edificacion[1], pestana: edificacion[2] };
  const edificio = hash.match(/^#\/edificios\/([^/]+)(?:\/([\w-]+))?$/);
  if (edificio) return { vista: "edificio", id: edificio[1], pestana: edificio[2] };
  const redMT = hash.match(/^#\/redes-mt\/([^/]+)(?:\/([\w-]+))?$/);
  if (redMT) return { vista: "red-mt", id: redMT[1], pestana: redMT[2] };
  const industria = hash.match(/^#\/industrias\/([^/]+)(?:\/([\w-]+))?$/);
  if (industria) return { vista: "industria", id: industria[1], pestana: industria[2] };
  const proyecto = hash.match(/^#\/proyectos\/([^/]+)$/);
  if (proyecto) return { vista: "proyecto", id: proyecto[1] };
  const modulo = hash.match(/^#\/([\w-]+)$/)?.[1] as Modulo | undefined;
  return { vista: "modulo", modulo: modulo && MODULOS.includes(modulo) ? modulo : "inicio" };
};

/** Módulo al que pertenece la ruta, para marcarlo en el menú. */
const moduloDe = (ruta: Ruta): Modulo => {
  if (ruta.vista === "modulo") return ruta.modulo;
  if (ruta.vista === "industria") return "industrias";
  if (ruta.vista === "edificacion") return "pisos";
  if (ruta.vista === "red-mt") return "redes-mt";
  if (ruta.vista === "edificio") return "no-residencial";
  return "viviendas";
};

const MENU: { modulo: Modulo; titulo: string; icono: string; pronto?: boolean }[] = [
  { modulo: "inicio", titulo: "Inicio", icono: "⌂" },
  { modulo: "viviendas", titulo: "Viviendas", icono: "▭" },
  { modulo: "pisos", titulo: "Varios pisos", icono: "☰" },
  { modulo: "industrias", titulo: "Industrias", icono: "⚙" },
  { modulo: "no-residencial", titulo: "No residencial", icono: "▦" },
  { modulo: "redes-mt", titulo: "Redes MT", icono: "⚡" },
];

function AsistenteDe({ id }: { id: string }) {
  const proyecto = useQuery({ queryKey: ["proyecto", id], queryFn: () => api.proyecto(id) });
  if (proyecto.isError) return <div className="pagina"><MensajeError error={proyecto.error} /></div>;
  if (!proyecto.data) return <div className="pagina">Cargando…</div>;
  return <Asistente proyecto={proyecto.data} />;
}

export function App() {
  const [ruta, setRuta] = useState(leerRuta);

  useEffect(() => {
    const alCambiar = () => setRuta(leerRuta());
    window.addEventListener("hashchange", alCambiar);
    return () => window.removeEventListener("hashchange", alCambiar);
  }, []);

  const actual = moduloDe(ruta);

  return (
    <div className="marco">
      <aside className="lateral">
        <a className="marca" href="#/">
          Electric
        </a>
        <span className="lema">Proyectos eléctricos CNEL EP</span>
        <nav aria-label="Módulos">
          {MENU.map((m) => (
            <a
              key={m.modulo}
              href={m.modulo === "inicio" ? "#/" : `#/${m.modulo}`}
              className={`enlace-modulo${m.modulo === actual ? " activo" : ""}`}
              aria-current={m.modulo === actual ? "page" : undefined}
            >
              <span className="icono" aria-hidden="true">
                {m.icono}
              </span>
              {m.titulo}
              {m.pronto ? <span className="pronto-chip">pronto</span> : null}
            </a>
          ))}
        </nav>
        <p className="pie-lateral">Resultados en borrador: requieren revisión y firma de un profesional habilitado.</p>
      </aside>
      <main>
        {ruta.vista === "proyecto" ? <Editor key={ruta.id} id={ruta.id} /> : null}
        {ruta.vista === "asistente" ? <AsistenteDe key={ruta.id} id={ruta.id} /> : null}
        {ruta.vista === "edificacion" ? <Edificacion key={ruta.id} id={ruta.id} pestana={ruta.pestana} /> : null}
        {ruta.vista === "edificio" ? <Edificio key={ruta.id} id={ruta.id} pestana={ruta.pestana} /> : null}
        {ruta.vista === "red-mt" ? <RedMT key={ruta.id} id={ruta.id} pestana={ruta.pestana} /> : null}
        {ruta.vista === "industria" ? <Industria key={ruta.id} id={ruta.id} pestana={ruta.pestana} /> : null}
        {ruta.vista === "nuevo" ? <Asistente key="nuevo" /> : null}
        {ruta.vista === "modulo" && ruta.modulo === "inicio" ? <Inicio /> : null}
        {ruta.vista === "modulo" && ruta.modulo === "viviendas" ? <Viviendas /> : null}
        {ruta.vista === "modulo" && ruta.modulo === "pisos" ? <PaginaPisos /> : null}
        {ruta.vista === "modulo" && ruta.modulo === "industrias" ? <PaginaIndustrias /> : null}
        {ruta.vista === "modulo" && ruta.modulo === "redes-mt" ? <PaginaRedesMT /> : null}
        {ruta.vista === "modulo" && ruta.modulo === "no-residencial" ? <PaginaNoResidencial /> : null}
      </main>
    </div>
  );
}
