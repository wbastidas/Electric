import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Calculos as Datos, type Resultado } from "../api/cliente";
import { ETIQUETA_TIPO, legible } from "../util";
import { Aviso, Insignia, MensajeError } from "./comunes";

type Fila = Datos["cuadro"][number];
type Seleccion = { id: string; sujeto: string } | null;

/** Columna del cuadro de cargas → cálculo que la produce. */
const COLUMNAS: { clave: keyof Fila; titulo: string; rc?: string }[] = [
  { clave: "circuito", titulo: "Circuito" },
  { clave: "tipo", titulo: "Tipo" },
  { clave: "fase", titulo: "Fase", rc: "RC-10" },
  { clave: "carga", titulo: "Carga", rc: "RC-01" },
  { clave: "corriente", titulo: "Corriente", rc: "RC-06" },
  { clave: "breaker", titulo: "Breaker", rc: "RC-09" },
  { clave: "conductor", titulo: "Conductor", rc: "RC-07" },
  { clave: "tierra", titulo: "Tierra", rc: "RC-14" },
  { clave: "ducto", titulo: "Ducto", rc: "RC-13" },
  { clave: "longitud", titulo: "Longitud" },
  { clave: "caida", titulo: "Caída", rc: "RC-08" },
];

function origen(fila: Fila, rc: string): Seleccion {
  if (fila.circuito !== "alimentador") return { id: rc, sujeto: fila.circuito };
  if (rc === "RC-10") return null;
  // La carga del alimentador es la demanda máxima del proyecto.
  return rc === "RC-01" ? { id: "RC-03", sujeto: "proyecto" } : { id: rc, sujeto: "alimentador" };
}

export function Detalle({ resultado, cerrar }: { resultado: Resultado; cerrar: () => void }) {
  return (
    <aside className="detalle" aria-label="Detalle del cálculo">
      <div className="titulo-circuito">
        <h2>
          {resultado.id} · {resultado.nombre}
        </h2>
        <button className="discreto" onClick={cerrar}>
          Cerrar
        </button>
      </div>
      <p className="cifra">{resultado.texto}</p>
      <p>
        <span className="tenue">{resultado.sujeto}</span> <Insignia estado={resultado.estado} />
      </p>
      <h3>Fórmula</h3>
      <p className="formula">{resultado.formula}</p>
      {resultado.entradas.length ? (
        <>
          <h3>Entradas</h3>
          <dl>
            {resultado.entradas.map((e) => (
              <div key={e.clave}>
                <dt>{legible(e.clave)}</dt>
                <dd>{e.texto}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : null}
      {resultado.detalle.length ? (
        <>
          <h3>Otros valores</h3>
          <dl>
            {resultado.detalle.map((e) => (
              <div key={e.clave}>
                <dt>{legible(e.clave)}</dt>
                <dd>{e.texto}</dd>
              </div>
            ))}
          </dl>
        </>
      ) : null}
      {resultado.supuestos.length ? (
        <>
          <h3>Supuestos aplicados</h3>
          <ul>
            {resultado.supuestos.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </>
      ) : null}
      {resultado.avisos.length ? (
        <>
          <h3>Avisos</h3>
          <ul>
            {resultado.avisos.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </>
      ) : null}
      <h3>Tablas usadas</h3>
      <ul className="tablas">
        {resultado.tablas.map((t) => (
          <li key={`${t.id}-${t.fila}`}>
            <code>{t.id}</code> v{t.version}, fila «{t.fila}» <Insignia estado={t.estado} />
          </li>
        ))}
      </ul>
    </aside>
  );
}

export function Calculos({ id, revision }: { id: string; revision: number }) {
  const calculos = useQuery({ queryKey: ["calculos", id, revision], queryFn: () => api.calculos(id) });
  const [seleccion, setSeleccion] = useState<Seleccion>(null);

  if (calculos.isError) return <MensajeError error={calculos.error} />;
  const datos = calculos.data;
  if (!datos) return <p>Calculando…</p>;

  if (datos.estado === "incompleto") {
    return (
      <Aviso tipo="alerta">
        <strong>Falta información para calcular</strong>
        <ul>
          {datos.pendientes.map((p) => (
            <li key={p.mensaje}>{p.mensaje}</li>
          ))}
        </ul>
      </Aviso>
    );
  }

  const elegido = seleccion
    ? datos.resultados.find((r) => r.id === seleccion.id && r.sujeto === seleccion.sujeto)
    : undefined;

  return (
    <div className={elegido ? "con-detalle" : ""}>
      <div className="columnas">
        <Aviso tipo="alerta">{datos.aviso}</Aviso>

        <div className="resumen">
          {datos.resumen.map((d) => (
            <button
              key={d.etiqueta}
              className="dato"
              onClick={() => setSeleccion({ id: d.id, sujeto: d.sujeto })}
            >
              <span className="etiqueta">{d.etiqueta}</span>
              <span className="valor">{d.texto}</span>
            </button>
          ))}
        </div>

        <section>
          <h2>Cuadro de cargas</h2>
          <p className="tenue">Toque una cifra para ver su fórmula, sus entradas y la tabla de la que sale.</p>
          <div className="tabla-ancha">
            <table>
              <thead>
                <tr>
                  {COLUMNAS.map((c) => (
                    <th key={c.clave}>{c.titulo}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {datos.cuadro.map((fila) => (
                  <tr key={fila.circuito} className={fila.circuito === "alimentador" ? "total" : ""}>
                    {COLUMNAS.map((c) => {
                      const valor = c.clave === "tipo" ? ETIQUETA_TIPO[fila.tipo] ?? fila.tipo : fila[c.clave];
                      const destino = c.rc ? origen(fila, c.rc) : null;
                      return (
                        <td key={c.clave}>
                          {destino && valor ? (
                            <button className="enlace" onClick={() => setSeleccion(destino)}>
                              {valor}
                            </button>
                          ) : (
                            valor
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {datos.avisos.length ? (
          <section>
            <h2>Avisos</h2>
            <ul>
              {datos.avisos.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </section>
        ) : null}

        {datos.supuestos.length ? (
          <section>
            <h2>Supuestos aplicados</h2>
            <ul>
              {datos.supuestos.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </section>
        ) : null}

        {datos.tablas_sin_verificar.length ? (
          <section>
            <h2>Tablas sin verificar usadas: {datos.tablas_sin_verificar.length}</h2>
            <p className="tenue">
              Sus valores no se han comparado con el documento oficial. El expediente no puede
              emitirse hasta que un ingeniero las verifique.
            </p>
            <ul className="tablas">
              {datos.tablas_sin_verificar.map((t) => (
                <li key={t.id}>
                  <code>{t.id}</code> v{t.version} <Insignia estado={t.estado} />
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <p className="tenue">
          Huella del cálculo: <code>{datos.huella?.slice(0, 16)}</code>
        </p>
      </div>
      {elegido ? <Detalle resultado={elegido} cerrar={() => setSeleccion(null)} /> : null}
    </div>
  );
}
