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
    ["total", "online", "offline", "unknown", "error"].forEach(function (key) {
      var value = document.querySelector('[data-count="' + key + '"]');
      value.textContent = String(data.summary[key]);
    });

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

  function deviceRow(device) {
    var row = document.createElement("tr");
    row.appendChild(nameCell(device));
    row.appendChild(textCell("IP address", device.ip_address));
    row.appendChild(textCell("Device type", device.device_type));
    row.appendChild(statusCell(device));
    row.appendChild(textCell("Response time", device.response_label));
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
    return cell;
  }

  function textCell(label, value) {
    var cell = document.createElement("td");
    cell.setAttribute("data-label", label);
    cell.appendChild(hiddenLabel(label));
    cell.appendChild(document.createTextNode(value));
    return cell;
  }

  function statusCell(device) {
    var cell = document.createElement("td");
    cell.setAttribute("data-label", "Status");
    cell.appendChild(hiddenLabel("Status"));
    var badge = document.createElement("span");
    badge.className = "status status-" + device.status;
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
    actions.appendChild(checkForm(device));
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
