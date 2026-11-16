import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./api/cliente";
import { Asistente } from "./vistas/Asistente";
import { MensajeError } from "./vistas/comunes";
import { Editor } from "./vistas/Editor";
import { Industria } from "./vistas/Industria";
import { Lista } from "./vistas/Lista";

type Ruta =
  | { vista: "lista" }
  | { vista: "nuevo" }
  | { vista: "proyecto" | "asistente" | "industria"; id: string };

const leerRuta = (): Ruta => {
  const hash = window.location.hash;
  if (hash === "#/nuevo") return { vista: "nuevo" };
  const asistente = hash.match(/^#\/proyectos\/([^/]+)\/asistente$/);
  if (asistente) return { vista: "asistente", id: asistente[1] };
  const industria = hash.match(/^#\/industrias\/([^/]+)$/);
  if (industria) return { vista: "industria", id: industria[1] };
  const proyecto = hash.match(/^#\/proyectos\/([^/]+)$/);
  return proyecto ? { vista: "proyecto", id: proyecto[1] } : { vista: "lista" };
};

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

  return (
    <>
      <header className="barra">
        <a className="marca" href="#/">
          Electric
        </a>
        <span className="lema">Proyectos eléctricos CNEL EP</span>
      </header>
      <main>
        {ruta.vista === "proyecto" ? <Editor key={ruta.id} id={ruta.id} /> : null}
        {ruta.vista === "asistente" ? <AsistenteDe key={ruta.id} id={ruta.id} /> : null}
        {ruta.vista === "industria" ? <Industria key={ruta.id} id={ruta.id} /> : null}
        {ruta.vista === "nuevo" ? <Asistente key="nuevo" /> : null}
        {ruta.vista === "lista" ? <Lista /> : null}
      </main>
    </>
  );
}
