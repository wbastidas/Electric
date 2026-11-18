/** Módulos acordados que todavía no están construidos: qué van a cubrir. */
export function Pronto({ modulo }: { modulo: "redes-mt" | "no-residencial" }) {
  const datos =
    modulo === "redes-mt"
      ? {
          titulo: "Redes de media tensión",
          intro: "Proyectos en 13,8 kV y superiores. Se construye empezando por la extensión de red.",
          tipos: [
            ["Extensión de red MT", "Postes, vanos, conductor, estructuras y seccionamiento desde un punto de arranque."],
            ["Cámara o centro de transformación", "Celdas de MT, transformador, malla de puesta a tierra y medición en MT."],
            ["Urbanización o lotización", "Red de MT y BT, transformadores por sector y alumbrado público."],
            ["Subestación", "Alimentación en 69 kV o más para cargas muy grandes."],
          ],
          entregables: [
            "Ruta sobre el mapa con postes numerados y exportación a KML",
            "Planimetría DXF con estructuras, vanos y tabla de estructuras",
            "Unifilar de MT, caída de tensión, regulación, cortocircuito, seccionadores y fusibles",
          ],
        }
      : {
          titulo: "Proyectos no residenciales",
          intro: "Edificaciones que no son vivienda unifamiliar, desde los planos del arquitecto.",
          tipos: [
            ["Locales y oficinas", "Iluminación por nivel de lux, tomas por puesto de trabajo, aire y tableros por zona."],
            ["Edificio de departamentos", "Medidor por departamento, centro de medición, servicios generales y transformador."],
            ["Nave industrial con plano", "Tableros y máquinas sobre el DXF de la nave y distancias reales de alimentadores."],
            ["Comercial grande", "Centros comerciales, hospitales o colegios, con generador de respaldo y transferencia."],
          ],
          entregables: [
            "Planos de iluminación, tomas y fuerza por planta",
            "Cuadros de cargas por tablero y diagrama unifilar",
            "Cálculos de demanda, transformador, cortocircuito y protecciones",
          ],
        };
  return (
    <div className="pagina">
      <div className="titulo-modulo">
        <h1>{datos.titulo}</h1>
        <p className="tenue">{datos.intro}</p>
      </div>
      <section className="tarjeta">
        <h2>En desarrollo</h2>
        <p>Este módulo está acordado y todavía no está disponible. Va a cubrir:</p>
        <div className="tipos-pronto">
          {datos.tipos.map(([nombre, texto]) => (
            <div key={nombre} className="tipo-pronto">
              <strong>{nombre}</strong>
              <span className="tenue">{texto}</span>
            </div>
          ))}
        </div>
        <h3>Entregables</h3>
        <ul>
          {datos.entregables.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      </section>
    </div>
  );
}
