import type { Borrador, CargaEspecial, Circuito, Perfil } from "../api/cliente";
import { conCantidadDePuntos, ETIQUETA_TIPO, legible, nuevoIdCircuito, numero, texto } from "../util";
import { Aviso, Campo } from "./comunes";

interface Props {
  datos: Borrador;
  perfil: Perfil;
  cambiar: (datos: Borrador) => void;
}

type Tipo = Circuito["tipo"];

export function Circuitos({ datos, perfil, cambiar }: Props) {
  const equipos = perfil.cargas.filter((c) => c.especial);
  const potenciaPunto = (tipo: string) => perfil.cargas.find((c) => c.tipo === tipo)?.potencia;

  const agregar = (tipo: Tipo) => {
    const id = nuevoIdCircuito(datos);
    const circuito: Circuito = { id, tipo, longitud_m: "10", zona_humeda: false };
    const base = { ...datos, circuitos: [...datos.circuitos, circuito] };
    if (tipo !== "especial") return cambiar(conCantidadDePuntos(base, id, 1));
    const equipo = equipos[0];
    if (!equipo) return;
    const carga: CargaEspecial = { id: `${id}-EQ`, tipo: equipo.tipo, circuito: id, origen: "fijado" };
    cambiar({ ...base, cargas_especiales: [...datos.cargas_especiales, carga] });
  };

  const editar = (id: string, cambio: Partial<Circuito>) =>
    cambiar({ ...datos, circuitos: datos.circuitos.map((c) => (c.id === id ? { ...c, ...cambio } : c)) });

  const editarCarga = (circuito: string, cambio: Partial<CargaEspecial>) =>
    cambiar({
      ...datos,
      cargas_especiales: datos.cargas_especiales.map((c) =>
        c.circuito === circuito ? { ...c, ...cambio } : c,
      ),
    });

  const quitar = (id: string) =>
    cambiar({
      ...datos,
      circuitos: datos.circuitos.filter((c) => c.id !== id),
      puntos: datos.puntos.filter((p) => p.circuito !== id),
      cargas_especiales: datos.cargas_especiales.filter((c) => c.circuito !== id),
    });

  return (
    <div className="columnas">
      <div className="acciones izquierda">
        <button onClick={() => agregar("iluminacion")}>+ Circuito de iluminación</button>
        <button onClick={() => agregar("tomacorrientes")}>+ Circuito de tomacorrientes</button>
        <button onClick={() => agregar("especial")} disabled={!equipos.length}>
          + Carga especial
        </button>
      </div>

      {datos.circuitos.length === 0 ? (
        <Aviso tipo="nota">
          Agregue los circuitos de la vivienda. Cada carga especial (ducha, cocina, aire
          acondicionado) va en un circuito propio.
        </Aviso>
      ) : null}

      {datos.circuitos.map((circuito) => {
        const puntos = datos.puntos.filter((p) => p.circuito === circuito.id);
        const carga = datos.cargas_especiales.find((c) => c.circuito === circuito.id);
        const equipo = equipos.find((e) => e.tipo === carga?.tipo);
        const tipoPunto = circuito.tipo === "iluminacion" ? "punto_luz" : "tomacorriente";
        return (
          <section className="tarjeta circuito" key={circuito.id}>
            <div className="titulo-circuito">
              <h2>
                {circuito.id} · {ETIQUETA_TIPO[circuito.tipo]}
              </h2>
              <button className="discreto" onClick={() => quitar(circuito.id)}>
                Quitar
              </button>
            </div>
            <div className="rejilla">
              {circuito.tipo === "especial" && carga ? (
                <>
                  <Campo etiqueta="Equipo">
                    <select
                      value={carga.tipo}
                      onChange={(e) => editarCarga(circuito.id, { tipo: e.target.value })}
                    >
                      {equipos.map((e) => (
                        <option key={e.tipo} value={e.tipo}>
                          {legible(e.tipo)}
                        </option>
                      ))}
                    </select>
                  </Campo>
                  <Campo
                    etiqueta="Potencia de placa (W)"
                    ayuda={`Vacío usa el valor del perfil: ${texto(equipo?.potencia)} W.`}
                  >
                    <input
                      type="number"
                      min="0"
                      step="any"
                      value={texto(carga.potencia_w)}
                      onChange={(e) => editarCarga(circuito.id, { potencia_w: numero(e.target.value) })}
                    />
                  </Campo>
                  <Campo etiqueta="Conexión">
                    <select
                      value={carga.conexion ?? ""}
                      onChange={(e) =>
                        editarCarga(circuito.id, {
                          conexion: (e.target.value || null) as CargaEspecial["conexion"],
                        })
                      }
                    >
                      <option value="">
                        Por defecto del perfil ({equipo?.conexion === "linea" ? "entre líneas" : "fase y neutro"})
                      </option>
                      <option value="fase_neutro">Fase y neutro</option>
                      <option value="linea">Entre líneas</option>
                    </select>
                  </Campo>
                </>
              ) : (
                <Campo
                  etiqueta={circuito.tipo === "iluminacion" ? "Puntos de luz" : "Tomacorrientes"}
                  ayuda={`${texto(potenciaPunto(tipoPunto))} W por punto, según el perfil.`}
                >
                  <input
                    type="number"
                    min="1"
                    step="1"
                    value={puntos.length}
                    onChange={(e) =>
                      cambiar(conCantidadDePuntos(datos, circuito.id, Math.floor(Number(e.target.value)) || 0))
                    }
                  />
                </Campo>
              )}
              <Campo etiqueta="Longitud del recorrido (m)" ayuda="Del tablero al punto más lejano.">
                <input
                  type="number"
                  min="0"
                  step="any"
                  value={texto(circuito.longitud_m)}
                  onChange={(e) => editar(circuito.id, { longitud_m: e.target.value })}
                />
              </Campo>
              <Campo etiqueta="Fase">
                <select
                  value={circuito.fase ?? ""}
                  onChange={(e) => editar(circuito.id, { fase: (e.target.value || null) as Circuito["fase"] })}
                >
                  <option value="">Automática (balanceo)</option>
                  {["A", "B", "C", "AB", "BC", "AC"].map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </Campo>
              <label className="casilla">
                <input
                  type="checkbox"
                  checked={circuito.zona_humeda ?? false}
                  onChange={(e) => editar(circuito.id, { zona_humeda: e.target.checked })}
                />
                Zona húmeda (baño, cocina, exterior)
              </label>
            </div>
          </section>
        );
      })}
    </div>
  );
}
