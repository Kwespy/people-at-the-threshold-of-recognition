# Border Transit

Proyecto visual que mantiene un pool de imágenes documentales y genera versiones transformadas para una web pública.

## Arquitectura actual

- `index.html`: interfaz web pública.
- `rendered/`: imágenes ya generadas que sí se conservan y publican.
- `metadata/`: metadatos asociados a cada imagen.
- `pool.json`: catálogo principal de imágenes.
- `pool_selection.json`: lista explícita de IDs que forman el pool permanente.
- `manifest.json`: manifiesto generado para la web.
- `originals/`: fuentes originales locales; no forman parte del contenido público del repositorio.
- `operations/`: transformaciones visuales.
- `generate_pool.py`: genera las imágenes persistentes del pool.
- `live_server.py`: servidor Flask con generación temporal en tiempo real; las imágenes LIVE solo viven en memoria.
- `scan_*.py`: herramientas de búsqueda y análisis; sus resultados son locales.

## Regla de almacenamiento

Las imágenes que ya pertenecen al pool se conservan en `rendered/` y se publican mediante GitHub/Render.

Las imágenes generadas automáticamente durante una visita o una sesión en vivo son temporales: no se añaden al pool, no entran en Git y solo viven en la memoria del proceso. Desaparecen al consumirse, reiniciar la aplicación o detenerse el servidor.

Las originales y los resultados de escaneo permanecen fuera de GitHub, en el Mac o en la futura máquina virtual, con copias de seguridad independientes.

Tener una imagen en `originals/` no significa que pertenezca al pool. Para incorporar una imagen nueva hay que añadir su ID a `pool_selection.json` y revisar el resultado antes de publicar.

## Ejecutar localmente

Se recomienda Python 3.11 o superior.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python generate_pool.py
python live_server.py
```

La aplicación local queda disponible en `http://localhost:8000`.

## Publicar cambios

El flujo actual sigue siendo:

```text
Mac → generar pool → revisar cambios → GitHub → Render
```

El script `actualizar_web.sh` usa su propia ubicación, por lo que no depende de que el proyecto esté en el Escritorio.

Antes de usarlo, revisar siempre los cambios de Git, especialmente los archivos de `rendered/`, `metadata/`, `pool.json` y `manifest.json`.

## Docker y preparación futura para Ubuntu

La futura máquina virtual podrá ejecutar el proyecto mediante Docker. Docker empaqueta la aplicación y sus dependencias en un contenedor reproducible, para que el mismo servicio funcione igual en el Mac, Ubuntu y la máquina virtual. La imagen se define en `Dockerfile`.

La exposición pública de la máquina virtual requerirá posteriormente un servidor frontal como Nginx, HTTPS y un servicio de arranque automático. Esa migración no forma parte de esta fase.

## Archivos que no deben publicarse

No subir a GitHub:

- `originals/`
- resultados de escaneo
- vídeos, frames y contact sheets
- entornos virtuales
- `live_rendered/`
- `pool_backups/`
- modelos locales pesados
