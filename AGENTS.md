# Instrucciones del proyecto

## Objetivo

Border Transit mantiene un pool permanente de imágenes documentales y una web pública que muestra sus transformaciones visuales.

## Reglas de seguridad

- No ejecutar `git push`, despliegues ni publicaciones sin autorización explícita del usuario.
- No ejecutar `git pull` mientras existan cambios locales sin revisar.
- No borrar, mover ni sobrescribir `originals/`, `metadata/`, `pool.json` o `manifest.json` sin confirmar antes el alcance.
- No incorporar automáticamente todas las imágenes de `originals/` al pool permanente.
- Solo las imágenes seleccionadas explícitamente pueden entrar en `pool.json` y generar archivos permanentes en `rendered/`.
- Las imágenes LIVE son temporales y deben vivir únicamente en memoria; nunca deben escribirse en disco ni añadirse a Git.
- En Git solo deben estar los originales necesarios para renderizar el pool publicado (los IDs de `pool_selection.json`); el resto de `originals/`, escaneos, vídeos, frames, contact sheets, entornos virtuales y copias de seguridad no deben subirse a GitHub.

## Flujo actual

1. Trabajar y revisar cambios localmente en el Mac.
2. Mantener la web publicada sin cambios hasta que el usuario autorice una publicación.
3. Generar únicamente el pool permanente seleccionado.
4. Revisar `git diff` y el estado del pool antes de cualquier commit.

## Compatibilidad

- Conservar el comportamiento actual de la web mientras se reorganiza el proyecto.
- Mantener rutas y nombres de archivos existentes salvo que exista una razón clara y documentada.
- Preparar la ejecución futura en Ubuntu mediante Docker, sin forzar todavía la migración.
