import type { Borrador, Perfil, Supuesto } from "../api/cliente";
import { hoy, numero, texto } from "../util";
import { Campo } from "./comunes";

interface Props {
  datos: Borrador;
  perfil: Perfil;
  cambiar: (datos: Borrador) => void;
}

const PARAMETROS: Record<string, string> = {
  factor_potencia: "Factor de potencia",
  temperatura_ambiente_c: "Temperatura ambiente (°C)",
  factor_demanda_iluminacion: "Factor de demanda de iluminación",
  factor_demanda_tomacorrientes: "Factor de demanda de tomacorrientes",
  factor_demanda_especiales: "Factor de demanda de cargas especiales",
};

export function Datos({ datos, perfil, cambiar }: Props) {
  const predio = (campo: keyof Borrador["predio"], valor: string | number) =>
    cambiar({ ...datos, predio: { ...datos.predio, [campo]: valor } });
  const proyectista = (campo: keyof Borrador["proyectista"], valor: string) =>
    cambiar({ ...datos, proyectista: { ...datos.proyectista, [campo]: valor } });

  const supuesto = (indice: number, cambio: Partial<Supuesto>) =>
    cambiar({
      ...datos,
      supuestos: datos.supuestos.map((s, i) => (i === indice ? { ...s, ...cambio } : s)),
    });
  const libres = Object.keys(PARAMETROS).filter(
    (p) => !datos.supuestos.some((s) => s.parametro === p),
  );

  return (
    <div className="columnas">
      <section className="tarjeta">
        <h2>Proyecto</h2>
        <div className="rejilla">
          <Campo etiqueta="Nombre del proyecto">
            <input value={datos.nombre} onChange={(e) => cambiar({ ...datos, nombre: e.target.value })} />
          </Campo>
          <Campo etiqueta="Área construida (m²)" ayuda="Define el mínimo de circuitos y los factores de demanda.">
            <input
              type="number"
              min="0"
              step="any"
              value={texto(datos.area_construida_m2)}
              onChange={(e) => cambiar({ ...datos, area_construida_m2: numero(e.target.value) })}
            />
          </Campo>
          <Campo etiqueta="Sistema de tensión">
            <select
              value={datos.sistema ?? ""}
              onChange={(e) => cambiar({ ...datos, sistema: e.target.value || null })}
            >
              <option value="">
                Por defecto del perfil (
                {perfil.sistemas.find((s) => s.id === perfil.sistema_defecto)?.descripcion})
              </option>
              {perfil.sistemas.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.descripcion}
                </option>
              ))}
            </select>
          </Campo>
          <Campo
            etiqueta="Longitud del alimentador (m)"
            ayuda="Recorrido del medidor al tablero de distribución."
          >
            <input
              type="number"
              min="0"
              step="any"
              value={texto(datos.tablero?.alimentador_longitud_m)}
              onChange={(e) => {
                const largo = numero(e.target.value);
                cambiar({
                  ...datos,
                  tablero: largo === null ? null : { id: datos.tablero?.id ?? "TD-1", alimentador_longitud_m: largo },
                });
              }}
            />
          </Campo>
        </div>
      </section>

      <section className="tarjeta">
        <h2>Predio</h2>
        <div className="rejilla">
          <Campo etiqueta="Propietario">
            <input value={datos.predio.propietario} onChange={(e) => predio("propietario", e.target.value)} />
          </Campo>
          <Campo etiqueta="Dirección">
            <input value={datos.predio.direccion} onChange={(e) => predio("direccion", e.target.value)} />
          </Campo>
          <Campo etiqueta="Clave catastral">
            <input
              value={datos.predio.clave_catastral}
              onChange={(e) => predio("clave_catastral", e.target.value)}
            />
          </Campo>
          <Campo etiqueta="Unidad de negocio CNEL">
            <input
              value={datos.predio.unidad_negocio}
              onChange={(e) => predio("unidad_negocio", e.target.value)}
              placeholder="Guayaquil, Manabí, El Oro…"
            />
          </Campo>
          <Campo etiqueta="Número de plantas">
            <input
              type="number"
              min="1"
              step="1"
              value={datos.predio.plantas}
              onChange={(e) => predio("plantas", Math.max(1, Number(e.target.value) || 1))}
            />
          </Campo>
        </div>
      </section>

      <section className="tarjeta">
        <h2>Proyectista</h2>
        <div className="rejilla">
          <Campo etiqueta="Nombre">
            <input value={datos.proyectista.nombre} onChange={(e) => proyectista("nombre", e.target.value)} />
          </Campo>
          <Campo etiqueta="Título">
            <input
              value={datos.proyectista.titulo}
              onChange={(e) => proyectista("titulo", e.target.value)}
              placeholder="Ingeniero eléctrico"
            />
          </Campo>
          <Campo etiqueta="Registro SENESCYT">
            <input
              value={datos.proyectista.registro_senescyt}
              onChange={(e) => proyectista("registro_senescyt", e.target.value)}
            />
          </Campo>
          <Campo etiqueta="Registro en CNEL">
            <input
              value={datos.proyectista.registro_cnel}
              onChange={(e) => proyectista("registro_cnel", e.target.value)}
            />
          </Campo>
        </div>
      </section>

      <section className="tarjeta">
        <h2>Supuestos</h2>
        <p className="tenue">
          Sobrescriben un valor del perfil. Cada uno exige justificación y queda escrito en los
          cálculos que lo usan.
        </p>
        {datos.supuestos.map((s, i) => (
          <div className="rejilla supuesto" key={s.parametro}>
            <Campo etiqueta="Parámetro">
              <input value={PARAMETROS[s.parametro] ?? s.parametro} readOnly />
            </Campo>
            <Campo etiqueta="Valor">
              <input
                type="number"
                step="any"
                value={texto(s.valor)}
                onChange={(e) => supuesto(i, { valor: e.target.value })}
              />
            </Campo>
            <Campo etiqueta="Justificación">
              <input value={s.justificacion} onChange={(e) => supuesto(i, { justificacion: e.target.value })} />
            </Campo>
            <Campo etiqueta="Autor">
              <input value={s.autor} onChange={(e) => supuesto(i, { autor: e.target.value })} />
            </Campo>
            <button
              className="discreto"
              onClick={() => cambiar({ ...datos, supuestos: datos.supuestos.filter((_, j) => j !== i) })}
            >
              Quitar
            </button>
          </div>
        ))}
        {libres.length ? (
          <select
            aria-label="Agregar supuesto"
            value=""
            onChange={(e) =>
              e.target.value &&
              cambiar({
                ...datos,
                supuestos: [
                  ...datos.supuestos,
                  {
                    parametro: e.target.value,
                    valor: "1",
                    justificacion: "",
                    autor: datos.proyectista.nombre,
                    fecha: hoy(),
                  },
                ],
              })
            }
          >
            <option value="">Agregar supuesto…</option>
            {libres.map((p) => (
              <option key={p} value={p}>
                {PARAMETROS[p]}
              </option>
            ))}
          </select>
        ) : null}
      </section>
    </div>
  );
}
