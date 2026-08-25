from collections import defaultdict
from statistics import mean

from django.db.models import Max, Sum

from .models import (
    AssemblyLine,
    AssemblyRouteStep,
    AssemblyStation,
    ProductionPlan,
    ReworkOrder,
    StationEventType,
    UnitStationEvent,
)


def format_seconds(seconds):
    if seconds is None:
        return "-"
    seconds = round(seconds)
    minutes, remainder = divmod(seconds, 60)
    return f"{minutes} min {remainder:02d} s" if minutes else f"{remainder} s"


def build_production_metrics(start_date, end_date, line_id=None):
    """Calcula indicadores solo con eventos operativos auditados en el periodo."""
    lines = AssemblyLine.objects.filter(is_active=True).order_by("code")
    if line_id:
        lines = lines.filter(pk=line_id)
    lines = list(lines)
    line_ids = [line.pk for line in lines]
    events = list(
        UnitStationEvent.objects.filter(
            station__line_id__in=line_ids,
            event_at__date__range=(start_date, end_date),
        )
        .select_related("unit", "station__line", "route_step__route")
        .order_by("unit_id", "route_step_id", "event_at", "id")
    )
    completed_events = [event for event in events if event.event_type == StationEventType.COMPLETED]
    station_cycles = defaultdict(list)
    active_starts = {}
    for event in events:
        key = (event.unit_id, event.route_step_id)
        if event.event_type in {StationEventType.STARTED, StationEventType.RESUMED}:
            active_starts[key] = event.event_at
        elif event.event_type == StationEventType.COMPLETED and key in active_starts:
            elapsed = (event.event_at - active_starts.pop(key)).total_seconds()
            if elapsed >= 0:
                station_cycles[event.station_id].append(elapsed)

    failure_counts = defaultdict(int)
    for event in events:
        if event.event_type == StationEventType.FAILED:
            failure_counts[event.station_id] += 1
    completion_times = defaultdict(list)
    for event in completed_events:
        completion_times[event.station_id].append(event.event_at)

    stations = AssemblyStation.objects.filter(line_id__in=line_ids, is_active=True).select_related("line").order_by(
        "line__code", "sequence", "code"
    ).values(
        "id",
        "code",
        "name",
        "takt_time_seconds",
        "line__takt_time_seconds",
        "line__code",
    )
    station_metrics = []
    seen_stations = set()
    for station in stations:
        station_id = station["id"]
        if station_id in seen_stations:
            continue
        seen_stations.add(station_id)
        completions = completion_times[station_id]
        takt_intervals = [
            (current - previous).total_seconds()
            for previous, current in zip(completions, completions[1:])
            if current >= previous
        ]
        target_takt = station["takt_time_seconds"] or station["line__takt_time_seconds"]
        cycle_seconds = mean(station_cycles[station_id]) if station_cycles[station_id] else None
        real_takt = mean(takt_intervals) if takt_intervals else None
        station_metrics.append(
            {
                "line_code": station["line__code"],
                "station_code": station["code"],
                "station_name": station["name"],
                "completed_count": len(completions),
                "failure_count": failure_counts[station_id],
                "average_cycle": format_seconds(cycle_seconds),
                "real_takt": format_seconds(real_takt),
                "target_takt": format_seconds(target_takt),
                "takt_variance": format_seconds(real_takt - target_takt) if real_takt is not None and target_takt else "-",
                "performance_percent": round((target_takt / real_takt) * 100, 1) if real_takt and target_takt else None,
            }
        )

    rework_counts = defaultdict(int)
    for rework in ReworkOrder.objects.filter(
        station_detected__line_id__in=line_ids,
        opened_at__date__range=(start_date, end_date),
    ):
        rework_counts[rework.defect_code or "Sin codigo"] += 1
    rework_metrics = [
        {"defect_code": defect_code, "count": count}
        for defect_code, count in sorted(rework_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    route_ids = {event.route_step.route_id for event in completed_events if event.route_step_id}
    terminal_sequences = dict(
        AssemblyRouteStep.objects.filter(route_id__in=route_ids, is_active=True)
        .values("route_id")
        .annotate(sequence=Max("sequence"))
        .values_list("route_id", "sequence")
    )
    completed_units_by_line = defaultdict(set)
    for event in completed_events:
        if event.route_step_id and terminal_sequences.get(event.route_step.route_id) == event.route_step.sequence:
            completed_units_by_line[event.station.line_id].add(event.unit_id)
    planned_by_line = dict(
        ProductionPlan.objects.filter(line_id__in=line_ids, planned_date__range=(start_date, end_date))
        .values("line_id")
        .annotate(quantity=Sum("target_quantity"))
        .values_list("line_id", "quantity")
    )
    productivity = []
    for line in lines:
        completed = len(completed_units_by_line[line.pk])
        planned = planned_by_line.get(line.pk) or 0
        productivity.append(
            {
                "line_code": line.code,
                "completed": completed,
                "planned": planned,
                "fulfillment_percent": round((completed / planned) * 100, 1) if planned else None,
            }
        )

    total_cycles = sum(len(cycles) for cycles in station_cycles.values())
    total_failures = sum(failure_counts.values())
    total_completed = sum(len(units) for units in completed_units_by_line.values())
    performance_values = [metric["performance_percent"] for metric in station_metrics if metric["performance_percent"] is not None]
    return {
        "station_metrics": station_metrics,
        "rework_metrics": rework_metrics,
        "productivity": productivity,
        "summary": {
            "cycle_count": total_cycles,
            "failure_count": total_failures,
            "completed_units": total_completed,
            "performance_percent": round(mean(performance_values), 1) if performance_values else None,
            "quality_percent": round((total_completed / (total_completed + total_failures)) * 100, 1)
            if total_completed + total_failures
            else None,
            "availability_percent": None,
        },
    }
