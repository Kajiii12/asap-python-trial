# ASAP Python Migration (FastAPI + Flet)

This is a Python-first migration starter for the ASAP Command Post project.

## Why this structure?

The current GitHub repository contains `server.ts`, `ip_camera_bridge.py`, and configuration files, but does not include the referenced React source folder (`src/`). The existing UI therefore cannot be reproduced pixel-for-pixel from the files currently available.

This migration uses:
- **FastAPI** for the Python API.
- **SQLite** for persistent incident and synchronization state (easy local setup; can be migrated to MySQL later).
- **Flet** for one Python client that can run as a web app and be packaged for Android.
- The existing `ip_camera_bridge.py` can continue to push frames to `/api/camera/push-frame`.

## Project layout

```text
backend/
  app/
    main.py             FastAPI application and API routes
frontend/
  main.py               Flet Security Officer / Field Responder client
requirements.txt
.env.example
```

## Windows setup

Use Python 3.11 or newer.

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

### 1. Start the API

From the project root:

```powershell
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

API documentation: http://127.0.0.1:8000/docs

### 2. Start the Flet client

Open a second terminal, activate the same environment, then run:

```powershell
python frontend/main.py
```

To serve the Flet client as a web app:

```powershell
flet run --web frontend/main.py
```

## Android testing

For a phone on the same Wi-Fi network:
1. Find the PC's LAN IPv4 address using `ipconfig`.
2. Set `ASAP_API_URL` to `http://YOUR_PC_LAN_IP:8000`.
3. Allow inbound TCP port 8000 through Windows Firewall for your private network.
4. Run the Flet app in web mode for a quick mobile-browser test.

For a packaged Android application, follow the current Flet Android build workflow:

```powershell
flet build apk frontend
```

Android packaging requires the Android build prerequisites documented by Flet. A phone must use the PC's LAN IP or a deployed HTTPS API URL, not `127.0.0.1`.

## Implemented API routes

- `GET /healthz` and `GET /api/health`
- `GET /api/sync/state`
- `POST /api/sync/state`
- `POST /api/camera/push-frame`
- `GET /api/camera/latest-frame`
- `POST /api/ai/analyze-emergency`
- `GET /api/tts`

The sync endpoint preserves the existing payload conventions for incidents, device overrides, zone states, activity logs, and PA broadcasts. Unlike the original in-memory TypeScript state, the Python version persists sync state in SQLite.

## Important limitations before production

- The image-analysis endpoint currently uses a **rule-based fallback based on the supplied category/name/visual hints**. It does not inspect image pixels. Connect and test a supported Gemini vision model before enabling automatic photo classification.
- The client role selector is only a prototype view switch. It is **not authentication or authorization**. Add account login, password hashing, role-based API permissions, audit controls, and secure token handling before deployment.
- The existing `firestore.rules` in the original repository permits unrestricted reads and writes. Do not expose that Firebase project publicly with those rules.
- CORS is permissive by default for local development. Set `CORS_ORIGINS` to explicit trusted origins before deployment.
- Camera frames are held in process memory and are not persisted. Run the bridge on a machine that can reach the IP camera.
- The existing `server.ts` includes more detailed Gemini prompt behavior and emergency contact guidance. Review and validate all emergency procedures with campus authorities before operational use.

## Migration notes

Keep the original TypeScript files during the migration as a reference until the Python version has passed feature-by-feature testing. Do not delete the original `server.ts`, `package.json`, Firebase configuration, or camera bridge prematurely.
