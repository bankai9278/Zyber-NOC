"""Labels for values that are already stored in the database.

These functions only format saved results. They do not decide whether a
device is online. Timestamps are stored in UTC and shown in Toronto time.
"""

from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

def _toronto_zone():
    """Return America/Toronto through zoneinfo.

    Windows Python does not ship the IANA time zone database, and this
    project does not add the tzdata package. The local TZif file uses the
    current Toronto rule: EST, UTC-5, with daylight time from the second
    Sunday in March until the first Sunday in November.
    """
    try:
        return ZoneInfo("America/Toronto")
    except ZoneInfoNotFoundError:
        zone_path = Path(__file__).resolve().parent / "zoneinfo" / "America" / "Toronto"
        with zone_path.open("rb") as zone_file:
            return ZoneInfo.from_file(zone_file, key="America/Toronto")


TORONTO = _toronto_zone()

STATUS_LABELS = {
    "online": "Online",
    "offline": "Offline",
    "error": "Error",
    "unknown": "Unknown",
}


def present_overview(overview):
    """Add display labels to a device overview."""
    return {
        "summary": overview["summary"],
        "devices": [present_device(device) for device in overview["devices"]],
    }


def present_device(device):
    """Add display labels to one device row."""
    status = device.get("status") or "unknown"
    parent_name = device.get("parent_name") or None
    unreachable = (
        status == "offline"
        and device.get("parent_status") == "offline"
        and bool(parent_name)
    )
    if unreachable:
        status_label = f"Unreachable via {parent_name}"
        status_class = "unknown"
    else:
        status_label = STATUS_LABELS.get(status, "Unknown")
        status_class = status if status in STATUS_LABELS else "unknown"
    return {
        **device,
        "status": status,
        "status_label": status_label,
        "status_class": status_class,
        "parent_label": parent_name or "None",
        "response_label": response_label(status, device.get("response_time_ms")),
        "checked_label": checked_label(device.get("recorded_at")),
        "created_label": format_local_time(device.get("created_at")) or "Unknown",
        "location_label": device.get("location") or "None",
        "vlan_label": "None" if device.get("vlan") is None else str(device["vlan"]),
        "uptime_label": uptime_label(device.get("uptime_percent")),
        "average_response_label": average_response_label(
            device.get("uptime_percent"),
            device.get("average_response_ms"),
        ),
    }


def present_status_changes(changes):
    """Add display labels to saved status changes, newest first."""
    presented = []
    for change in changes:
        presented.append(
            {
                **change,
                "previous_label": STATUS_LABELS.get(change["previous_status"], change["previous_status"]),
                "new_label": STATUS_LABELS.get(change["new_status"], change["new_status"]),
                "checked_label": format_local_time(change["recorded_at"]) or "Unknown",
            }
        )
    return presented


def present_incidents(incidents):
    """Add display labels to saved outages. No row is created here."""
    presented = []
    for incident in incidents:
        presented.append(
            {
                **incident,
                "change_label": (
                    f"{incident['previous_status']} -> {incident['new_status']}"
                ),
                "checked_label": format_local_time(incident["recorded_at"]) or "Unknown",
                "duration_label": outage_duration_label(
                    incident["recorded_at"],
                    incident.get("recovered_at"),
                ),
                "cause_label": (
                    "caused by parent outage"
                    if incident.get("parent_status_at_time") == "offline"
                    else ""
                ),
            }
        )
    return presented


def outage_duration_label(started_at, recovered_at):
    """Describe a saved outage from its start and recovery timestamps.

    A missing recovery timestamp means the device has not returned online
    in a later saved status change. The label is then ``ongoing``.
    """
    if not recovered_at:
        return "ongoing"
    start = _parse_timestamp(started_at)
    end = _parse_timestamp(recovered_at)
    if start is None or end is None:
        return "ongoing"
    seconds = int((end - start).total_seconds())
    if seconds < 0:
        return "ongoing"
    return _format_duration(seconds)


def group_devices(devices, group_by):
    """Group presented devices by location or VLAN.

    ``None`` means the caller asked for a flat list. Devices with no
    location or VLAN go in Unassigned, and that group is last.
    """
    if group_by not in ("location", "vlan"):
        return None
    buckets = {}
    for device in devices:
        key, label, sort_key = _group_identity(device, group_by)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {"label": label, "sort_key": sort_key, "devices": []}
            buckets[key] = bucket
        bucket["devices"].append(device)
    groups = []
    for bucket in sorted(buckets.values(), key=lambda item: item["sort_key"]):
        counts = {
            "total": len(bucket["devices"]),
            "online": 0,
            "offline": 0,
            "unknown": 0,
            "error": 0,
        }
        for device in bucket["devices"]:
            status = device.get("status") or "unknown"
            if status not in counts:
                status = "unknown"
            counts[status] += 1
        groups.append(
            {
                "label": bucket["label"],
                "summary": _group_summary(bucket["label"], counts),
                "counts": counts,
                "devices": bucket["devices"],
            }
        )
    return groups


def _group_identity(device, group_by):
    if group_by == "location":
        raw = device.get("location")
        text = raw.strip() if isinstance(raw, str) else ""
        if not text:
            return ("", "Unassigned", (1, ""))
        return (text.casefold(), text, (0, text.casefold()))
    vlan = device.get("vlan")
    if isinstance(vlan, bool) or not isinstance(vlan, int):
        return (None, "Unassigned", (1, 0))
    return (vlan, str(vlan), (0, vlan))


def _group_summary(label, counts):
    noun = "device" if counts["total"] == 1 else "devices"
    parts = []
    for status in ("online", "offline", "unknown", "error"):
        count = counts[status]
        if count:
            parts.append(f"{count} {status}")
    return f"{label} - {counts['total']} {noun} - {', '.join(parts)}"


def _parse_timestamp(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _format_duration(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(_count_word(hours, "hour"))
    if minutes:
        parts.append(_count_word(minutes, "minute"))
    if secs or not parts:
        parts.append(_count_word(secs, "second"))
    return " ".join(parts)


def _count_word(count, word):
    if count == 1:
        return f"1 {word}"
    return f"{count} {word}s"


STATUS_COLORS = {
    "online": "#73bf69",
    "offline": "#f2495c",
    "unknown": "#5a5a5a",
    "error": "#ff9830",
}

_NODE_WIDTH = 180
_NODE_HEIGHT = 72
_NODE_GAP_X = 28
_NODE_GAP_Y = 56
_NODE_PAD = 24


def topology_map(devices):
    """Lay out saved devices as a parent/child tree.

    Devices with no parent are roots. The coordinates are for an inline SVG.
    Status colours come from the latest saved result. No saved check stays unknown.
    """
    if not devices:
        return None
    by_id = {device["id"]: device for device in devices}
    children = {device["id"]: [] for device in devices}
    roots = []
    for device in devices:
        parent_id = device.get("parent_id")
        if parent_id in by_id and parent_id != device["id"]:
            children[parent_id].append(device)
        else:
            roots.append(device)
    for kids in children.values():
        kids.sort(key=lambda item: (item.get("name") or "").casefold())
    roots.sort(key=lambda item: (item.get("name") or "").casefold())

    attached = set()

    def attach(device):
        if device["id"] in attached:
            return
        attached.add(device["id"])
        for child in children[device["id"]]:
            attach(child)

    for root in list(roots):
        attach(root)
    for device in devices:
        if device["id"] not in attached:
            roots.append(device)
            attach(device)

    def span(device, seen):
        if device["id"] in seen:
            return 1
        next_seen = seen | {device["id"]}
        kids = [child for child in children[device["id"]] if child["id"] not in next_seen]
        if not kids:
            return 1
        return sum(span(child, next_seen) for child in kids)

    nodes = []
    edges = []
    placed = set()

    def place(device, depth, left, seen):
        if device["id"] in placed:
            return
        placed.add(device["id"])
        next_seen = seen | {device["id"]}
        kids = [child for child in children[device["id"]] if child["id"] not in next_seen]
        width = span(device, seen)
        column_width = _NODE_WIDTH + _NODE_GAP_X
        node_x = _NODE_PAD + left * column_width
        node_x += (width * column_width - _NODE_GAP_X - _NODE_WIDTH) / 2
        node_y = _NODE_PAD + depth * (_NODE_HEIGHT + _NODE_GAP_Y)
        status = device.get("status") if device.get("status") in STATUS_COLORS else "unknown"
        nodes.append(
            {
                "id": device["id"],
                "parent_id": None,
                "status": status,
                "name": device.get("name") or "",
                "short_name": _clip_text(device.get("name") or "", 22),
                "ip_address": device.get("ip_address") or "",
                "type_label": _clip_text(device.get("device_type") or "device", 16),
                "x": node_x,
                "y": node_y,
                "width": _NODE_WIDTH,
                "height": _NODE_HEIGHT,
                "color": STATUS_COLORS[status],
                "text_color": "#ffffff" if status == "unknown" else "#111217",
            }
        )
        child_left = left
        for child in kids:
            place(child, depth + 1, child_left, next_seen)
            child_node = next(item for item in nodes if item["id"] == child["id"])
            child_node["parent_id"] = device["id"]
            edges.append(
                {
                    "parent_id": device["id"],
                    "child_id": child["id"],
                    "status": child_node["status"],
                    "x1": node_x + _NODE_WIDTH / 2,
                    "y1": node_y + _NODE_HEIGHT,
                    "x2": child_node["x"] + _NODE_WIDTH / 2,
                    "y2": child_node["y"],
                }
            )
            child_left += span(child, next_seen)

    column = 0
    for root in roots:
        place(root, 0, column, set())
        column += span(root, set())

    used_columns = max(column, 1)
    max_y = max(node["y"] for node in nodes)
    return {
        "width": _NODE_PAD * 2 + used_columns * _NODE_WIDTH + max(0, used_columns - 1) * _NODE_GAP_X,
        "height": max_y + _NODE_HEIGHT + _NODE_PAD,
        "nodes": nodes,
        "edges": edges,
    }


def _clip_text(value, limit):
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def latency_chart(results):
    """Build an inline SVG description from the last 20 saved checks.

    The line uses the stored median, or the stored response time when an
    older row has no median. A shaded band uses stored minimum and maximum
    values. A point with no measured time is skipped. Missing loss is not
    treated as zero.
    """
    recent = list(results)[-20:]
    samples = []
    for result in recent:
        median = result.get("median_ms")
        if median is None:
            median = result.get("response_time_ms")
        if median is None:
            continue
        samples.append(
            {
                "median": median,
                "min_ms": result.get("min_ms"),
                "max_ms": result.get("max_ms"),
                "loss": result.get("packet_loss_pct"),
            }
        )
    if not samples:
        return None
    width = 640
    height = 160
    padding = 24
    highs = [sample["median"] for sample in samples]
    highs.extend(
        sample["max_ms"] for sample in samples if sample["max_ms"] is not None
    )
    highest = max(highs) or 1
    last_index = len(samples) - 1
    coordinates = []
    dots = []
    band_points = []
    bands = []

    def y_for(value):
        return round(height - padding - (height - padding * 2) * (value / highest), 1)

    for index, sample in enumerate(samples):
        if last_index == 0:
            x_position = width / 2
        else:
            x_position = padding + (width - padding * 2) * index / last_index
        x_position = round(x_position, 1)
        y_position = y_for(sample["median"])
        coordinates.append((x_position, y_position))
        dots.append(
            {
                "x": x_position,
                "y": y_position,
                "color": _loss_color(sample["loss"]),
            }
        )
        if sample["min_ms"] is None or sample["max_ms"] is None:
            if band_points:
                bands.append(_band_polygon(band_points))
                band_points = []
            continue
        band_points.append((x_position, y_for(sample["max_ms"]), y_for(sample["min_ms"])))
    if band_points:
        bands.append(_band_polygon(band_points))
    return {
        "width": width,
        "height": height,
        "points": " ".join(f"{x_position},{y_position}" for x_position, y_position in coordinates),
        "coordinates": coordinates,
        "dots": dots,
        "bands": bands,
        "highest_ms": highest,
        "count": len(samples),
    }


def _loss_color(loss):
    if loss is None:
        return "#8e8e9a"
    if loss <= 0:
        return "#6e9fff"
    if loss <= 20:
        return "#ff9830"
    return "#f2495c"


def _band_polygon(points):
    if len(points) == 1:
        x_position, y_max, y_min = points[0]
        return (
            f"{x_position - 2},{y_max} {x_position + 2},{y_max} "
            f"{x_position + 2},{y_min} {x_position - 2},{y_min}"
        )
    upper = [f"{x_position},{y_max}" for x_position, y_max, _y_min in points]
    lower = [f"{x_position},{y_min}" for x_position, _y_max, y_min in reversed(points)]
    return " ".join(upper + lower)


def ping_stat_labels(results):
    """Labels for the latest saved ping. Missing measurements stay unlabeled."""
    if not results:
        return {"jitter_label": "Unknown", "packet_loss_label": "Unknown"}
    ping_rows = [result for result in results if result.get("check_type") != "tcp"]
    if not ping_rows:
        return {"jitter_label": "Not measured", "packet_loss_label": "Not measured"}
    latest = ping_rows[-1]
    jitter = latest.get("jitter_ms")
    loss = latest.get("packet_loss_pct")
    return {
        "jitter_label": "Not measured" if jitter is None else f"{jitter} ms",
        "packet_loss_label": "Not measured" if loss is None else f"{loss}%",
    }


def present_history(results):
    """Add display labels to monitoring history, oldest first."""
    presented = []
    for result in results:
        presented.append(
            {
                **result,
                "status_label": STATUS_LABELS.get(result["status"], result["status"]),
                "response_label": response_label(result["status"], result["response_time_ms"]),
                "checked_label": checked_label(result["recorded_at"]),
                "check_label": check_label(result),
            }
        )
    return presented


def uptime_label(uptime_percent):
    """Show Unknown until at least one monitoring result has been saved."""
    if uptime_percent is None:
        return "Unknown"
    return f"{uptime_percent}%"


def average_response_label(uptime_percent, average_response_ms):
    """Show Unknown when no check has been saved.

    A saved check with no measured response time is Not measured.
    """
    if uptime_percent is None:
        return "Unknown"
    if average_response_ms is None:
        return "Not measured"
    return f"{average_response_ms} ms"


def check_label(result):
    """Name the saved check without implying a check that did not run."""
    if result.get("check_type") == "tcp":
        return f"TCP {result.get('port')}"
    return "Ping"


HISTORY_COLOURS = {
    "online": "#73bf69",
    "offline": "#f2495c",
    "error": "#ff9830",
    "empty": "#2a2d33",
}
_HISTORY_RANK = {"online": 1, "error": 2, "offline": 3}


def toronto_window(start_day, end_day):
    """Return the UTC instants that bound these Toronto calendar days."""
    start = datetime.combine(start_day, time.min, tzinfo=TORONTO)
    end = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=TORONTO)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def status_history(rows, device_ids, days, today):
    """Build one coloured block per Toronto day from saved results.

    Offline is worse than error, and error is worse than online. A day
    with no saved check stays empty. Uptime uses only the checks inside
    the window.
    """
    start_day = today - timedelta(days=days - 1)
    by_device = {device_id: {} for device_id in device_ids}
    for row in rows:
        local = _local_moment(row.get("recorded_at") or row.get("first_at"))
        status = row.get("status")
        device_id = row.get("device_id")
        count = row.get("checks", 1)
        if (
            local is None
            or status not in _HISTORY_RANK
            or device_id not in by_device
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 1
        ):
            continue
        day = local.date()
        if day < start_day or day > today:
            continue
        bucket = by_device[device_id].get(day)
        if bucket is None:
            bucket = {
                "online": 0,
                "error": 0,
                "offline": 0,
                "worst": status,
                "first_worst": local,
            }
            by_device[device_id][day] = bucket
        bucket[status] += count
        if _HISTORY_RANK[status] > _HISTORY_RANK[bucket["worst"]] or (
            status == bucket["worst"] and local < bucket["first_worst"]
        ):
            bucket["worst"] = status
            bucket["first_worst"] = local
    bars = {}
    for device_id in device_ids:
        blocks = []
        online = 0
        total = 0
        for offset in range(days):
            day = start_day + timedelta(days=offset)
            bucket = by_device[device_id].get(day)
            if bucket is None:
                blocks.append(
                    {
                        "kind": "empty",
                        "color": HISTORY_COLOURS["empty"],
                        "title": f"{_day_label(day)} - No checks",
                    }
                )
                continue
            day_total = bucket["online"] + bucket["error"] + bucket["offline"]
            online += bucket["online"]
            total += day_total
            blocks.append(
                {
                    "kind": bucket["worst"],
                    "color": HISTORY_COLOURS[bucket["worst"]],
                    "title": _history_title(day, bucket),
                }
            )
        if total == 0:
            uptime_label = "No data"
        else:
            uptime_label = f"{int(online * 100 / total + 0.5)}%"
        bars[device_id] = {"blocks": blocks, "uptime_label": uptime_label}
    return bars


def _local_moment(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(TORONTO)


def _day_label(day):
    return f"{day.strftime('%b')} {day.day}, {day.year}"


def _clock_label(moment):
    text = moment.strftime("%I:%M %p")
    if text.startswith("0"):
        return text[1:]
    return text


def _history_title(day, bucket):
    label = _day_label(day)
    worst = bucket["worst"]
    if worst == "online":
        count = bucket["online"]
        noun = "check" if count == 1 else "checks"
        return f"{label} - Online ({count} {noun})"
    count = bucket[worst]
    times = "time" if count == 1 else "times"
    name = "Offline" if worst == "offline" else "Error"
    clock = _clock_label(bucket["first_worst"])
    return f"{label} - {name} {count} {times}, first at {clock}"


def response_label(status, response_time_ms):
    """Describe a saved response time without filling in a missing check."""
    if status == "unknown":
        return "Not checked"
    if response_time_ms is None:
        return "Not measured"
    return f"{response_time_ms} ms"


def checked_label(recorded_at):
    """Show a stored UTC check time in America/Toronto local time."""
    if not recorded_at:
        return "Not checked"
    local = format_local_time(recorded_at)
    if local is None:
        return "Not checked"
    return local


def format_local_time(value):
    """Convert a stored UTC timestamp to America/Toronto.

    The database value is left unchanged. The returned text is for display.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(TORONTO)
    return local.strftime("%Y-%m-%d %H:%M:%S") + " ET"
