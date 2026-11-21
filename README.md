# ClipStudio

ClipStudio is an independent, local-first, AI-powered video clipping and creator workspace platform. It is designed to empower content creators, video editors, and live streamers to ingest long-form media, transcribe speech, detect highlights, generate viral-ready vertical and horizontal clips, edit captions, and manage publishing workflows seamlessly.

---

## Current Development Status

> **Status: Phase 1 Implemented — Project Scaffolding & Core Database Engine**  
> Backend FastAPI application factory, SQLite WAL database, Alembic migrations, durable persistent job queue, WebSocket real-time progress hub, and interactive React studio shell are fully implemented and verified.

---

## Windows Installation & Quick Start Guide

ClipStudio includes native batch scripts for automated setup, startup, and graceful shutdown on Windows.

### Prerequisites
- **OS**: Windows 10 or 11 (64-bit)
- **Python**: 3.10+ installed
- **Node.js**: 20+ LTS and npm installed
- **FFmpeg**: 7.0+ / 9.0+ in system PATH

---

### 1. First-Time Setup

Run the automated setup script from the root directory:

```cmd
D:\dharmendra\clipstudio\setup_clipstudio.bat
```

**What this script does:**
1. Validates Python and Node.js installation.
2. Creates the Python virtual environment at `clipstudio-backend\.venv`.
3. Installs backend dependencies (`fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `aiosqlite`).
4. Executes initial Alembic database migrations (`data\clipstudio.db`).
5. Installs frontend npm packages in `clipstudio-frontend\node_modules`.

---

### 2. Launching ClipStudio

Start all services with a single command:

```cmd
D:\dharmendra\clipstudio\start_clipstudio.bat
```

Once started, access the platform at:
- **Creator Studio Frontend**: [http://localhost:5173](http://localhost:5173)
- **Backend REST API**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive OpenAPI Documentation**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Real-Time WebSocket Stream**: `ws://127.0.0.1:8000/ws/events`

Service logs are continuously written to:
- Backend: `D:\dharmendra\clipstudio\logs\backend.log`
- Frontend: `D:\dharmendra\clipstudio\logs\frontend.log`

---

### 3. Stopping ClipStudio Safely

Stop backend and frontend processes without terminating unrelated system processes:

```cmd
D:\dharmendra\clipstudio\stop_clipstudio.bat
```

This terminates only the specific PIDs registered by ClipStudio, leaving the SQLite database and historical job records completely intact.

---

### 4. Manual Independent Startup (For Debugging)

#### Backend Startup
```powershell
cd D:\dharmendra\clipstudio\clipstudio-backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

#### Running Database Migrations Manually
```powershell
cd D:\dharmendra\clipstudio\clipstudio-backend
.\.venv\Scripts\alembic upgrade head
```

#### Frontend Startup
```powershell
cd D:\dharmendra\clipstudio\clipstudio-frontend
npm run dev
```

#### Running Backend Unit Tests
```powershell
cd D:\dharmendra\clipstudio\clipstudio-backend
.\.venv\Scripts\pytest -v
```

---

### 5. Troubleshooting Common Issues

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| **Port 8000 already in use** | A previous backend process did not terminate | Run `stop_clipstudio.bat` or inspect PID with `netstat -ano \| findstr :8000`. |
| **Port 5173 already in use** | An existing Vite server is running | Run `stop_clipstudio.bat` or check Vite logs in `logs\frontend.log`. |
| **Database locked error** | SQLite file accessed across threads | SQLite WAL mode and a 5000ms busy timeout are pre-configured. Ensure no external SQLite browser locks the DB file. |
| **WebSocket disconnected** | Backend stopped or starting up | Click the "Reconnect" button on the top right header badge. |
| **Restarting after system reboot** | OS restarted | Run `start_clipstudio.bat`. The backend startup reconciler will automatically recover any interrupted jobs. |

---

## Core Product Vision & Roadmap

ClipStudio delivers an end-to-end studio experience that bridges raw video/stream archives and short-form content.

### Planned Capabilities (Phased Roadmap)
- **Phase 1 (Complete)**: Scaffolding, SQLite WAL Database, Alembic Migrations, In-Process Durable Job Engine, WebSockets.
- **Phase 2 (Next)**: Media Ingestion & FFmpeg Pipeline (Metadata inspection, audio demuxing, stream-copy cuts).
- **Phase 3**: Speech Recognition Subsystem (Faster-Whisper int8, Silero VAD, word-level timestamps).
- **Phase 4**: Local AI Subsystem & Highlight Engine (Ollama integration, viral scoring, title generation).
- **Phase 5**: Smart 9:16 Video Framing & Caption Engine (Auto-framing, Advanced SubStation Alpha karaoke captions).
- **Phase 6**: Live Stream Monitoring & Buffer Engine (RTMP/HLS rolling buffer, instant 60s clipping).
- **Phase 7**: Creator Studio UI & Timeline Player.
- **Phase 8**: End-to-End Hardening & Release.

---

## PeakCut — Reference-Only Policy

ClipStudio references PeakCut strictly as a conceptual and usability design benchmark:
- **Zero Code Reuse**: ClipStudio does not use, copy, fork, or adapt PeakCut source code, components, backend logic, or database schemas.
- **Independent Implementation**: All frontend components, backend endpoints, processing engines, and data models are engineered independently from scratch.
- **No Shared Git History**: ClipStudio is initialized in a fresh, isolated repository with its own standalone commit lineage.
