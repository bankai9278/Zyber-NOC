"""Tests for display labels. These do not change stored UTC timestamps."""

from datetime import date

from app.presentation import (
    checked_label,
    format_local_time,
    group_devices,
    latency_chart,
    outage_duration_label,
    present_incidents,
    status_history,
    topology_map,
)


def test_timestamps_are_shown_in_toronto_local_time():
    winter = "2026-01-15T15:04:05+00:00"
    summer = "2026-07-15T15:04:05+00:00"

    assert format_local_time(winter) == "2026-01-15 10:04:05 ET"
    assert format_local_time(summer) == "2026-07-15 11:04:05 ET"
    assert checked_label(winter) == "2026-01-15 10:04:05 ET"
    assert checked_label(None) == "Not checked"
    assert format_local_time("not-a-time") is None


def test_latency_chart_uses_only_saved_response_times():
    assert latency_chart([]) is None
    assert latency_chart([{"response_time_ms": None}]) is None

    chart = latency_chart(
        [{"response_time_ms": value} for value in (4, None, 8)]
    )

    assert chart["count"] == 2
    assert chart["highest_ms"] == 8
    assert chart["points"]
    assert len(chart["coordinates"]) == 2
    assert "<script" not in chart["points"]


def test_latency_chart_draws_a_band_only_where_min_and_max_were_saved():
    chart = latency_chart(
        [
            {"response_time_ms": 10, "packet_loss_pct": None},
            {"response_time_ms": None, "min_ms": None, "max_ms": None},
            {
                "response_time_ms": 20,
                "median_ms": 20,
                "min_ms": 15,
                "max_ms": 30,
                "packet_loss_pct": 0,
            },
            {
                "response_time_ms": 18,
                "median_ms": 18,
                "min_ms": 16,
                "max_ms": 22,
                "packet_loss_pct": 12,
            },
            {
                "response_time_ms": 25,
                "median_ms": 25,
                "min_ms": 21,
                "max_ms": 40,
                "packet_loss_pct": 40,
            },
        ]
    )

    assert chart["count"] == 4
    assert chart["highest_ms"] == 40
    assert chart["dots"][0]["color"] == "#8e8e9a"
    assert chart["dots"][1]["color"] == "#6e9fff"
    assert chart["dots"][2]["color"] == "#ff9830"
    assert chart["dots"][3]["color"] == "#f2495c"
    assert len(chart["bands"]) == 1


def test_outage_duration_is_calculated_from_stored_timestamps():
    start = "2026-01-15T15:00:00+00:00"

    assert outage_duration_label(start, None) == "ongoing"
    assert outage_duration_label(start, "") == "ongoing"
    assert outage_duration_label(start, start) == "0 seconds"
    assert outage_duration_label(start, "2026-01-15T15:01:30+00:00") == "1 minute 30 seconds"
    assert outage_duration_label(start, "2026-01-15T16:05:30+00:00") == "1 hour 5 minutes 30 seconds"
    assert outage_duration_label(start, "2026-01-15T17:00:00+00:00") == "2 hours"
    assert outage_duration_label(start, "2026-01-15T14:00:00+00:00") == "ongoing"

    presented = present_incidents(
        [
            {
                "device_name": "Core router",
                "previous_status": "online",
                "new_status": "offline",
                "recorded_at": start,
                "recovered_at": "2026-01-15T16:05:30+00:00",
            }
        ]
    )

    assert presented[0]["change_label"] == "online -> offline"
    assert presented[0]["checked_label"] == "2026-01-15 10:00:00 ET"
    assert presented[0]["duration_label"] == "1 hour 5 minutes 30 seconds"


def test_devices_group_by_location_or_vlan_with_unassigned_last():
    devices = [
        {"name": "Lab server", "location": "Lab", "vlan": None, "status": "online"},
        {"name": "Floor switch", "location": "Floor 3", "vlan": 10, "status": "offline"},
        {"name": "Closet phone", "location": None, "vlan": 2, "status": "unknown"},
        {"name": "Spare", "location": "  ", "vlan": None, "status": "error"},
    ]

    by_location = group_devices(devices, "location")
    by_vlan = group_devices(devices, "vlan")

    assert [group["summary"] for group in by_location] == [
        "Floor 3 - 1 device - 1 offline",
        "Lab - 1 device - 1 online",
        "Unassigned - 2 devices - 1 unknown, 1 error",
    ]
    assert [group["summary"] for group in by_vlan] == [
        "2 - 1 device - 1 unknown",
        "10 - 1 device - 1 offline",
        "Unassigned - 2 devices - 1 online, 1 error",
    ]
    assert group_devices(devices, "none") is None
    assert by_location[-1]["devices"][0]["name"] == "Closet phone"
    assert by_vlan[0]["label"] == "2"
    assert by_vlan[-1]["label"] == "Unassigned"


def test_topology_map_places_children_below_roots_and_uses_saved_status_colours():
    assert topology_map([]) is None

    laid_out = topology_map(
        [
            {
                "id": 1,
                "name": "Core router",
                "ip_address": "10.0.0.1",
                "device_type": "router",
                "parent_id": None,
                "status": "online",
            },
            {
                "id": 2,
                "name": "Access switch",
                "ip_address": "10.0.0.2",
                "device_type": "switch",
                "parent_id": 1,
                "status": "offline",
            },
            {
                "id": 3,
                "name": "Spare phone",
                "ip_address": "10.0.0.3",
                "device_type": "phone",
                "parent_id": None,
                "status": "unknown",
            },
        ]
    )
    by_id = {node["id"]: node for node in laid_out["nodes"]}

    assert by_id[2]["y"] > by_id[1]["y"]
    assert by_id[3]["y"] == by_id[1]["y"]
    assert laid_out["edges"][0]["y2"] == by_id[2]["y"]
    assert by_id[1]["color"] == "#73bf69"
    assert by_id[2]["color"] == "#f2495c"
    assert by_id[3]["color"] == "#5a5a5a"
    assert "<script" not in str(laid_out)


def test_status_bar_uses_the_worst_saved_status_and_skips_empty_days():
    today = date(2026, 11, 2)
    rows = [
        {
            "device_id": 1,
            "status": "online",
            "recorded_at": "2026-11-01T18:00:00+00:00",
        }
        for _ in range(17)
    ]
    rows.extend(
        (
            {
                "device_id": 1,
                "status": "online",
                "recorded_at": "2026-11-02T22:00:00+00:00",
            },
            {
                "device_id": 1,
                "status": "error",
                "recorded_at": "2026-11-02T23:00:00+00:00",
            },
            {
                "device_id": 1,
                "status": "offline",
                "recorded_at": "2026-11-03T00:12:00+00:00",
            },
            {
                "device_id": 1,
                "status": "offline",
                "recorded_at": "2026-11-03T01:00:00+00:00",
            },
            {
                "device_id": 2,
                "status": "online",
                "recorded_at": "2026-11-02T22:00:00+00:00",
            },
            {
                "device_id": 2,
                "status": "error",
                "recorded_at": "2026-11-02T23:00:00+00:00",
            },
        )
    )

    bars = status_history(rows, [1, 2, 5], 3, today)

    quiet, mixed, untouched = bars[1]["blocks"], bars[2]["blocks"], bars[5]
    assert quiet[0] == {
        "kind": "empty",
        "color": "#2a2d33",
        "title": "Oct 31, 2026 - No checks",
    }
    assert quiet[1]["color"] == "#73bf69"
    assert quiet[1]["title"] == "Nov 1, 2026 - Online (17 checks)"
    assert quiet[2]["color"] == "#f2495c"
    assert quiet[2]["title"] == "Nov 2, 2026 - Offline 2 times, first at 7:12 PM"
    assert bars[1]["uptime_label"] == "86%"
    assert mixed[2]["color"] == "#ff9830"
    assert mixed[2]["title"] == "Nov 2, 2026 - Error 1 time, first at 6:00 PM"
    assert bars[2]["uptime_label"] == "50%"
    assert len(untouched["blocks"]) == 3
    assert untouched["uptime_label"] == "No data"
    assert all(block["color"] == "#2a2d33" for block in untouched["blocks"])


def test_status_bar_splits_days_on_the_toronto_midnight():
    winter = status_history(
        [
            {
                "device_id": 1,
                "status": "online",
                "recorded_at": "2026-01-15T04:30:00+00:00",
            },
            {
                "device_id": 1,
                "status": "offline",
                "recorded_at": "2026-01-15T05:00:00+00:00",
            },
        ],
        [1],
        2,
        date(2026, 1, 15),
    )
    summer = status_history(
        [
            {
                "device_id": 1,
                "status": "online",
                "recorded_at": "2026-07-15T03:30:00+00:00",
            },
            {
                "device_id": 1,
                "status": "offline",
                "recorded_at": "2026-07-15T04:00:00+00:00",
            },
        ],
        [1],
        2,
        date(2026, 7, 15),
    )

    assert winter[1]["blocks"][0]["title"] == "Jan 14, 2026 - Online (1 check)"
    assert winter[1]["blocks"][1]["title"] == "Jan 15, 2026 - Offline 1 time, first at 12:00 AM"
    assert summer[1]["blocks"][0]["title"] == "Jul 14, 2026 - Online (1 check)"
    assert summer[1]["blocks"][1]["title"] == "Jul 15, 2026 - Offline 1 time, first at 12:00 AM"
    assert winter[1]["blocks"][0]["color"] == "#73bf69"
    assert winter[1]["blocks"][1]["color"] == "#f2495c"
