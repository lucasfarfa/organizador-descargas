"""Organizador de Descargas.

Vigila la carpeta Descargas y mueve cada archivo nuevo a una subcarpeta según
su tipo. Nunca sobrescribe: si el nombre ya existe en el destino, agrega
" (1)", " (2)", etc. Pensado para correr siempre en segundo plano con pythonw.

Uso:
    python organizador.py             # vigila, con consola (para probar)
    pythonw organizador.py            # vigila, sin ventana (segundo plano)
    python organizador.py --dry-run   # muestra qué movería y sale
"""

import argparse
import logging
import logging.handlers
import msvcrt
import os
import queue
import stat
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# --- Configuración -----------------------------------------------------------

DESCARGAS = Path.home() / "Downloads"
CARPETA_SCRIPT = Path(__file__).resolve().parent
ARCHIVO_LOG = CARPETA_SCRIPT / "organizador.log"
ARCHIVO_LOCK = CARPETA_SCRIPT / "organizador.lock"

CATEGORIAS = {
    "PDFs": {".pdf"},
    "Imágenes": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg",
                 ".heic", ".tif", ".tiff", ".ico"},
    "Instaladores": {".exe", ".msi", ".msix", ".msixbundle", ".appx", ".appxbundle"},
    "Hojas de cálculo": {".xlsx", ".xls", ".xlsm", ".ods", ".csv", ".tsv"},
    "Documentos": {".doc", ".docx", ".docm", ".dot", ".dotx", ".odt", ".rtf"},
    "Presentaciones": {".ppt", ".pptx", ".pptm", ".pps", ".ppsx", ".pot", ".potx", ".odp"},
}
CATEGORIA_POR_DEFECTO = "Otros"

# Descargas en curso: se ignoran hasta que el navegador las renombre.
EXT_PARCIALES = {".crdownload", ".part", ".partial", ".download", ".tmp"}

INTERVALO_REVISION = 1.0     # segundos entre chequeos de estabilidad
CHEQUEOS_ESTABLES = 3        # chequeos seguidos sin cambios = archivo terminado
TIEMPO_MAX_ESPERA = 10 * 60  # abandona un archivo que sigue cambiando tras esto
INTERVALO_BARRIDO = 5 * 60   # re-escaneo completo como red de seguridad
MAX_REINTENTOS = 5           # para archivos bloqueados por otro programa

EXT_A_CATEGORIA = {ext: cat for cat, exts in CATEGORIAS.items() for ext in exts}

log = logging.getLogger("organizador")


# --- Utilidades ----------------------------------------------------------------

def configurar_log() -> None:
    log.setLevel(logging.INFO)
    formato = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    archivo = logging.handlers.RotatingFileHandler(
        ARCHIVO_LOG, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    archivo.setFormatter(formato)
    log.addHandler(archivo)
    # Con pythonw no hay consola: sys.stdout es None.
    if sys.stdout is not None:
        consola = logging.StreamHandler(sys.stdout)
        consola.setFormatter(formato)
        log.addHandler(consola)


def tomar_lock():
    """Bloquea el archivo de lock. Devuelve None si otra instancia ya lo tiene."""
    f = open(ARCHIVO_LOCK, "a+")
    f.seek(0)
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


def categoria_de(ruta: Path) -> str | None:
    """Carpeta destino del archivo, o None si hay que ignorarlo."""
    nombre = ruta.name
    if nombre.startswith("~$") or nombre.lower() == "desktop.ini":
        return None
    ext = ruta.suffix.lower()
    if ext in EXT_PARCIALES:
        return None
    try:
        atributos = ruta.stat().st_file_attributes
    except OSError:
        return None
    if atributos & (stat.FILE_ATTRIBUTE_HIDDEN | stat.FILE_ATTRIBUTE_SYSTEM):
        return None
    return EXT_A_CATEGORIA.get(ext, CATEGORIA_POR_DEFECTO)


def descarga_en_curso(ruta: Path) -> bool:
    """True si existe "<nombre>.part" o similar al lado (p. ej. Firefox crea
    primero un "x.pdf" vacío y descarga en "x.pdf.part")."""
    return any((ruta.parent / (ruta.name + ext)).exists() for ext in EXT_PARCIALES)


def mover_sin_sobrescribir(origen: Path, categoria: str) -> Path:
    carpeta = origen.parent / categoria
    carpeta.mkdir(exist_ok=True)
    for n in range(10_000):
        nombre = origen.name if n == 0 else f"{origen.stem} ({n}){origen.suffix}"
        destino = carpeta / nombre
        try:
            # En Windows os.rename falla si el destino existe: nunca sobrescribe.
            os.rename(origen, destino)
            return destino
        except FileExistsError:
            continue
    raise RuntimeError(f"Demasiados archivos llamados {origen.name} en {carpeta}")


# --- Organizador -----------------------------------------------------------------

@dataclass
class Pendiente:
    desde: float = field(default_factory=time.monotonic)
    firma: tuple | None = None  # (tamaño, mtime) del último chequeo
    estables: int = 0
    intentos: int = 0
    proximo: float = 0.0


class Organizador(threading.Thread):
    """Recibe rutas por una cola y mueve cada archivo cuando deja de cambiar."""

    def __init__(self, carpeta: Path):
        super().__init__(name="organizador", daemon=True)
        self.carpeta = carpeta
        self.cola: queue.Queue[Path] = queue.Queue()
        self.pendientes: dict[Path, Pendiente] = {}
        self.ultimo_barrido = 0.0

    def encolar(self, ruta) -> None:
        self.cola.put(Path(ruta))

    def barrer(self) -> None:
        try:
            with os.scandir(self.carpeta) as entradas:
                for entrada in entradas:
                    if entrada.is_file():
                        self.encolar(entrada.path)
        except OSError as e:
            log.warning("No se pudo listar %s: %s", self.carpeta, e)
        self.ultimo_barrido = time.monotonic()

    def run(self) -> None:
        self.barrer()
        while True:
            try:
                self.ciclo()
            except Exception:
                log.exception("Error inesperado en el ciclo del organizador")
            time.sleep(INTERVALO_REVISION)

    def ciclo(self) -> None:
        if time.monotonic() - self.ultimo_barrido >= INTERVALO_BARRIDO:
            self.barrer()
        while True:
            try:
                ruta = self.cola.get_nowait()
            except queue.Empty:
                break
            if ruta.parent == self.carpeta:
                self.pendientes.setdefault(ruta, Pendiente())
        for ruta, pendiente in list(self.pendientes.items()):
            try:
                listo = self.revisar(ruta, pendiente)
            except Exception:
                log.exception("Error procesando %s", ruta.name)
                listo = True
            if listo:
                del self.pendientes[ruta]

    def revisar(self, ruta: Path, p: Pendiente) -> bool:
        """Avanza un archivo pendiente. True = terminado (movido o descartado)."""
        ahora = time.monotonic()
        if ahora < p.proximo:
            return False
        if not ruta.is_file():
            return True  # ya no está: movido, borrado o renombrado
        categoria = categoria_de(ruta)
        if categoria is None:
            return True
        if descarga_en_curso(ruta):
            p.desde, p.estables = ahora, 0
            return False
        if ahora - p.desde > TIEMPO_MAX_ESPERA:
            log.warning("Sigue cambiando tras %d min, se reintenta en el próximo barrido: %s",
                        TIEMPO_MAX_ESPERA // 60, ruta.name)
            return True

        st = ruta.stat()
        firma = (st.st_size, st.st_mtime_ns)
        if firma != p.firma:
            p.firma, p.estables = firma, 0
            return False
        p.estables += 1
        if p.estables < CHEQUEOS_ESTABLES:
            return False

        try:
            destino = mover_sin_sobrescribir(ruta, categoria)
        except PermissionError:
            p.intentos += 1
            if p.intentos >= MAX_REINTENTOS:
                log.error("Bloqueado por otro programa, se reintenta en el próximo barrido: %s",
                          ruta.name)
                return True
            p.proximo = ahora + 2 ** p.intentos
            return False
        log.info("%s -> %s", ruta.name, destino.relative_to(self.carpeta))
        return True


class Manejador(FileSystemEventHandler):
    def __init__(self, organizador: Organizador):
        self.organizador = organizador

    def on_created(self, event):
        if not event.is_directory:
            self.organizador.encolar(event.src_path)

    def on_moved(self, event):
        # Los navegadores renombran "x.pdf.crdownload" -> "x.pdf" al terminar.
        if not event.is_directory:
            self.organizador.encolar(event.dest_path)


def iniciar_observer(carpeta: Path, organizador: Organizador) -> Observer:
    observer = Observer()
    # No recursivo: no mira dentro de las subcarpetas ya ordenadas.
    observer.schedule(Manejador(organizador), str(carpeta), recursive=False)
    observer.start()
    return observer


def vigilar(carpeta: Path) -> None:
    organizador = Organizador(carpeta)
    organizador.start()
    observer = None
    try:
        while True:
            if observer is None or not observer.is_alive():
                if observer is not None:
                    log.warning("El observador se detuvo; reiniciando")
                try:
                    observer = iniciar_observer(carpeta, organizador)
                except OSError as e:
                    log.error("No se pudo vigilar %s: %s", carpeta, e)
                    observer = None
            time.sleep(5)
    except KeyboardInterrupt:
        log.info("Detenido por el usuario")
        if observer is not None:
            observer.stop()
            observer.join()


def simular(carpeta: Path) -> None:
    totales = Counter()
    for entrada in sorted(os.scandir(carpeta), key=lambda e: e.name.lower()):
        if not entrada.is_file():
            continue
        categoria = categoria_de(Path(entrada.path)) or "(ignorado)"
        totales[categoria] += 1
        log.info("[dry-run] %s -> %s", entrada.name, categoria)
    for categoria, n in totales.most_common():
        log.info("[dry-run] %-18s %d archivo(s)", categoria, n)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ordena la carpeta Descargas por tipo de archivo.")
    parser.add_argument("--dry-run", action="store_true",
                        help="solo muestra a dónde iría cada archivo y sale")
    parser.add_argument("--carpeta", type=Path, default=DESCARGAS,
                        help=f"carpeta a vigilar (por defecto {DESCARGAS})")
    args = parser.parse_args()

    configurar_log()
    carpeta = args.carpeta.resolve()
    if args.dry_run:
        simular(carpeta)
        return

    lock = tomar_lock()
    if lock is None:
        log.info("Ya hay otra instancia corriendo; saliendo")
        return
    log.info("Vigilando %s", carpeta)
    vigilar(carpeta)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Error fatal")
        raise
