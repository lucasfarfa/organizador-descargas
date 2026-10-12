# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es

Script de Python para Windows (un solo archivo, `organizador.py`) que vigila `~/Downloads` y mueve cada archivo a una subcarpeta según su extensión. Debe funcionar offline y correr siempre en segundo plano con `pythonw`. Es solo Windows: usa `msvcrt` y `st_file_attributes`. README y mensajes de log están en español.

## Comandos

```bash
python -m pip install -r requirements.txt   # única dependencia externa: watchdog
python organizador.py --dry-run             # muestra a qué carpeta iría cada archivo y sale; no mueve nada
python organizador.py                       # vigila con consola (Ctrl+C para cortar)
python organizador.py --carpeta <ruta>      # vigila otra carpeta en vez de Descargas
```

No hay tests ni linter. Para probar cambios, usar siempre `--carpeta` apuntando a una carpeta temporal con archivos de prueba, no la carpeta Descargas real: sin `--dry-run` el script mueve archivos de verdad.

El proceso en segundo plano (acceso directo `Organizador Descargas.lnk` en `shell:startup`, que ejecuta `pythonw.exe organizador.py`) mantiene `organizador.lock` abierto. Si está corriendo, una instancia nueva sale de inmediato con "Ya hay otra instancia". Para probar cambios, detenerlo antes con `Stop-Process -Name pythonw` y reiniciarlo después.

## Arquitectura

Todo el flujo está en `organizador.py`, con dos hilos:

- **Hilo principal** (`vigilar`): mantiene vivo el `Observer` de watchdog (no recursivo, para no reprocesar las subcarpetas ya ordenadas) y lo reinicia si muere. `Manejador` solo encola rutas en `on_created` y `on_moved`. `on_moved` es importante: los navegadores terminan una descarga renombrando `x.pdf.crdownload` → `x.pdf`.
- **Hilo `Organizador`**: consume la cola y lleva un dict de `Pendiente` (todos los archivos en proceso a la vez, para que una descarga lenta no bloquee a las demás). En cada ciclo de 1 s, `revisar()` avanza cada pendiente: descarta lo ignorable, espera a que `(tamaño, mtime)` no cambie `CHEQUEOS_ESTABLES` veces seguidas y recién entonces llama a `mover_sin_sobrescribir`. También hace un barrido completo de la carpeta al arrancar y cada `INTERVALO_BARRIDO` como red de seguridad ante eventos perdidos.

Reglas que hay que conservar al modificar:

- **Nunca sobrescribir:** `mover_sin_sobrescribir` usa `os.rename`, que en Windows falla con `FileExistsError` si el destino existe (a diferencia de `os.replace` o `shutil.move`). Ese error dispara el siguiente sufijo ` (n)`. No cambiarlo por algo que pise archivos.
- **Qué se ignora** está en `categoria_de` (devuelve `None`): `~$*`, `desktop.ini`, extensiones de `EXT_PARCIALES` y archivos ocultos o de sistema. Además `descarga_en_curso` cubre el caso de Firefox, que crea `x.pdf` vacío y descarga en `x.pdf.part`.
- **Archivos bloqueados** (`PermissionError`): se reintenta con espera creciente hasta `MAX_REINTENTOS`. Si no se logra, se abandona y lo retoma el siguiente barrido.
- **Categorías:** el dict `CATEGORIAS` es la única fuente de verdad; `EXT_A_CATEGORIA` se deriva de él. Las extensiones no listadas van a `Otros`.
- **Log:** con `pythonw` `sys.stdout` es `None` y no hay consola, por eso todo se escribe en `organizador.log` (rotativo, ignorado por git). Cualquier salida nueva debe pasar por `log`, no por `print`.
