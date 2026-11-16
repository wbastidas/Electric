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


class ArchivoBD(Base):
    """Plano original del arquitecto. Se guarda tal como llegó y no se modifica."""

    __tablename__ = "archivos"

    proyecto_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("proyectos.id"), primary_key=True
    )
    nombre: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    contenido: Mapped[bytes] = mapped_column(LargeBinary)


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
