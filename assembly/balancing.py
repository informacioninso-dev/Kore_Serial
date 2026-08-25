from collections import defaultdict
from math import floor
from statistics import mean

from django.core.exceptions import ValidationError

from core.models import ApprovalStatus

from .metrics import format_seconds
from .models import (
    AssemblyRoute,
    AssemblyStation,
    StationEventType,
    UnitStationEvent,
)


def _round(value, digits=1):
    return round(value, digits) if value is not None else None


def _route_for_study(study):
    if study.route_id:
        return study.route
    route = AssemblyRoute.objects.filter(
        version=study.version,
        is_active=True,
        approval_status=ApprovalStatus.APPROVED,
    ).order_by("-approved_at", "code", "revision").first()
    if route is not None:
        return route
    return AssemblyRoute.objects.filter(version=study.version, is_active=True).order_by("code", "revision").first()


def _measured_station_times(study, route):
    if not study.actual_start_date or not study.actual_end_date:
        return {}

    events = (
        UnitStationEvent.objects.filter(
            station__line=study.line,
            route_step__route=route,
            event_at__date__range=(study.actual_start_date, study.actual_end_date),
        )
        .select_related("station", "route_step")
        .order_by("unit_id", "route_step_id", "event_at", "id")
    )
    active_starts = {}
    cycles = defaultdict(list)
    completions = defaultdict(list)
    for event in events:
        key = (event.unit_id, event.route_step_id)
        if event.event_type in {StationEventType.STARTED, StationEventType.RESUMED}:
            active_starts[key] = event.event_at
        elif event.event_type == StationEventType.COMPLETED:
            completions[event.station_id].append(event.event_at)
            if key in active_starts:
                elapsed = (event.event_at - active_starts.pop(key)).total_seconds()
                if elapsed >= 0:
                    cycles[event.station_id].append(elapsed)

    measured = {}
    for station_id, station_completions in completions.items():
        station_completions = sorted(station_completions)
        intervals = [
            (current - previous).total_seconds()
            for previous, current in zip(station_completions, station_completions[1:])
            if current >= previous
        ]
        measured[station_id] = {
            "actual_cycle_seconds": mean(cycles[station_id]) if cycles[station_id] else None,
            "real_takt_seconds": mean(intervals) if intervals else None,
            "completed_count": len(station_completions),
        }
    return measured


def _station_status(*, standard_seconds, target_takt_seconds, load_percent, actual_cycle_seconds, real_takt_seconds):
    if load_percent is not None and load_percent > 100:
        return "BOTTLENECK"
    if target_takt_seconds and standard_seconds > target_takt_seconds:
        return "BOTTLENECK"
    if target_takt_seconds and actual_cycle_seconds and actual_cycle_seconds > target_takt_seconds:
        return "BOTTLENECK"
    if target_takt_seconds and real_takt_seconds and real_takt_seconds > target_takt_seconds:
        return "BOTTLENECK"
    if target_takt_seconds and standard_seconds and standard_seconds < target_takt_seconds * 0.75:
        return "UNDERLOADED"
    return "BALANCED"


def _build_simulation(stations, target_takt_seconds):
    if not target_takt_seconds:
        return []

    overloaded = [
        {
            "station_code": station["station_code"],
            "station_name": station["station_name"],
            "seconds": station["standard_seconds"] - target_takt_seconds,
        }
        for station in stations
        if station["standard_seconds"] > target_takt_seconds
    ]
    underloaded = [
        {
            "station_code": station["station_code"],
            "station_name": station["station_name"],
            "seconds": target_takt_seconds - station["standard_seconds"],
        }
        for station in stations
        if station["standard_seconds"] < target_takt_seconds
    ]

    moves = []
    for source in overloaded:
        remaining = source["seconds"]
        for target in underloaded:
            if remaining <= 0:
                break
            if target["seconds"] <= 0:
                continue
            seconds = min(remaining, target["seconds"])
            target["seconds"] -= seconds
            remaining -= seconds
            moves.append(
                {
                    "source_station_code": source["station_code"],
                    "source_station_name": source["station_name"],
                    "target_station_code": target["station_code"],
                    "target_station_name": target["station_name"],
                    "seconds": round(seconds),
                    "seconds_display": format_seconds(seconds),
                    "reason": "Mover contenido de trabajo para acercar ambas estaciones al takt objetivo.",
                }
            )
        if remaining > 0:
            moves.append(
                {
                    "source_station_code": source["station_code"],
                    "source_station_name": source["station_name"],
                    "target_station_code": "",
                    "target_station_name": "Capacidad adicional",
                    "seconds": round(remaining),
                    "seconds_display": format_seconds(remaining),
                    "reason": "No hay holgura suficiente en estaciones vecinas; evaluar operador adicional, herramienta paralela o cambio de metodo.",
                }
            )
    return moves


def _build_recommendations(stations, simulation):
    recommendations = []
    bottlenecks = [station for station in stations if station["status"] == "BOTTLENECK"]
    for station in bottlenecks:
        reasons = []
        if station["load_percent"] and station["load_percent"] > 100:
            reasons.append(f"carga {station['load_percent']}% del turno")
        if station["target_takt_seconds"] and station["standard_seconds"] > station["target_takt_seconds"]:
            reasons.append(f"tiempo estandar {station['standard_seconds_display']} sobre takt {station['target_takt_display']}")
        if station["actual_cycle_seconds"] and station["target_takt_seconds"] and station["actual_cycle_seconds"] > station["target_takt_seconds"]:
            reasons.append(f"ciclo real {station['actual_cycle_display']} sobre takt")
        recommendations.append(
            {
                "tone": "danger",
                "station_code": station["station_code"],
                "title": f"Cuello de botella en {station['station_code']}",
                "body": "; ".join(reasons) or "La estacion concentra la mayor carga de trabajo.",
            }
        )

    for move in simulation[:4]:
        recommendations.append(
            {
                "tone": "warning",
                "station_code": move["source_station_code"],
                "title": f"Simular redistribucion desde {move['source_station_code']}",
                "body": f"{move['seconds_display']} hacia {move['target_station_name']}. {move['reason']}",
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "tone": "success",
                "station_code": "",
                "title": "Linea dentro de balance inicial",
                "body": "No se detectan estaciones sobre takt o sobre capacidad con los datos disponibles.",
            }
        )
    return recommendations


def build_line_balance_snapshot(study):
    route = _route_for_study(study)
    if route is None:
        raise ValidationError("No existe una ruta activa para la version seleccionada.")

    stations = list(AssemblyStation.objects.filter(line=study.line, is_active=True).order_by("sequence", "code"))
    station_rows = {
        station.pk: {
            "station_id": station.pk,
            "station_code": station.code,
            "station_name": station.name,
            "station_sequence": station.sequence,
            "target_takt_seconds": station.takt_time_seconds or study.target_takt_seconds or study.line.takt_time_seconds,
            "standard_seconds": 0,
            "steps": [],
        }
        for station in stations
    }

    route_steps = (
        route.steps.filter(is_active=True, station__line=study.line)
        .select_related("station")
        .order_by("station__sequence", "sequence")
    )
    for step in route_steps:
        row = station_rows[step.station_id]
        expected_seconds = step.expected_duration_seconds or 0
        row["standard_seconds"] += expected_seconds
        row["steps"].append(
            {
                "step_id": step.pk,
                "sequence": step.sequence,
                "name": step.name,
                "expected_seconds": expected_seconds,
                "expected_display": format_seconds(expected_seconds),
            }
        )

    measured = _measured_station_times(study, route)
    target_takt_seconds = study.target_takt_seconds or study.line.takt_time_seconds
    if not target_takt_seconds:
        standard_values = [row["standard_seconds"] for row in station_rows.values() if row["standard_seconds"]]
        target_takt_seconds = max(standard_values) if standard_values else None

    calculated_stations = []
    for row in station_rows.values():
        station_measurement = measured.get(row["station_id"], {})
        target = row["target_takt_seconds"] or target_takt_seconds
        standard_seconds = row["standard_seconds"]
        load_seconds = standard_seconds * study.planned_units
        capacity_seconds = study.shift_duration_seconds
        actual_cycle_seconds = station_measurement.get("actual_cycle_seconds")
        real_takt_seconds = station_measurement.get("real_takt_seconds")
        load_percent = (load_seconds / capacity_seconds) * 100 if capacity_seconds else None
        capacity_units = floor(capacity_seconds / standard_seconds) if standard_seconds else None
        status = _station_status(
            standard_seconds=standard_seconds,
            target_takt_seconds=target,
            load_percent=load_percent,
            actual_cycle_seconds=actual_cycle_seconds,
            real_takt_seconds=real_takt_seconds,
        )
        calculated_stations.append(
            {
                **row,
                "target_takt_seconds": target,
                "target_takt_display": format_seconds(target),
                "standard_seconds_display": format_seconds(standard_seconds),
                "load_seconds": round(load_seconds),
                "load_seconds_display": format_seconds(load_seconds),
                "capacity_seconds": capacity_seconds,
                "capacity_seconds_display": format_seconds(capacity_seconds),
                "capacity_units": capacity_units,
                "load_percent": _round(load_percent),
                "actual_cycle_seconds": _round(actual_cycle_seconds),
                "actual_cycle_display": format_seconds(actual_cycle_seconds),
                "real_takt_seconds": _round(real_takt_seconds),
                "real_takt_display": format_seconds(real_takt_seconds),
                "completed_count": station_measurement.get("completed_count", 0),
                "status": status,
            }
        )

    station_count = len(calculated_stations)
    total_standard_seconds = sum(station["standard_seconds"] for station in calculated_stations)
    line_cycle_seconds = max((station["standard_seconds"] for station in calculated_stations), default=0)
    bottleneck = max(calculated_stations, key=lambda station: station["standard_seconds"], default=None)
    balance_efficiency = (
        (total_standard_seconds / (station_count * line_cycle_seconds)) * 100
        if station_count and line_cycle_seconds
        else None
    )
    capacity_units_per_shift = floor(study.shift_duration_seconds / line_cycle_seconds) if line_cycle_seconds else None
    simulation = _build_simulation(calculated_stations, target_takt_seconds)
    recommendations = _build_recommendations(calculated_stations, simulation)
    snapshot = {
        "line": {"id": study.line_id, "code": study.line.code, "name": study.line.name},
        "version": {"id": study.version_id, "code": study.version.code, "name": study.version.name},
        "route": {"id": route.pk, "code": route.code, "revision": route.revision, "name": route.name},
        "planned_units": study.planned_units,
        "shift_duration_seconds": study.shift_duration_seconds,
        "shift_duration_display": format_seconds(study.shift_duration_seconds),
        "target_takt_seconds": target_takt_seconds,
        "target_takt_display": format_seconds(target_takt_seconds),
        "actual_period": {
            "start": study.actual_start_date.isoformat() if study.actual_start_date else "",
            "end": study.actual_end_date.isoformat() if study.actual_end_date else "",
        },
        "stations": calculated_stations,
        "simulation": simulation,
        "summary": {
            "station_count": station_count,
            "total_standard_seconds": total_standard_seconds,
            "total_standard_display": format_seconds(total_standard_seconds),
            "line_cycle_seconds": line_cycle_seconds,
            "line_cycle_display": format_seconds(line_cycle_seconds),
            "bottleneck_station_code": bottleneck["station_code"] if bottleneck else "",
            "bottleneck_station_name": bottleneck["station_name"] if bottleneck else "",
            "balance_efficiency_percent": _round(balance_efficiency),
            "capacity_units_per_shift": capacity_units_per_shift,
            "demand_gap_units": max(study.planned_units - capacity_units_per_shift, 0)
            if capacity_units_per_shift is not None
            else None,
        },
    }
    return snapshot, recommendations
