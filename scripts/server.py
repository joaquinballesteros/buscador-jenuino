#!/usr/bin/env python3
"""Servidor web del Buscador JENUI. Ejecutar desde la raíz del proyecto:

    python scripts/server.py
    uvicorn server:app --port 8000      # 'app' se expone para uvicorn (desde scripts/)

Normalmente se lanza con ``scripts/run.sh``, que ya usa el Python del entorno
virtual del proyecto.

La lógica vive en jenui.web.create_app.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

try:
    from jenui.config import Settings
    from jenui.web import create_app
except ModuleNotFoundError as exc:
    venv_python = _ROOT / ".venv" / "bin" / "python"
    hint = (f"    {venv_python} scripts/server.py"
            if venv_python.exists() else
            "    source .venv/bin/activate  &&  python scripts/server.py")
    sys.exit(
        f"\n[ERROR] Falta la dependencia '{exc.name}'.\n"
        f"Estás usando un Python sin las dependencias instaladas "
        f"(seguramente el del sistema, sin activar el entorno virtual).\n\n"
        f"Arráncalo con el entorno del proyecto:\n{hint}\n\n"
        f"O instala las dependencias:  pip install -r requirements.txt\n"
    )

app = create_app(Settings.load())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
