import { useMutation, useQuery } from "@tanstack/react-query";
import { type ChangeEvent, useState } from "react";
import { api, type Borrador, type Perfil, type ProyectoDetalle } from "../api/cliente";
import { ETIQUETA_TIPO, legible } from "../util";
import { Aviso, Campo, MensajeError } from "./comunes";
import { type Capas, COLORES, type Elegido, Visor } from "./Visor";

interface Props {
  id: string;
  revision: number;
  datos: Borrador;
  perfil: Perfil;
  sinGuardar: boolean;
  cambiar: (datos: Borrador) => void;
  adoptar: (proyecto: ProyectoDetalle) => void;
}

const CAPAS: [keyof Capas, string][] = [
  ["plano", "Plano del arquitecto"],
  ["ambientes", "Ambientes"],
  ["iluminacion", "Iluminación"],
  ["tomas", "Tomacorrientes"],
  ["especiales", "Cargas especiales"],
  ["recorridos", "Recorridos"],
];

export function Plano({ id, revision, datos, perfil, sinGuardar, cambiar, adoptar }: Props) {
  const plano = datos.plano;
  const [capas, setCapas] = useState<Capas>({
    plano: true, ambientes: true, iluminacion: true, tomas: true, especiales: true, recorridos: true,
  });
  const [resaltado, setResaltado] = useState<string | null>(null);
  const [elegido, setElegido] = useState<Elegido | null>(null);
  const [escala, setEscala] = useState("");
  const [avisos, setAvisos] = useState<string[]>([]);

  const fondo = useQuery({
    queryKey: ["fondo", id, plano?.sha256],
    queryFn: () => api.fondo(id),
    enabled: Boolean(plano),
  });

  const subir = useMutation({
    mutationFn: (archivo: File) => api.subirPlano(id, revision, archivo, escala || undefined),
    onSuccess: (proyecto) => {
      setAvisos([]);
      adoptar(proyecto);
    },
  });
  const disenar = useMutation({
    // El diseño parte de lo guardado: si hay cambios pendientes, primero se guardan.
    mutationFn: async () => {
      const base = sinGuardar ? (await api.guardar(id, revision, datos)).revision : revision;
      return api.disenar(id, base);
    },
    onSuccess: (resultado) => {
      setAvisos(resultado.avisos);
      setElegido(null);
      adoptar(resultado.proyecto);
    },
  });

  const alElegirArchivo = (e: ChangeEvent<HTMLInputElement>) => {
    const archivo = e.target.files?.[0];
    if (archivo) subir.mutate(archivo);
    e.target.value = "";
  };

  const cargador = (
    <div className="rejilla">
      <Campo etiqueta={plano ? "Reemplazar el plano (DXF)" : "Plano arquitectónico (DXF)"}
        ayuda="El archivo original se guarda sin cambios; la instalación va en capas propias.">
        <input type="file" accept=".dxf" onChange={alElegirArchivo} disabled={subir.isPending || sinGuardar} />
      </Campo>
      <Campo etiqueta="Escala (m por unidad de dibujo)" ayuda="Solo si el DXF no declara sus unidades. Milímetros: 0.001.">
        <input type="number" min="0" step="any" value={escala} onChange={(e) => setEscala(e.target.value)} />
      </Campo>
    </div>
  );

  if (!plano) {
    return (
      <section className="tarjeta columnas">
        <h2>Cargar el plano</h2>
        <p className="tenue">
          La plataforma lee los muros, las puertas y los nombres de los ambientes, y sobre ellos
          propone luminarias, interruptores, tomacorrientes, tablero, circuitos y recorridos.
        </p>
        {sinGuardar ? <Aviso tipo="alerta">Guarde los cambios antes de cargar un plano.</Aviso> : null}
        {cargador}
        {subir.isPending ? <p>Leyendo el plano…</p> : null}
        {subir.isError ? <MensajeError error={subir.error} /> : null}
      </section>
    );
  }

  const disenado = Boolean(plano.ubicaciones?.length);
  const usos = perfil.usos.map((u) => u.uso);
  const equipos = perfil.cargas.filter((c) => c.especial);
  const dudas = plano.ambientes.filter((a) => a.banderas?.length);

  const cambiarUso = (ambiente: string, uso: string) =>
    cambiar({
      ...datos,
      plano: {
        ...plano,
        // Al elegir el uso, la duda queda resuelta por el usuario.
        ambientes: plano.ambientes.map((a) => (a.id === ambiente ? { ...a, uso, banderas: [] } : a)),
      },
    });
  const agregarEquipo = (tipo: string) =>
    cambiar({
      ...datos,
      cargas_especiales: [
        ...datos.cargas_especiales,
        { id: `declarada-${Date.now()}`, tipo, circuito: "-", origen: "fijado" },
      ],
    });
  const quitarEquipo = (idCarga: string) =>
    cambiar({
      ...datos,
      cargas_especiales: datos.cargas_especiales.filter((c) => c.id !== idCarga),
      circuitos: datos.circuitos.filter(
        (c) => c.id !== datos.cargas_especiales.find((e) => e.id === idCarga)?.circuito,
      ),
    });

  const cuenta = (circuito: string) =>
    datos.puntos.filter((p) => p.circuito === circuito).length ||
    datos.cargas_especiales.filter((c) => c.circuito === circuito).length;

  return (
    <div className="plano">
      <div className="columnas">
        {plano.banderas?.length ? (
          <Aviso tipo="alerta">
            <strong>Al leer el plano</strong>
            <ul>{plano.banderas.map((b) => <li key={b}>{b}</li>)}</ul>
          </Aviso>
        ) : null}
        <Visor
          fondo={fondo.data}
          plano={plano}
          datos={datos}
          capas={capas}
          resaltado={resaltado}
          elegido={elegido?.id ?? null}
          elegir={setElegido}
        />
        <p className="tenue">
          {plano.archivo} · {plano.ambientes.length} ambientes · {String(plano.area_construida_m2).replace(".", ",")} m²
          construidos. Rueda del ratón para acercar; arrastre para mover; toque un símbolo para ver sus datos.
        </p>
        {fondo.isError ? <MensajeError error={fondo.error} /> : null}
      </div>

      <div className="columnas panel-plano">
        <section className="tarjeta">
          <h2>Instalación</h2>
          <div className="acciones izquierda">
            <button className="primario" disabled={disenar.isPending} onClick={() => disenar.mutate()}>
              {disenar.isPending ? "Diseñando…" : disenado ? "Volver a diseñar" : "Diseñar instalación"}
            </button>
          </div>
          <p className="tenue">
            {disenado
              ? "Volver a diseñar reemplaza puntos y circuitos; conserva los equipos declarados."
              : "Coloca luminarias, tomas, tablero y recorridos según las plantillas del perfil."}
          </p>
          {disenar.isError ? <MensajeError error={disenar.error} /> : null}
          {avisos.length ? (
            <Aviso tipo="alerta">
              <strong>Por revisar</strong>
              <ul>{avisos.map((a) => <li key={a}>{a}</li>)}</ul>
            </Aviso>
          ) : null}
          {disenado ? (
            <>
              <h3>Descargar</h3>
              {sinGuardar ? <p className="tenue">Guarde para descargar la versión actual.</p> : (
                <div className="acciones izquierda">
                  <a className="boton" href={api.urlSalida(id, "dxf")}>DXF</a>
                  <a className="boton" href={api.urlSalida(id, "pdf")}>PDF</a>
                  <a className="boton" href={api.urlSalida(id, "png")}>Imagen</a>
                </div>
              )}
            </>
          ) : null}
        </section>

        {elegido ? (
          <section className="tarjeta">
            <h2>{elegido.id}</h2>
            <dl>
              <div><dt>Tipo</dt><dd>{elegido.tipo}</dd></div>
              {elegido.circuito ? <div><dt>Circuito</dt><dd>{elegido.circuito}</dd></div> : null}
              <div><dt>Ambiente</dt><dd>{elegido.ambiente}</dd></div>
              <div><dt>Altura</dt><dd>{elegido.altura.replace(".", ",")} m</dd></div>
            </dl>
          </section>
        ) : null}

        <section className="tarjeta">
          <h2>Capas</h2>
          {CAPAS.map(([clave, nombre]) => (
            <label className="casilla" key={clave}>
              <input
                type="checkbox"
                checked={capas[clave]}
                onChange={(e) => setCapas({ ...capas, [clave]: e.target.checked })}
              />
              {nombre}
            </label>
          ))}
          {disenado ? (
            <>
              <h3>Circuitos</h3>
              <ul className="circuitos">
                {datos.circuitos.map((c, i) => (
                  <li key={c.id}>
                    <button
                      className={`chip ${resaltado === c.id ? "activo" : ""}`}
                      aria-pressed={resaltado === c.id}
                      onClick={() => setResaltado(resaltado === c.id ? null : c.id)}
                    >
                      <span className="muestra" style={{ background: COLORES[i % COLORES.length] }} />
                      {c.id} · {ETIQUETA_TIPO[c.tipo]} · {cuenta(c.id)}
                    </button>
                  </li>
                ))}
              </ul>
              <p className="tenue">Toque un circuito para resaltarlo.</p>
            </>
          ) : null}
        </section>

        <section className="tarjeta">
          <h2>Equipos declarados</h2>
          <p className="tenue">Cargas especiales que el plano no dice; el diseño las ubica en su ambiente.</p>
          <ul className="circuitos">
            {datos.cargas_especiales.map((c) => (
              <li key={c.id}>
                <span className="chip">
                  {legible(c.tipo)}
                  <button className="discreto" aria-label={`Quitar ${c.tipo}`} onClick={() => quitarEquipo(c.id)}>×</button>
                </span>
              </li>
            ))}
          </ul>
          <select aria-label="Agregar equipo" value="" onChange={(e) => e.target.value && agregarEquipo(e.target.value)}>
            <option value="">Agregar equipo…</option>
            {equipos.map((e) => <option key={e.tipo} value={e.tipo}>{legible(e.tipo)}</option>)}
          </select>
        </section>

        <section className="tarjeta">
          <h2>Ambientes</h2>
          {dudas.length ? (
            <Aviso tipo="alerta">
              {dudas.length === 1 ? "Un ambiente necesita" : `${dudas.length} ambientes necesitan`} que confirme su uso.
            </Aviso>
          ) : null}
          <div className="tabla-ancha">
            <table>
              <thead><tr><th>Ambiente</th><th>Uso</th><th>Área</th></tr></thead>
              <tbody>
                {plano.ambientes.map((a) => (
                  <tr key={a.id} className={a.banderas?.length ? "dudoso" : ""}>
                    <td title={a.banderas?.join("; ")}>{a.nombre || `${a.id} (sin nombre)`}</td>
                    <td>
                      <select aria-label={`Uso de ${a.nombre || a.id}`} value={a.uso} onChange={(e) => cambiarUso(a.id, e.target.value)}>
                        {usos.map((u) => <option key={u} value={u}>{legible(u)}</option>)}
                      </select>
                    </td>
                    <td>{String(a.area_m2).replace(".", ",")} m²</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="tarjeta columnas">
          <h2>Archivo</h2>
          {sinGuardar ? <p className="tenue">Guarde los cambios para poder reemplazar el plano.</p> : null}
          {cargador}
          {subir.isPending ? <p>Leyendo el plano…</p> : null}
          {subir.isError ? <MensajeError error={subir.error} /> : null}
        </section>
      </div>
    </div>
  );
}
