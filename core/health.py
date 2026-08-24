from __future__ import annotations

from django.db import connection
from django.http import JsonResponse
from django.utils import timezone


def healthz(request):
    """Healthcheck liviano para balanceador/monitoring."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # pragma: no cover - depende del entorno de BD
        return JsonResponse(
            {
                "status": "error",
                "database": "down",
                "schema": getattr(connection, "schema_name", "unknown"),
                "timestamp": timezone.now().isoformat(),
                "error": str(exc),
            },
            status=503,
        )

    return JsonResponse(
        {
            "status": "ok",
            "database": "up",
            "schema": getattr(connection, "schema_name", "unknown"),
            "timestamp": timezone.now().isoformat(),
        },
        status=200,
    )

