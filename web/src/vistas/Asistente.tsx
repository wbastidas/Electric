import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { api, type Escenario, type Perfil, type ProyectoDetalle, type Respuestas } from "../api/cliente";
import { legible } from "../util";
import { Aviso, Campo, MensajeError } from "./comunes";
import { Comparacion } from "./Escenarios";

const PASOS = ["Proyecto", "Plano", "Clima y aire", "Iluminación", "Equipos y exteriores", "Opciones"] as const;
/** Equipos que el asistente pregunta; el aire y la refrigeradora tienen su propia pregunta. */
const PROPUESTOS = new Set(["aire_acondicionado", "refrigeradora"]);

const AIRE: [Respuestas["aire"], string, string][] = [
  ["zona", "Según la zona", "En Costa, Amazonía y Galápagos: dormitorios, sala y estudio. En Sierra, ninguno."],
  ["dormitorios", "Solo dormitorios", "Aire en cada dormitorio, sea cual sea la zona."],
  ["todos", "Todos los que lo admiten", "Dormitorios, sala y estudio, sea cual sea la zona."],
  ["ninguno", "Ninguno", "Sin aire acondicionado."],
];

interface Props {
  /** Si se abre desde un proyecto que ya tiene plano, empieza en «Clima y aire». */
  proyecto?: ProyectoDetalle;
}

/** Asistente: unas pocas preguntas y tres opciones diseñadas para elegir. */
export function Asistente({ proyecto: existente }: Props) {
  const consultas = useQueryClient();
  const perfiles = useQuery({ queryKey: ["perfiles"], queryFn: api.perfiles });
  const [paso, setPaso] = useState(existente?.datos.plano ? 2 : existente ? 1 : 0);
  const [proyecto, setProyecto] = useState<ProyectoDetalle | undefined>(existente);

  const [nombre, setNombre] = useState("");
  const [propietario, setPropietario] = useState("");
  const [direccion, setDireccion] = useState("");
  const [perfilId, setPerfilId] = useState("cnel-ep");
  const [alimentador, setAlimentador] = useState("");
  const [archivo, setArchivo] = useState<File | null>(null);
  const [escala, setEscala] = useState("");

  const previas = existente?.datos.preferencias;
  const [r, setR] = useState<Respuestas>({
    zona_climatica: previas?.zona_climatica ?? null,
    aire: "zona",
    iluminacion: previas?.iluminacion ?? "plafon",
    iluminacion_social: null,
    iluminacion_dormitorios: null,
    refrigeradora: previas?.refrigeradora ?? true,
    exteriores: previas?.exteriores ?? true,
    equipos:
      existente?.datos.cargas_especiales.filter((c) => c.origen !== "auto").map((c) => c.tipo) ?? [
        "ducha",
        "cocina",
      ],
  });
  const cambiar = (cambio: Partial<Respuestas>) => setR({ ...r, ...cambio });

  const perfil: Perfil | undefined =
    perfiles.data?.find((p) => p.id === (proyecto?.datos.perfil.id ?? perfilId)) ?? perfiles.data?.[0];

  const leerPlano = useMutation({
    mutationFn: async () => {
      if (!perfil || !archivo) throw new Error("falta el plano");
      const base =
        proyecto ??
        (await api.crear({
          nombre: nombre.trim(),
          perfil: { id: perfil.id, version: perfil.version },
          predio: { propietario, direccion, clave_catastral: "", unidad_negocio: "", plantas: 1 },
          tablero: { id: "TD-1", alimentador_longitud_m: alimentador },
        }));
      setProyecto(base);
      return api.subirPlano(base.id, base.revision, archivo, escala || undefined);
    },
    onSuccess: (leido) => {
      setProyecto(leido);
      consultas.invalidateQueries({ queryKey: ["proyectos"] });
    },
  });
  const generar = useMutation({
    mutationFn: () => {
      if (!proyecto) throw new Error("sin proyecto");
      return api.opciones(proyecto.id, proyecto.revision, r);
    },
    onSuccess: () => {
      consultas.invalidateQueries({ queryKey: ["proyectos"] });
      consultas.invalidateQueries({ queryKey: ["escenarios"] });
      consultas.invalidateQueries({ queryKey: ["proyecto"] });
    },
  });

  if (perfiles.isError) return <MensajeError error={perfiles.error} />;
  if (!perfil) return <p>Cargando…</p>;

  const plano = proyecto?.datos.plano;
  const especiales = perfil.cargas.filter((c) => c.especial && !PROPUESTOS.has(c.tipo));
  const estilos = perfil.estilos;
  const descripcion = (id?: string | null) => estilos.find((e) => e.id === id)?.descripcion;
  const listo = [
    nombre.trim() !== "" && Number(alimentador) > 0,
    Boolean(plano?.ambientes.length),
    true,
    true,
    true,
    true,
  ];

  const navegacion = (siguiente: ReactNode = null) => (
    <div className="acciones izquierda">
      {paso > (existente?.datos.plano ? 2 : 0) && paso < 5 ? (
        <button onClick={() => setPaso(paso - 1)}>← Atrás</button>
      ) : null}
      {siguiente ?? (
        <button className="primario" disabled={!listo[paso]} onClick={() => setPaso(paso + 1)}>
          Siguiente →
        </button>
      )}
    </div>
  );

  const selectorEstilo = (valor: string | null | undefined, alCambiar: (v: string | null) => void, conGeneral: boolean) => (
    <select value={valor ?? ""} onChange={(e) => alCambiar(e.target.value || null)}>
      {conGeneral ? <option value="">Igual que el general</option> : null}
      {estilos.map((e) => (
        <option key={e.id} value={e.id}>{e.nombre}</option>
      ))}
    </select>
  );

  return (
    <div className="pagina asistente">
      <a className="volver" href={proyecto && existente ? `#/proyectos/${proyecto.id}` : "#/"}>
        ← {existente ? "Volver al proyecto" : "Proyectos"}
      </a>
      <h1>{existente ? `Opciones para ${existente.datos.nombre}` : "Nuevo proyecto"}</h1>
      <ol className="pasos" aria-label="Pasos del asistente">
        {PASOS.map((p, i) => (
          <li key={p} className={i === paso ? "actual" : i < paso ? "hecho" : ""} aria-current={i === paso ? "step" : undefined}>
            {p}
          </li>
        ))}
      </ol>

      {paso === 0 ? (
        <section className="tarjeta columnas">
          <h2>Datos del proyecto</h2>
          <div className="rejilla">
            <Campo etiqueta="Nombre del proyecto">
              <input value={nombre} onChange={(e) => setNombre(e.target.value)} placeholder="Vivienda familia Pérez" />
            </Campo>
            <Campo etiqueta="Propietario">
              <input value={propietario} onChange={(e) => setPropietario(e.target.value)} />
            </Campo>
            <Campo etiqueta="Dirección">
              <input value={direccion} onChange={(e) => setDireccion(e.target.value)} />
            </Campo>
            <Campo etiqueta="Perfil normativo">
              <select value={perfil.id} onChange={(e) => setPerfilId(e.target.value)}>
                {perfiles.data?.map((p) => (
                  <option key={p.id} value={p.id}>{p.nombre} · v{p.version}</option>
                ))}
              </select>
            </Campo>
            <Campo etiqueta="Distancia del medidor al tablero (m)" ayuda="No sale del plano: mídala o estímela.">
              <input type="number" min="0" step="any" value={alimentador} onChange={(e) => setAlimentador(e.target.value)} />
            </Campo>
          </div>
          {navegacion()}
        </section>
      ) : null}

      {paso === 1 ? (
        <section className="tarjeta columnas">
          <h2>Plano arquitectónico</h2>
          <p className="tenue">Un DXF de la planta. La plataforma lee muros, puertas y nombres de los ambientes.</p>
          <div className="rejilla">
            <Campo etiqueta="Archivo DXF">
              <input type="file" accept=".dxf" onChange={(e) => setArchivo(e.target.files?.[0] ?? null)} />
            </Campo>
            <Campo etiqueta="Escala (m por unidad)" ayuda="Solo si el DXF no declara sus unidades. Milímetros: 0.001.">
              <input type="number" min="0" step="any" value={escala} onChange={(e) => setEscala(e.target.value)} />
            </Campo>
          </div>
          <div className="acciones izquierda">
            <button disabled={!archivo || leerPlano.isPending} onClick={() => leerPlano.mutate()}>
              {leerPlano.isPending ? "Leyendo…" : plano ? "Leer otro plano" : "Leer el plano"}
            </button>
          </div>
          {leerPlano.isError ? <MensajeError error={leerPlano.error} /> : null}
          {plano ? (
            <Aviso tipo={plano.ambientes.some((a) => a.banderas?.length) ? "alerta" : "nota"}>
              <strong>
                {plano.ambientes.length} ambientes · {String(plano.area_construida_m2).replace(".", ",")} m² construidos
              </strong>
              <div>{plano.ambientes.map((a) => `${a.nombre || a.id} (${legible(a.uso)})`).join(" · ")}</div>
              {plano.ambientes.some((a) => a.banderas?.length) ? (
                <div>Algunos ambientes no se reconocieron; podrá corregir su uso en la pestaña Plano.</div>
              ) : null}
            </Aviso>
          ) : null}
          {navegacion()}
        </section>
      ) : null}

      {paso === 2 ? (
        <section className="tarjeta columnas">
          <h2>¿Dónde está la vivienda?</h2>
          <div className="opciones-grandes" role="radiogroup" aria-label="Zona climática">
            {[{ id: "", nombre: "No lo sé / sin zona", aire: false }, ...perfil.zonas].map((z) => (
              <label key={z.id} className={`opcion ${(r.zona_climatica ?? "") === z.id ? "elegida" : ""}`}>
                <input type="radio" name="zona" checked={(r.zona_climatica ?? "") === z.id}
                  onChange={() => cambiar({ zona_climatica: z.id || null })} />
                <strong>{z.nombre}</strong>
                <span className="tenue">{z.id ? (z.aire ? "Clima cálido: se propone aire" : "Clima templado: sin aire") : "No se propone aire por zona"}</span>
              </label>
            ))}
          </div>
          <h3>Aire acondicionado</h3>
          <div className="opciones-grandes" role="radiogroup" aria-label="Aire acondicionado">
            {AIRE.map(([valor, titulo, texto]) => (
              <label key={valor} className={`opcion ${r.aire === valor ? "elegida" : ""}`}>
                <input type="radio" name="aire" checked={r.aire === valor} onChange={() => cambiar({ aire: valor })} />
                <strong>{titulo}</strong>
                <span className="tenue">{texto}</span>
              </label>
            ))}
          </div>
          <p className="tenue">La capacidad se calcula por el área de cada ambiente; luego puede cambiarla por ambiente.</p>
          {navegacion()}
        </section>
      ) : null}

      {paso === 3 ? (
        <section className="tarjeta columnas">
          <h2>¿Cómo le gusta la iluminación?</h2>
          <div className="rejilla">
            <Campo etiqueta="Estilo general" ayuda={descripcion(r.iluminacion)}>
              {selectorEstilo(r.iluminacion, (v) => cambiar({ iluminacion: v ?? "plafon" }), false)}
            </Campo>
            <Campo etiqueta="Sala, comedor, cocina y estudio" ayuda={descripcion(r.iluminacion_social)}>
              {selectorEstilo(r.iluminacion_social, (v) => cambiar({ iluminacion_social: v }), true)}
            </Campo>
            <Campo etiqueta="Dormitorios" ayuda={descripcion(r.iluminacion_dormitorios)}>
              {selectorEstilo(r.iluminacion_dormitorios, (v) => cambiar({ iluminacion_dormitorios: v }), true)}
            </Campo>
          </div>
          <p className="tenue">
            Cada luminaria cuenta para la carga con la potencia por punto de CNEL, sea foco u ojo de buey. Después puede
            cambiar el estilo de cualquier ambiente.
          </p>
          {navegacion()}
        </section>
      ) : null}

      {paso === 4 ? (
        <section className="tarjeta columnas">
          <h2>Equipos y exteriores</h2>
          <h3>Equipos con circuito propio</h3>
          <div className="casillas">
            {especiales.map((c) => (
              <label key={c.tipo} className="casilla">
                <input
                  type="checkbox"
                  checked={r.equipos?.includes(c.tipo) ?? false}
                  onChange={(e) =>
                    cambiar({
                      equipos: e.target.checked
                        ? [...(r.equipos ?? []), c.tipo]
                        : (r.equipos ?? []).filter((t) => t !== c.tipo),
                    })
                  }
                />
                {legible(c.tipo)} <span className="tenue">({c.potencia} W)</span>
              </label>
            ))}
          </div>
          <h3>Además</h3>
          <label className="casilla">
            <input type="checkbox" checked={r.refrigeradora ?? true} onChange={(e) => cambiar({ refrigeradora: e.target.checked })} />
            Tomacorriente dedicado para la refrigeradora
          </label>
          <label className="casilla">
            <input type="checkbox" checked={r.exteriores ?? true} onChange={(e) => cambiar({ exteriores: e.target.checked })} />
            Luces y tomas exteriores en la fachada
          </label>
          {navegacion(
            <button className="primario" disabled={generar.isPending} onClick={() => { setPaso(5); generar.mutate(); }}>
              Generar opciones →
            </button>,
          )}
        </section>
      ) : null}

      {paso === 5 ? (
        <section className="tarjeta columnas">
          <h2>Tres opciones para elegir</h2>
          {generar.isPending ? <p>Diseñando las tres opciones…</p> : null}
          {generar.isError ? (
            <>
              <MensajeError error={generar.error} />
              <button onClick={() => setPaso(4)}>← Volver a las preguntas</button>
            </>
          ) : null}
          {generar.data ? <Opciones lista={generar.data} perfil={perfil} /> : null}
        </section>
      ) : null}
    </div>
  );
}

const QUE_ES: Record<string, string> = {
  Básica: "Lo mínimo: plafón según el área, sin aire ni refrigeradora dedicada.",
  Recomendada: "Lo que usted respondió.",
  Confort: "Ojos de buey en zonas sociales, aire donde se admite, refrigeradora y fachada completa.",
};

function Opciones({ lista, perfil }: { lista: Escenario[]; perfil: Perfil }) {
  const ultimas = ["Básica", "Recomendada", "Confort"]
    .map((n) => lista.filter((e) => e.nombre.startsWith(n)).sort((a, b) => b.nombre.length - a.nombre.length)[0])
    .filter((e): e is Escenario => Boolean(e));
  return (
    <>
      <div className="opciones-grandes tres">
        {ultimas.map((e) => {
          const dato = (etiqueta: string) => e.resumen.find((d) => d.etiqueta === etiqueta)?.texto ?? "—";
          const base = e.nombre.replace(/ \d+$/, "");
          return (
            <div key={e.id} className={`opcion ${base === "Recomendada" ? "elegida" : ""}`}>
              <strong>{e.nombre}</strong>
              <span className="tenue">{QUE_ES[base]}</span>
              <span className="grande">{dato("Clasificación CNEL")}</span>
              <span>Demanda {dato("Demanda máxima")} · principal {dato("Breaker principal")}</span>
              <span className="tenue">
                {e.luminarias} luminarias · {e.tomacorrientes} tomas · {e.aires} aires · {e.circuitos} circuitos
              </span>
              <a className="boton primario" href={`#/proyectos/${e.id}`}>Elegir y abrir</a>
            </div>
          );
        })}
      </div>
      <details>
        <summary>Comparar todos los datos</summary>
        <Comparacion lista={ultimas} perfil={perfil} />
      </details>
      <p className="tenue">
        Las tres quedan guardadas como escenarios del proyecto: puede abrir cualquiera, ajustarla por ambiente y
        compararlas otra vez en la pestaña Escenarios.
      </p>
    </>
  );
}
