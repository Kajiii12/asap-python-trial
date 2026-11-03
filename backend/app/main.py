from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("ASAP_DATA_DIR", APP_DIR.parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("ASAP_DB_PATH", DATA_DIR / "asap.sqlite3"))

app = FastAPI(title="ASAP Command Post API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_STATE: dict[str, Any] = {
    "version": 1,
    "updatedAt": int(time.time() * 1000),
    "incidents": {},
    "deviceOverrides": {},
    "zoneStates": {},
    "activityLogs": {},
    "paBroadcast": None,
}
camera_state: dict[str, Any] = {
    "frameBase64": None,
    "cameraUrl": os.getenv("CAMERA_URL", "http://192.168.120.220:8080/"),
    "updatedAt": 0,
    "framesReceived": 0,
}


def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def initialize_database() -> None:
    with db() as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS app_state "
            "(id INTEGER PRIMARY KEY CHECK(id = 1), payload TEXT NOT NULL)"
        )
        row = con.execute("SELECT id FROM app_state WHERE id=1").fetchone()
        if row is None:
            con.execute(
                "INSERT INTO app_state (id, payload) VALUES (1, ?)",
                (json.dumps(DEFAULT_STATE),),
            )


def read_state() -> dict[str, Any]:
    initialize_database()
    with db() as con:
        row = con.execute("SELECT payload FROM app_state WHERE id=1").fetchone()
    try:
        state = json.loads(row["payload"]) if row else DEFAULT_STATE.copy()
    except (TypeError, json.JSONDecodeError):
        state = DEFAULT_STATE.copy()
    for key, value in DEFAULT_STATE.items():
        state.setdefault(key, value.copy() if isinstance(value, dict) else value)
    return state


def write_state(state: dict[str, Any]) -> None:
    with db() as con:
        con.execute(
            "INSERT INTO app_state (id, payload) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (json.dumps(state, ensure_ascii=False),),
        )


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/healthz")
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "ASAP Command Post API", "timestamp": int(time.time() * 1000)}


@app.get("/api/sync/state")
def get_sync_state() -> dict[str, Any]:
    state = read_state()
    return {
        "ok": True,
        "serverTime": int(time.time() * 1000),
        "version": state["version"],
        "updatedAt": state["updatedAt"],
        "incidents": list(state["incidents"].values()),
        "deviceOverrides": list(state["deviceOverrides"].values()),
        "zoneStates": list(state["zoneStates"].values()),
        "activityLogs": list(state["activityLogs"].values()),
        "paBroadcast": state["paBroadcast"],
    }


@app.post("/api/sync/state")
async def update_sync_state(request: Request) -> dict[str, Any]:
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON object required")

    state = read_state()
    now = int(time.time() * 1000)
    changed = False

    if body.get("reset") is True:
        for key in ("incidents", "deviceOverrides", "zoneStates", "activityLogs"):
            state[key] = {}
        state["paBroadcast"] = None
        changed = True

    broadcast = body.get("paBroadcast")
    if isinstance(broadcast, dict) and broadcast.get("id"):
        state["paBroadcast"] = {**broadcast, "serverTimestampMs": now}
        changed = True

    for incident in body.get("seedIncidents", []) if isinstance(body.get("seedIncidents"), list) else []:
        if isinstance(incident, dict) and incident.get("id") and incident["id"] not in state["incidents"]:
            state["incidents"][str(incident["id"])] = incident
            changed = True

    incident = body.get("incident")
    if isinstance(incident, dict) and incident.get("id"):
        state["incidents"][str(incident["id"])] = incident
        changed = True

    override = body.get("deviceOverride")
    overrides = [override] if isinstance(override, dict) else []
    if isinstance(body.get("deviceOverrides"), list):
        overrides.extend(x for x in body["deviceOverrides"] if isinstance(x, dict))
    for item in overrides:
        if item.get("itemId"):
            item = {**item, "updatedAt": item.get("updatedAt") or now}
            state["deviceOverrides"][str(item["itemId"])] = item
            changed = True

    zone = body.get("zoneState")
    zones = [zone] if isinstance(zone, dict) else []
    if isinstance(body.get("zoneStates"), list):
        zones.extend(x for x in body["zoneStates"] if isinstance(x, dict))
    for item in zones:
        if item.get("zoneId"):
            item = {**item, "updatedAt": item.get("updatedAt") or now}
            state["zoneStates"][str(item["zoneId"])] = item
            changed = True

    log = body.get("activityLog")
    if isinstance(log, dict) and log.get("id"):
        state["activityLogs"][str(log["id"])] = log
        ordered = sorted(
            state["activityLogs"].values(),
            key=lambda x: x.get("timestampMs", 0),
            reverse=True,
        )[:60]
        state["activityLogs"] = {str(x["id"]): x for x in ordered if x.get("id")}
        changed = True

    if changed:
        state["version"] = int(state.get("version", 1)) + 1
        state["updatedAt"] = now
        write_state(state)

    return {"ok": True, "version": state["version"], "updatedAt": state["updatedAt"]}


class CameraFrame(BaseModel):
    frameBase64: str
    cameraUrl: str | None = None


@app.post("/api/camera/push-frame")
def push_camera_frame(payload: CameraFrame) -> dict[str, Any]:
    if not payload.frameBase64:
        raise HTTPException(status_code=400, detail="frameBase64 is required")
    camera_state["frameBase64"] = payload.frameBase64
    if payload.cameraUrl:
        camera_state["cameraUrl"] = payload.cameraUrl
    camera_state["updatedAt"] = int(time.time() * 1000)
    camera_state["framesReceived"] += 1
    return {
        "ok": True,
        "framesReceived": camera_state["framesReceived"],
        "updatedAt": camera_state["updatedAt"],
    }


@app.get("/api/camera/latest-frame")
def latest_camera_frame() -> dict[str, Any]:
    fresh = bool(
        camera_state["frameBase64"]
        and int(time.time() * 1000) - camera_state["updatedAt"] < 8000
    )
    return {
        "ok": True,
        "hasFrame": fresh,
        "frameBase64": camera_state["frameBase64"] if fresh else None,
        "cameraUrl": camera_state["cameraUrl"],
        "updatedAt": camera_state["updatedAt"],
        "framesReceived": camera_state["framesReceived"],
        "engine": "Python IP camera bridge",
    }


def classify_incident(hint: str) -> str:
    value = hint.lower()
    rules = {
        "missing_lost_found": ("missing", "lost", "found", "wallet", "backpack", "unattended bag", "id card", "keys"),
        "garbage": ("garbage", "trash", "waste", "litter", "rubbish", "sanitation", "overflowing bin"),
        "fire": ("fire", "flame", "smoke", "burn", "sparks"),
        "medical": ("medical", "injur", "faint", "unconscious", "bleed", "ambulance", "first aid", "seizure"),
        "severe_weather_evacuation": ("weather", "flood", "storm", "rain", "typhoon", "evac", "collapse", "earthquake", "chemical"),
        "lockdown": ("intruder", "weapon", "gun", "firearm", "knife", "lockdown", "breach", "armed"),
    }
    for category, words in rules.items():
        if any(word in value for word in words):
            return category
    return "medical"


CONTACTS = {
    "lockdown": [
        {"agency": "Campus Security Command Post & Chief Security Officer", "contactNumber": "Campus Ext. 100 / Radio Ch. 1"},
        {"agency": "Campus Guard House & All Gate Security Posts", "contactNumber": "Guard House Ext. 101"},
        {"agency": "School Administration", "contactNumber": "Admin Office Ext. 201"},
    ],
    "medical": [
        {"agency": "Campus Clinic & Duty Physician / School Nurse", "contactNumber": "Campus Ext. 104"},
        {"agency": "Campus Security Command Post", "contactNumber": "Campus Ext. 100"},
    ],
    "fire": [
        {"agency": "Campus Fire Safety Marshal & Facilities Engineering", "contactNumber": "Facilities Ext. 301"},
        {"agency": "Campus Security Command Post", "contactNumber": "Campus Ext. 100"},
    ],
    "severe_weather_evacuation": [
        {"agency": "Campus Disaster & Evacuation Committee", "contactNumber": "Campus Ext. 102"},
        {"agency": "Campus Facilities & Maintenance", "contactNumber": "Facilities Ext. 305"},
    ],
    "garbage": [
        {"agency": "Campus Janitorial & Sanitation Services", "contactNumber": "Facilities Ext. 305"},
    ],
    "missing_lost_found": [
        {"agency": "Campus Guard House & Gate Security Post", "contactNumber": "Guard House Ext. 101"},
        {"agency": "Student Affairs & Lost-and-Found Desk", "contactNumber": "Admin Office Ext. 204"},
    ],
}


@app.post("/api/ai/analyze-emergency")
async def analyze_emergency(request: Request) -> dict[str, Any]:
    body = await request.json()
    image_data = body.get("imageBase64")
    if not image_data:
        raise HTTPException(status_code=400, detail="Image base64 data is required for visual analysis")

    zone = str(body.get("locationHint") or "Main Gate")
    hints = " ".join(str(body.get(k) or "") for k in ("categoryHint", "fileNameHint", "visualHint"))
    category = classify_incident(hints)
    critical = category in ("fire", "lockdown")
    severity = "critical" if critical else ("medium" if category in ("garbage", "missing_lost_found") else "high")
    zones = ["Main Gate", "Gymnasium", "Academic Building", "Admin Building", "Canteen", "Gate 2", "Gate 3"]
    actions = {
        "missing_lost_found": [
            "Post a Missing / Lost & Found bulletin with the photo through the campus platform.",
            "Alert the Guard House and gate security personnel.",
            f"Log and secure the report details at {zone}.",
        ],
        "garbage": [
            f"Dispatch the campus sanitation team to {zone}.",
            "Coordinate waste collection with the appropriate campus or local office.",
            "Clean and sanitize the affected area.",
        ],
        "fire": [
            "Activate the campus fire emergency procedure and alert occupants.",
            "Contact the Bureau of Fire Protection and campus emergency personnel.",
            "Move occupants to designated safe assembly points.",
        ],
        "lockdown": [
            "Activate the campus security emergency procedure.",
            "Notify campus security leadership and appropriate police authorities.",
            "Keep people away from the affected area and follow official instructions.",
        ],
        "severe_weather_evacuation": [
            f"Assess the hazard and evacuate {zone} if it is unsafe.",
            "Coordinate with campus DRRM and local disaster response personnel.",
            "Cordon off flooded or structurally compromised areas.",
        ],
        "medical": [
            f"Dispatch campus first-aid responders to {zone}.",
            "Contact the campus clinic or emergency medical services.",
            "Keep access routes clear for responders.",
        ],
    }
    title = {
        "missing_lost_found": f"Missing / Lost & Found — {zone}",
        "garbage": f"Garbage & Sanitation Hazard — {zone}",
        "fire": f"Fire & Smoke Hazard — {zone}",
        "lockdown": f"Security Threat Alert — {zone}",
        "severe_weather_evacuation": f"Severe Weather & Evacuation Alert — {zone}",
        "medical": f"Medical Emergency — {zone}",
    }[category]
    return {
        "success": True,
        "source": "python-rule-based-fallback",
        "latencyMs": 0,
        "detectedType": category,
        "title": title,
        "severity": severity,
        "suggestedZones": zones if critical else [zone],
        "summary": f"Rule-based classification suggests a {category.replace('_', ' ')} incident at {zone}. Review the photo and verify the situation before dispatching responders.",
        "immediateActions": actions[category],
        "requiresLockdown": critical,
        "confidenceScore": 0.55,
        "detectedHazards": [category.replace("_", " ").title()],
        "requiredContacts": CONTACTS[category],
        "notice": "This fallback does not inspect image pixels. Configure a vision model before relying on automated photo analysis.",
    }


@app.get("/api/tts")
def text_to_speech(text: str = "", format: str = "") -> Response:
    if not text.strip():
        raise HTTPException(status_code=400, detail="Missing text parameter")
    try:
        from gtts import gTTS
        import io
        stream = io.BytesIO()
        gTTS(text=text[:1000], lang="en").write_to_fp(stream)
        audio = stream.getvalue()
        if format.lower() == "json":
            return {"ok": True, "audioBase64": base64.b64encode(audio).decode("ascii")}
        return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=3600"})
    except ImportError:
        raise HTTPException(status_code=501, detail="Install gTTS to enable speech synthesis")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TTS provider unavailable: {exc}")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "ASAP Command Post API is running", "docs": "/docs"}
