"""Worker de la cola de IA (etapa 4C).

Uso:
  manage.py cola_worker --once        # procesa lo vencido y sale (tarea cada 2 min)
  manage.py cola_worker               # bucle persistente (servicio)

Sin broker externo: MySQL + SKIP LOCKED. Seguro ante solapes.
"""
import logging
import time

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Procesa trabajos pendientes de la cola de IA."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true",
                            help="Procesa un lote y sale.")
        parser.add_argument("--limite", type=int, default=5,
                            help="Trabajos por lote.")
        parser.add_argument("--intervalo", type=int, default=30,
                            help="Segundos entre lotes en modo bucle.")

    def handle(self, *args, **opts):
        from app.iahelp.servicios.fondo import latir, tomar_lote, procesar_trabajo
        limite = opts["limite"]
        if opts["once"]:
            latir()
            jobs = tomar_lote(limite)
            for job in jobs:
                ok = procesar_trabajo(job)
                self.stdout.write(f"{job.tipo} #{job.ticket_id}: {'OK' if ok else 'reintentable/ERROR'}")
            latir()
            return
        self.stdout.write("cola_worker en bucle (Ctrl+C para detener)...")
        try:
            while True:
                latir()
                jobs = tomar_lote(limite)
                for job in jobs:
                    ok = procesar_trabajo(job)
                    logger.info("%s #%s: %s", job.tipo, job.ticket_id, "OK" if ok else "reintento")
                time.sleep(opts["intervalo"])
        except KeyboardInterrupt:
            self.stdout.write("detenido.")
