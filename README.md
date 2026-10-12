# Organizador de Descargas

Script de Python para Windows que vigila la carpeta **Descargas** y mueve cada archivo nuevo a una subcarpeta según su tipo. Corre en segundo plano, sin ventana y sin conexión a internet.

## Qué hace

| Subcarpeta | Extensiones |
|---|---|
| `PDFs` | `.pdf` |
| `Imágenes` | `.jpg .jpeg .png .gif .bmp .webp .svg .heic .tif .tiff .ico` |
| `Instaladores` | `.exe .msi .msix .msixbundle .appx .appxbundle` |
| `Hojas de cálculo` | `.xlsx .xls .xlsm .ods .csv .tsv` |
| `Documentos` | `.doc .docx .docm .dot .dotx .odt .rtf` |
| `Presentaciones` | `.ppt .pptx .pptm .pps .ppsx .pot .potx .odp` |
| `Otros` | todo lo demás |

- **Nunca sobrescribe.** Si `PDFs\informe.pdf` ya existe, el nuevo queda como `informe (1).pdf`, `informe (2).pdf`, etc.
- **Espera a que la descarga termine.** Ignora los `.crdownload`, `.part`, `.partial`, `.download` y `.tmp`. Solo mueve un archivo cuando su tamaño deja de cambiar.
- **Ordena lo que ya estaba.** Al arrancar ordena lo que ya hay en la carpeta, y cada 5 minutos repasa toda la carpeta por si se escapó algún archivo.
- **Ignora lo que no corresponde:** subcarpetas, archivos ocultos o de sistema (`desktop.ini`) y temporales de Office (`~$...`).
- **Una sola instancia.** Si se lanza dos veces, la segunda copia se cierra sola.
- **Deja registro.** Cada movimiento queda en `organizador.log`, junto al script (rotativo, máximo ~4 MB).

## Requisitos

- Windows 10 u 11
- Python 3.10 o superior
- [`watchdog`](https://pypi.org/project/watchdog/), la única dependencia externa

## Instalación

```bash
git clone https://github.com/lucasfarfa/organizador-descargas.git
cd organizador-descargas
python -m pip install -r requirements.txt
```

## Uso

```bash
# Ver a dónde iría cada archivo, sin mover nada
python organizador.py --dry-run

# Vigilar con consola (para probar; se corta con Ctrl+C)
python organizador.py

# Vigilar otra carpeta
python organizador.py --carpeta "D:\Otra\Carpeta"
```

## Ejecutarlo siempre en segundo plano

Creá un acceso directo en la carpeta de Inicio que ejecute el script con `pythonw.exe`, que no abre ventana. Desde PowerShell, dentro de la carpeta del proyecto:

```powershell
$pyw = (Get-Command pythonw).Source
$lnk = [Environment]::GetFolderPath('Startup') + "\Organizador Descargas.lnk"
$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
$s.TargetPath = $pyw
$s.Arguments = "`"$PWD\organizador.py`""
$s.WorkingDirectory = "$PWD"
$s.Save()
Start-Process $lnk   # lo lanza ahora, sin esperar al próximo inicio de sesión
```

**Para detenerlo:** `Stop-Process -Name pythonw`. Ojo: esto cierra todos los procesos `pythonw`, no solo el organizador.
**Para que no arranque más:** borrá el acceso directo de la carpeta de Inicio. La abrís escribiendo `shell:startup` en Win+R.

## Personalizar

Las categorías y los tiempos de espera están al principio de `organizador.py`, en `CATEGORIAS` y las constantes de abajo. Después de editarlos, reiniciá el proceso.
