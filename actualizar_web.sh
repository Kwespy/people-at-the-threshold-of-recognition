#!/bin/bash
set -e

PROJECT="$HOME/Desktop/border-transit-pool"
cd "$PROJECT"

echo
echo "========================================"
echo "PEOPLE AT THE THRESHOLD OF RECOGNITION"
echo "ACTUALIZANDO WEB..."
echo "========================================"
echo

# ------------------------------------------------------------
# 1. Elegir Python del entorno virtual si existe
# ------------------------------------------------------------
if [ -x "$PROJECT/.venv/bin/python" ]; then
    PYTHON="$PROJECT/.venv/bin/python"
else
    PYTHON="python3"
fi

# ------------------------------------------------------------
# 2. Regenerar pool / renders / manifest
# ------------------------------------------------------------
echo "1/4 — Generando pool y renderizados..."
"$PYTHON" "$PROJECT/generate_pool.py"

# ------------------------------------------------------------
# 3. Preparar todos los cambios para Git
# ------------------------------------------------------------
echo
echo "2/4 — Preparando cambios..."
git add -A

# ------------------------------------------------------------
# 4. Crear commit solo si realmente hay cambios
# ------------------------------------------------------------
echo
echo "3/4 — Guardando versión..."

if git diff --cached --quiet; then
    echo "No hay cambios nuevos para guardar."
else
    TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
    git commit -m "Update website $TIMESTAMP"
fi

# ------------------------------------------------------------
# 5. Subir a GitHub
# Render detectará el push y actualizará automáticamente la web
# ------------------------------------------------------------
echo
echo "4/4 — Subiendo a GitHub..."
git push

echo
echo "========================================"
echo "✓ ACTUALIZACIÓN ENVIADA"
echo "Render actualizará la web automáticamente."
echo "========================================"
echo
