(function () {
  var panel = document.querySelector("[data-dashboard]");
  if (!panel) {
    return;
  }

  var refreshButton = document.getElementById("refresh-status");
  var live = document.getElementById("dashboard-status");
  var error = document.getElementById("dashboard-error");
  var empty = document.getElementById("dashboard-empty");
  var tableWrap = document.getElementById("device-table-wrap");
  var tableBody = document.querySelector("#device-table tbody");
  var groupsRoot = document.getElementById("device-groups");
  // The read-only demo marks its JSON with sample_data. Rows rebuilt from it
  // get a View link, matching the server-rendered rows, instead of actions.
  var sampleData = false;

  refreshButton.addEventListener("click", refreshStatus);

  function refreshStatus() {
    refreshButton.disabled = true;
    panel.setAttribute("aria-busy", "true");
    error.hidden = true;
    live.textContent = "Loading the latest monitoring results.";

    fetch(panel.getAttribute("data-refresh-url"), {
      headers: { Accept: "application/json" },
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("The dashboard request failed.");
        }
        return response.json();
      })
      .then(function (data) {
        renderDashboard(data);
        live.textContent = "Monitoring status updated from saved results.";
      })
      .catch(function () {
        error.hidden = false;
        error.textContent =
          "The latest monitoring results could not be loaded. The table still shows the last page loaded from the database.";
        live.textContent = "Monitoring status could not be refreshed.";
      })
      .finally(function () {
        refreshButton.disabled = false;
        panel.setAttribute("aria-busy", "false");
      });
  }

  function renderDashboard(data) {
    sampleData = data.sample_data === true;
    ["total", "online", "offline", "unknown", "error"].forEach(function (key) {
      var value = document.querySelector('[data-count="' + key + '"]');
      value.textContent = String(data.summary[key]);
    });
    renderIncidents(data.incidents || []);

    var grouped = Array.isArray(data.groups);
    if (grouped) {
      tableWrap.hidden = true;
      tableBody.replaceChildren();
      if (!data.devices.length) {
        empty.hidden = false;
        groupsRoot.hidden = true;
        groupsRoot.replaceChildren();
        return;
      }
      empty.hidden = true;
      groupsRoot.hidden = false;
      renderGroups(data.groups);
      return;
    }

    groupsRoot.hidden = true;
    groupsRoot.replaceChildren();
    tableBody.replaceChildren();
    if (!data.devices.length) {
      empty.hidden = false;
      tableWrap.hidden = true;
      return;
    }

    empty.hidden = true;
    tableWrap.hidden = false;
    data.devices.forEach(function (device) {
      tableBody.appendChild(deviceRow(device));
    });
  }

  function renderIncidents(incidents) {
    var list = document.getElementById("incident-list");
    var none = document.getElementById("incident-empty");
    if (!list || !none) {
      return;
    }
    list.replaceChildren();
    if (!incidents.length) {
      none.hidden = false;
      list.hidden = true;
      return;
    }
    none.hidden = true;
    list.hidden = false;
    incidents.forEach(function (incident) {
      var item = document.createElement("li");
      item.className = "incident incident-" + incident.new_status;
      item.appendChild(incidentLine("incident-device", incident.device_name));
      item.appendChild(incidentLine("mono", incident.change_label));
      item.appendChild(incidentLine("", incident.checked_label));
      item.appendChild(incidentLine("incident-duration", incident.duration_label));
      if (incident.cause_label) {
        item.appendChild(incidentLine("incident-cause", incident.cause_label));
      }
      list.appendChild(item);
    });
  }

  function incidentLine(className, text) {
    var line = document.createElement("p");
    if (className) {
      line.className = className;
    }
    line.textContent = text;
    return line;
  }

  function renderGroups(groups) {
    groupsRoot.replaceChildren();
    var sourceHead = document.querySelector("#device-table thead");
    groups.forEach(function (group) {
      var details = document.createElement("details");
      details.className = "device-group";
      details.open = true;
      var summary = document.createElement("summary");
      summary.textContent = group.summary;
      details.appendChild(summary);
      var wrap = document.createElement("div");
      wrap.className = "table-wrap";
      var table = document.createElement("table");
      var caption = document.createElement("caption");
      caption.textContent = group.summary;
      table.appendChild(caption);
      if (sourceHead) {
        table.appendChild(sourceHead.cloneNode(true));
      }
      var body = document.createElement("tbody");
      group.devices.forEach(function (device) {
        body.appendChild(deviceRow(device));
      });
      table.appendChild(body);
      wrap.appendChild(table);
      details.appendChild(wrap);
      groupsRoot.appendChild(details);
    });
  }

  function deviceRow(device) {
    var row = document.createElement("tr");
    row.appendChild(nameCell(device));
    row.appendChild(textCell("IP address", device.ip_address));
    row.appendChild(textCell("Device type", device.device_type));
    row.appendChild(textCell("Location", device.location_label));
    row.appendChild(textCell("VLAN", device.vlan_label));
    row.appendChild(statusCell(device));
    row.appendChild(textCell("Response time", device.response_label));
    row.appendChild(textCell("Uptime", device.uptime_label));
    row.appendChild(textCell("Average response", device.average_response_label));
    row.appendChild(textCell("Last checked", device.checked_label));
    row.appendChild(actionCell(device));
    return row;
  }

  function nameCell(device) {
    var cell = document.createElement("td");
    cell.setAttribute("data-label", "Device name");
    var link = document.createElement("a");
    link.href = "/devices/" + device.id;
    link.textContent = device.name;
    var description = document.createElement("span");
    description.className = "secondary";
    description.textContent = device.description || "No description";
    cell.appendChild(link);
    cell.appendChild(description);
    cell.appendChild(historyBar(device));
    return cell;
  }

  function historyBar(device) {
    var bar = document.createElement("div");
    bar.className = "history-bar history-bar-compact";
    var blocks = device.history_bar && device.history_bar.blocks ? device.history_bar.blocks : [];
    blocks.forEach(function (block) {
      var mark = document.createElement("span");
      mark.className = "history-block history-" + (block.kind || "empty");
      mark.title = block.title;
      bar.appendChild(mark);
    });
    return bar;
  }

  function textCell(label, value) {
    var cell = document.createElement("td");
    cell.setAttribute("data-label", label);
    cell.appendChild(hiddenLabel(label));
    if (label === "IP address" || label === "Response time" || label === "Average response") {
      var mono = document.createElement("span");
      mono.className = "mono";
      mono.textContent = value;
      cell.appendChild(mono);
    } else {
      cell.appendChild(document.createTextNode(value));
    }
    return cell;
  }

  function statusCell(device) {
    var cell = document.createElement("td");
    cell.setAttribute("data-label", "Status");
    cell.appendChild(hiddenLabel("Status"));
    var badge = document.createElement("span");
    badge.className = "status status-" + (device.status_class || device.status);
    badge.textContent = device.status_label;
    cell.appendChild(badge);
    return cell;
  }

  function hiddenLabel(label) {
    var hidden = document.createElement("span");
    hidden.className = "visually-hidden";
    hidden.textContent = label + ": ";
    return hidden;
  }

  function actionCell(device) {
    var cell = document.createElement("td");
    cell.setAttribute("data-label", "Actions");
    var actions = document.createElement("div");
    actions.className = "row-actions";
    if (sampleData) {
      var view = document.createElement("a");
      view.href = "/devices/" + device.id;
      view.textContent = "View";
      actions.appendChild(view);
      cell.appendChild(actions);
      return cell;
    }
    actions.appendChild(checkForm(device));
    var edit = document.createElement("a");
    edit.href = "/devices/" + device.id + "/edit";
    edit.textContent = "Edit";
    actions.appendChild(edit);
    var link = document.createElement("a");
    link.href = "/devices/" + device.id + "/delete";
    link.textContent = "Delete";
    actions.appendChild(link);
    cell.appendChild(actions);
    return cell;
  }

  function checkForm(device) {
    var form = document.createElement("form");
    form.className = "inline-form";
    form.method = "post";
    form.action = "/devices/" + device.id + "/check";
    form.appendChild(hiddenInput("csrf_token", panel.getAttribute("data-csrf-token")));
    form.appendChild(hiddenInput("next", "dashboard"));
    var button = document.createElement("button");
    button.type = "submit";
    button.setAttribute("data-loading-label", "Checking");
    button.textContent = "Check now";
    form.appendChild(button);
    return form;
  }

  function hiddenInput(name, value) {
    var input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    return input;
  }
})();
