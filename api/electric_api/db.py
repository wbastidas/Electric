"""Persistencia: proyectos por revisión y bitácora de solo inserción."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ProyectoBD(Base):
    __tablename__ = "proyectos"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    #: Sube en uno con cada cambio; sirve para detectar ediciones simultáneas.
    revision: Mapped[int] = mapped_column(Integer)
    #: Borrador del proyecto en JSON canónico.
    datos: Mapped[str] = mapped_column(Text)
    creado: Mapped[str] = mapped_column(String(32))
    actualizado: Mapped[str] = mapped_column(String(32))


class BitacoraBD(Base):
    """Registro de quién cambió qué y cuándo. Solo se inserta, nunca se edita."""

    __tablename__ = "bitacora"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proyecto_id: Mapped[str] = mapped_column(String(36), ForeignKey("proyectos.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    accion: Mapped[str] = mapped_column(String(32))
    autor: Mapped[str] = mapped_column(String(200))
    fecha: Mapped[str] = mapped_column(String(32))
    #: Huella del borrador tras el cambio.
    huella: Mapped[str] = mapped_column(String(64))
    resumen: Mapped[str] = mapped_column(Text)


class VersionBD(Base):
    """Borrador completo de cada revisión, para poder deshacer."""

    __tablename__ = "versiones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proyecto_id: Mapped[str] = mapped_column(String(36), ForeignKey("proyectos.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    #: Revisión cuyo contenido tiene esta. Es la propia, salvo al deshacer, que
    #: repite una anterior; así deshacer dos veces retrocede dos pasos.
    base: Mapped[int] = mapped_column(Integer)
    datos: Mapped[str] = mapped_column(Text)


class EscenarioBD(Base):
    """Proyectos que son alternativas de un mismo diseño, para compararlos."""

    __tablename__ = "escenarios"

    proyecto_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("proyectos.id"), primary_key=True
    )
    #: Id del proyecto del que salió el primer escenario; agrupa a todos.
    grupo: Mapped[str] = mapped_column(String(36), index=True)
    nombre: Mapped[str] = mapped_column(String(80))


class ArchivoBD(Base):
    """Plano original del arquitecto. Se guarda tal como llegó y no se modifica."""

    __tablename__ = "archivos"

    proyecto_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("proyectos.id"), primary_key=True
    )
    nombre: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    contenido: Mapped[bytes] = mapped_column(LargeBinary)


class EdificacionBD(Base):
    """Vivienda de varios pisos: agrupa un proyecto por planta."""

    __tablename__ = "edificaciones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    #: Datos comunes en JSON: perfil, alimentador desde el medidor, altura de piso…
    datos: Mapped[str] = mapped_column(Text)
    creado: Mapped[str] = mapped_column(String(32))
    actualizado: Mapped[str] = mapped_column(String(32))


class PisoBD(Base):
    """Planta de una edificación: un proyecto con su propio plano."""

    __tablename__ = "pisos"

    proyecto_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("proyectos.id"), primary_key=True
    )
    edificacion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("edificaciones.id"), index=True
    )
    nivel: Mapped[int] = mapped_column(Integer)
    nombre: Mapped[str] = mapped_column(String(80))


class RedMTBD(Base):
    """Extensión de red de media tensión y la red existente que la rodea."""

    __tablename__ = "redes_mt"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer)
    datos: Mapped[str] = mapped_column(Text)
    #: Red existente leída del geoportal o de un archivo, en JSON; vacía si no se cargó.
    existente: Mapped[str] = mapped_column(Text, default="")
    creado: Mapped[str] = mapped_column(String(32))
    actualizado: Mapped[str] = mapped_column(String(32))


class EdificioBD(Base):
    """Edificio de departamentos, locales y oficinas con centro de medición."""

    __tablename__ = "edificios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer)
    datos: Mapped[str] = mapped_column(Text)
    creado: Mapped[str] = mapped_column(String(32))
    actualizado: Mapped[str] = mapped_column(String(32))


class IndustriaBD(Base):
    """Proyecto industrial: cuadro de cargas, ubicación y transformador existente."""

    __tablename__ = "industrias"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer)
    #: Borrador de la industria en JSON.
    datos: Mapped[str] = mapped_column(Text)
    creado: Mapped[str] = mapped_column(String(32))
    actualizado: Mapped[str] = mapped_column(String(32))


def crear_motor(url: str) -> Engine:
    if url.startswith("sqlite"):
        opciones: dict[str, object] = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            opciones["poolclass"] = StaticPool
        motor = create_engine(url, **opciones)
    else:
        motor = create_engine(url, pool_pre_ping=True)
    Base.metadata.create_all(motor)
    return motor


def crear_sesiones(motor: Engine) -> sessionmaker:  # type: ignore[type-arg]
    return sessionmaker(motor, expire_on_commit=False)
