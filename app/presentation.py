"""Labels for values that are already stored in the database.

These functions only format saved results. They do not decide whether a
device is online.
"""

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
    return {
        **device,
        "status": status,
        "status_label": STATUS_LABELS.get(status, "Unknown"),
        "response_label": response_label(status, device.get("response_time_ms")),
        "checked_label": checked_label(device.get("recorded_at")),
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
            }
        )
    return presented


def response_label(status, response_time_ms):
    """Describe a saved response time without filling in a missing check."""
    if status == "unknown":
        return "Not checked"
    if response_time_ms is None:
        return "Not measured"
    return f"{response_time_ms} ms"


def checked_label(recorded_at):
    """Show a stored UTC timestamp in a shorter form."""
    if not recorded_at:
        return "Not checked"
    text = recorded_at.replace("T", " ")
    if text.endswith("+00:00"):
        return text[:-6] + " UTC"
    return text
