from __future__ import annotations

import os
import uuid
from datetime import datetime

import flet as ft
import requests

API_BASE = os.getenv("ASAP_API_URL", "http://127.0.0.1:8000").rstrip("/")
INCIDENT_TYPES = [
    "medical", "fire", "lockdown", "severe_weather_evacuation",
    "garbage", "missing_lost_found",
]


def api_get(path: str):
    response = requests.get(f"{API_BASE}{path}", timeout=5)
    response.raise_for_status()
    return response.json()


def api_post(path: str, payload: dict):
    response = requests.post(f"{API_BASE}{path}", json=payload, timeout=8)
    response.raise_for_status()
    return response.json()


def main(page: ft.Page):
    page.title = "ASAP Command Post"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 18
    page.scroll = ft.ScrollMode.AUTO
    page.window_min_width = 360
    page.window_min_height = 640

    role = ft.Dropdown(
        label="Application view",
        value="Security Officer",
        options=[
            ft.dropdown.Option("Security Officer"),
            ft.dropdown.Option("Field Responder"),
        ],
        width=260,
    )
    title = ft.Text("ASAP COMMAND POST", size=22, weight=ft.FontWeight.BOLD)
    subtitle = ft.Text("Campus safety, incident coordination and response")
    status = ft.Text("Connecting to API…", color=ft.Colors.AMBER)
    incident_list = ft.Column(spacing=10)
    title_field = ft.TextField(label="Incident title", expand=True)
    location_field = ft.TextField(label="Campus location", value="Main Gate", expand=True)
    type_field = ft.Dropdown(
        label="Incident category",
        value="medical",
        options=[ft.dropdown.Option(x) for x in INCIDENT_TYPES],
        expand=True,
    )
    severity_field = ft.Dropdown(
        label="Severity",
        value="high",
        options=[ft.dropdown.Option(x) for x in ("critical", "high", "medium", "low")],
        width=150,
    )
    description_field = ft.TextField(label="Description", multiline=True, min_lines=2, max_lines=4)
    responder_field = ft.TextField(label="Assigned responder (optional)")
    update_status = ft.Dropdown(
        label="Response status",
        value="Acknowledged",
        options=[ft.dropdown.Option(x) for x in (
            "Received", "Acknowledged", "En Route", "On Scene", "Resolved"
        )],
        expand=True,
    )
    message = ft.Text()

    def notify(text: str, color=ft.Colors.GREEN):
        message.value = text
        message.color = color
        page.update()

    def load_incidents():
        incident_list.controls.clear()
        try:
            data = api_get("/api/sync/state")
            incidents = data.get("incidents", [])
            status.value = f"API connected • {len(incidents)} incident(s) • Sync v{data.get('version', 1)}"
            status.color = ft.Colors.GREEN
            if not incidents:
                incident_list.controls.append(ft.Text("No incidents have been reported yet."))
            for incident in sorted(incidents, key=lambda x: x.get("timestampMs", 0), reverse=True):
                incident_id = str(incident.get("id", ""))
                incident_status = incident.get("status", "Reported")
                incident_list.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text(incident.get("title", "Untitled incident"), size=16, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                f"{incident.get('type', 'unknown')} • {incident.get('severity', 'unassigned')} • "
                                f"{incident.get('location', 'Unknown location')}"
                            ),
                            ft.Text(f"Status: {incident_status}"),
                            ft.Text(incident.get("description", "")),
                            ft.Text(f"ID: {incident_id}", size=10, color=ft.Colors.GREY),
                        ], spacing=4),
                        padding=12,
                        border=ft.border.all(1, ft.Colors.BLUE_GREY_700),
                        border_radius=10,
                    )
                )
        except Exception as exc:
            status.value = f"API unavailable: {exc}"
            status.color = ft.Colors.RED
            incident_list.controls.append(
                ft.Text("Start the FastAPI backend, then select Refresh.", color=ft.Colors.AMBER)
            )
        page.update()

    def create_incident(_):
        if not title_field.value or not location_field.value:
            notify("Enter an incident title and location.", ft.Colors.RED)
            return
        now = int(datetime.now().timestamp() * 1000)
        incident = {
            "id": str(uuid.uuid4()),
            "title": title_field.value.strip(),
            "type": type_field.value,
            "severity": severity_field.value,
            "status": "Reported",
            "timestampMs": now,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "location": location_field.value.strip(),
            "description": description_field.value or "",
            "reporter": role.value,
            "assignedResponder": responder_field.value or "",
        }
        try:
            api_post("/api/sync/state", {"incident": incident})
            title_field.value = ""
            description_field.value = ""
            responder_field.value = ""
            notify("Incident submitted.")
            load_incidents()
        except Exception as exc:
            notify(f"Could not submit incident: {exc}", ft.Colors.RED)

    def update_selected_status(_):
        try:
            data = api_get("/api/sync/state")
            incidents = data.get("incidents", [])
            if not incidents:
                notify("There are no incidents to update.", ft.Colors.AMBER)
                return
            incident = sorted(incidents, key=lambda x: x.get("timestampMs", 0), reverse=True)[0]
            incident["status"] = update_status.value
            incident["lastUpdatedBy"] = role.value
            incident["lastUpdatedAt"] = int(datetime.now().timestamp() * 1000)
            api_post("/api/sync/state", {"incident": incident})
            notify(f"Updated latest incident to: {update_status.value}")
            load_incidents()
        except Exception as exc:
            notify(f"Could not update status: {exc}", ft.Colors.RED)

    def change_role(_):
        is_admin = role.value == "Security Officer"
        title.value = "ASAP COMMAND POST" if is_admin else "ASAP FIELD RESPONDER"
        form.visible = is_admin
        responder_panel.visible = not is_admin
        page.update()

    form = ft.Container(
        content=ft.Column([
            ft.Text("Report / dispatch an incident", size=18, weight=ft.FontWeight.BOLD),
            ft.Row([title_field, location_field], wrap=True),
            ft.Row([type_field, severity_field], wrap=True),
            description_field,
            responder_field,
            ft.ElevatedButton("Submit incident", icon=ft.Icons.ADD_ALERT, on_click=create_incident),
        ], spacing=10),
        padding=14,
        border=ft.border.all(1, ft.Colors.BLUE_GREY_700),
        border_radius=12,
    )
    responder_panel = ft.Container(
        content=ft.Column([
            ft.Text("Responder actions", size=18, weight=ft.FontWeight.BOLD),
            ft.Text("Update the response status of the most recently updated incident."),
            update_status,
            ft.ElevatedButton("Update response status", icon=ft.Icons.TASK_ALT, on_click=update_selected_status),
        ], spacing=10),
        padding=14,
        border=ft.border.all(1, ft.Colors.BLUE_GREY_700),
        border_radius=12,
        visible=False,
    )

    page.add(
        ft.Row([title, role], alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
        subtitle,
        status,
        ft.Row([
            ft.ElevatedButton("Refresh incidents", icon=ft.Icons.REFRESH, on_click=lambda _: load_incidents()),
        ]),
        form,
        responder_panel,
        message,
        ft.Divider(),
        ft.Text("Live incident board", size=18, weight=ft.FontWeight.BOLD),
        incident_list,
        ft.Text(
            "Prototype notice: role selection is a view switch, not user authentication. "
            "Add secured accounts and permissions before real campus deployment.",
            size=11,
            color=ft.Colors.AMBER,
        ),
    )
    role.on_change = change_role
    load_incidents()


if __name__ == "__main__":
    ft.app(target=main)
