"""
Trae el registro maestro de cambios desde `register.csv` (CC-2026-027).

Git es la fuente del expediente; Kore solo necesita saber que cambios existen
para poder firmarlos. Por eso esto importa y no exporta: capturar los cambios a
mano en la base garantizaria que se desincronicen del repositorio.
"""
import csv
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand

from changecontrol.models import ChangeControl

ROOT = Path(__file__).resolve().parents[3]
REGISTER = ROOT / "docs" / "quality" / "change-control" / "register.csv"


class Command(BaseCommand):
    help = "Sincroniza los controles de cambio desde docs/quality/change-control/register.csv"

    def add_arguments(self, parser):
        parser.add_argument("--file", default=str(REGISTER))

    def handle(self, *args, **options):
        ruta = Path(options["file"])
        if not ruta.exists():
            self.stderr.write(f"No existe {ruta}")
            return

        creados = actualizados = 0
        with ruta.open(encoding="utf-8-sig", newline="") as fuente:
            for fila in csv.DictReader(fuente):
                code = (fila.get("id") or "").strip()
                if not code:
                    continue
                anio = code.split("-")[1] if "-" in code else ""
                carpeta = f"docs/quality/change-control/changes/{anio}/"
                try:
                    apertura = date.fromisoformat((fila.get("fecha_apertura") or "").strip())
                except ValueError:
                    apertura = None
                if apertura is None:
                    self.stderr.write(f"{code}: fecha de apertura invalida, se omite")
                    continue

                _, creado = ChangeControl.objects.update_or_create(
                    code=code,
                    defaults={
                        "title": (fila.get("titulo") or "").strip(),
                        "areas": (fila.get("areas") or "").strip(),
                        "risk": (fila.get("riesgo") or "").strip(),
                        "status": (fila.get("estado") or "").strip(),
                        "opened_on": apertura,
                        "document_path": carpeta,
                    },
                )
                creados += 1 if creado else 0
                actualizados += 0 if creado else 1

        self.stdout.write(f"Controles creados: {creados} | actualizados: {actualizados}")
