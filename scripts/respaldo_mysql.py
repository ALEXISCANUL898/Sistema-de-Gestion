"""Respaldo MySQL sin exponer la clave en la línea de comandos.

Uso: venv\\Scripts\\python.exe scripts\\respaldo_mysql.py [--dir BACKUPS]
Lee .env de la raíz, vuelca esquema+datos con --single-transaction,
conserva 7 días. Sin rutinas/eventos (la app no los usa). No toca producción.
"""
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
BACKUP_DIR = Path(sys.argv[sys.argv.index("--dir") + 1]) if "--dir" in sys.argv else BASE / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
RETENCION_DIAS = 7

MYSQLDUMP = r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysqldump.exe"


def parse_env(path):
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def main():
    cfg = parse_env(BASE / ".env")
    db = cfg.get("DB_NAME", "Matris")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = BACKUP_DIR / f"{db}-{ts}.sql"
    env = dict(os.environ, MYSQL_PWD=cfg.get("DB_PASSWORD", ""))  # clave por entorno, no CLI
    cmd = [
        MYSQLDUMP,
        f"--host={cfg.get('DB_HOST', '127.0.0.1')}",
        f"--port={cfg.get('DB_PORT', '3306')}",
        f"--user={cfg.get('DB_USER', 'root')}",
        # --no-tablespaces: app_tickets no tiene PROCESS; sin rutinas/eventos
        # porque la app Django no los usa (verificado: sin triggers).
        "--single-transaction", "--no-tablespaces",
        "--set-gtid-purged=OFF",
        db,
    ]
    with open(out, "w", encoding="utf-8") as fh:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, text=True,
                           env=env, timeout=600)
    if r.returncode != 0:
        out.unlink(missing_ok=True)
        print(f"ERROR mysqldump: {r.stderr.strip()[:500]}")
        return 1
    # Verificación: tablas esperadas + marca de cierre del volcado
    txt = out.read_text(encoding="utf-8", errors="replace")
    tablas = txt.count("CREATE TABLE ")
    ok = "Dump completed" in txt
    print(f"respaldo: {out.name} ({out.stat().st_size // 1024} KB, tablas={tablas}, cierre={'OK' if ok else 'FALTA'})")
    if not ok:
        return 1
    # Retención
    limite = datetime.now() - timedelta(days=RETENCION_DIAS)
    for f in BACKUP_DIR.glob(f"{db}-*.sql"):
        try:
            fecha = datetime.strptime(f.stem.split("-", 1)[1], "%Y%m%d-%H%M%S")
        except (IndexError, ValueError):
            continue
        if fecha < limite:
            f.unlink()
            print(f"retención: eliminado {f.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
