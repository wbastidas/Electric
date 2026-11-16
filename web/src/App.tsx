import { useEffect, useState } from "react";
import { Editor } from "./vistas/Editor";
import { Lista } from "./vistas/Lista";

const idDeLaRuta = (): string | null => {
  const coincide = window.location.hash.match(/^#\/proyectos\/(.+)$/);
  return coincide ? coincide[1] : null;
};

export function App() {
  const [id, setId] = useState(idDeLaRuta);

  useEffect(() => {
    const alCambiar = () => setId(idDeLaRuta());
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
      <main>{id ? <Editor key={id} id={id} /> : <Lista />}</main>
    </>
  );
}
