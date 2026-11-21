# CLIPSTUDIO — INDEPENDENT SOFTWARE ARCHITECTURE BLUEPRINT

> **Document Version:** 1.0.0  
> **Target Platform:** ClipStudio  
> **Working Directory:** `D:\dharmendra\clipstudio`  
> **Repository:** `https://github.com/dharmendramawlemawle/ClipStudio.git`  
> **Status:** Architectural Blueprint & Specification (No implementation yet)

---

## 1. Executive Summary & Product Vision

ClipStudio is an **independent, local-first, AI-augmented video clipping and creator workspace platform**. It empowers content creators, live streamers, and video editors to:
1. Ingest long-form media (recorded podcasts, VODs, gaming sessions) and monitor real-time live streams (RTMP, HLS, YouTube, Twitch).
2. Transcribe multi-speaker audio with word-level timestamps using high-efficiency local speech models.
3. Automatically detect narrative hooks, virality spikes, and emotional highlights using local or optional cloud LLMs.
4. Intelligently crop and re-frame horizontal (16:9) video into vertical (9:16) short-form content (TikTok, Reels, YouTube Shorts).
5. Edit dynamic, word-animated captions and preview cuts in real time without waiting for full re-encodes.
6. Export publication-ready, hardware-optimized video files with synchronized burned-in or soft subtitles.

### Core Architectural Tenets
- **Local-First Privacy & Zero-Cloud-Cost**: Full pipeline (ingest, speech recognition, highlight scoring, rendering) functions entirely offline on consumer hardware with zero data transmission to external servers by default.
- **Hardware-Aware Adaptive Scheduling**: Tailored to run efficiently on 4-core/8-thread laptop CPUs (Intel Core i5-1135G7) with 16 GB RAM and integrated graphics (Intel Iris Xe), preventing system lockups through concurrency throttling and low-bitwidth quantization.
- **Modular Micro-Services inside a Monorepo**: Decoupled domain engines (Ingestion, Transcription, Highlight, Framing, Rendering, LiveStream, AI Provider) coordinated via an async FastAPI core and a responsive React creator studio.
- **Strict PeakCut Independence**: PeakCut serves solely as an external visual/functional UX benchmark. Zero code, components, schemas, or history are derived from PeakCut.

---

## 2. Target Hardware Constraints & Resource Budget

The reference development and execution target is an Intel Core i5 mobile workstation:

| Hardware Component | Detected Specification | Operational Resource Allocation |
| :--- | :--- | :--- |
| **CPU** | Intel Core i5-1135G7 @ 2.40GHz (4 Cores / 8 Threads, AVX-512 supported) | Maximum 4 concurrent worker threads for CPU compute (leaving 4 threads for OS/UI responsiveness) |
| **RAM** | 16.0 GB Total (~6.6 GB currently free) | Hard memory ceiling: **3.5 GB** for Local LLM, **1.2 GB** for Whisper, **1.5 GB** for FFmpeg processing buffer |
| **GPU** | Intel Iris Xe Graphics (Integrated, shared VRAM) | OpenCL/VAAPI/QSV hardware acceleration for FFmpeg decode/encode (`h264_qsv` where available); CPU for AI inference |
| **Storage / Disk** | Fast NVMe / SSD | SQLite Write-Ahead Logging (WAL); rolling disk ring-buffer for live streams (capped at 5–10 GB) |
| **Runtime Dependencies** | Python 3.10.10, Node.js 26.13.1, FFmpeg 9.0.2-full, Ollama 0.40.16 | Zero external cloud service prerequisites |

### AI Model Recommendations for 16GB Non-CUDA Hardware
- **Local LLM**: `Llama-3.2-3B-Instruct-Q4_K_M` (Ollama, ~2.0 GB RAM footprint) or `Qwen2.5-1.5B-Instruct-Q4_K_M` (~1.2 GB RAM). These deliver fast token generation on CPU AVX2/AVX-512 without starving system RAM.
- **Speech-to-Text**: `faster-whisper-small` or `faster-whisper-base` with `compute_type="int8"` on CPU (~500 MB – 1.0 GB RAM).
- **Prohibited by Default**: 70B models, unquantized fp16/fp32 models, or models exceeding 4.5 GB memory footprint without explicit user override.

---

## 3. High-Level System Architecture

```mermaid
flowchart TD
    subgraph Client["Frontend Creator Studio (React + Vite + TypeScript)"]
        UI_Dash["Creator Workspace & Projects"]
        UI_Stream["Live Stream Monitor & Ring Preview"]
        UI_Player["Timeline Video Player & Scrubbing"]
        UI_SubEditor["Dynamic Caption & Style Editor"]
        UI_Settings["AI Provider & Model Router"]
        Zustand_Store["Client State (Zustand)"]
        Query_Cache["Data & Job Cache (TanStack Query v5)"]
    end

    subgraph Gateway["API & Real-time Layer (FastAPI)"]
        REST_Router["REST API Endpoints (/api/v1)"]
        WS_Manager["WebSocket Event Hub (/ws/events)"]
        Job_Orchestrator["Async Job Scheduler & Lifecycle Engine"]
    end

    subgraph CoreServices["Domain Engine Services"]
        Ingest_Svc["Ingestion Service (FFprobe, Metadata)"]
        Live_Svc["Live Stream Engine (HLS/RTMP Ring Buffer)"]
        Whisper_Svc["Transcription Subsystem (Faster-Whisper int8)"]
        AI_Svc["AI Highlight & Intelligence Router"]
        Framing_Svc["Smart 9:16 Video Framing Engine"]
        Render_Svc["Rendering & Export Pipeline (FFmpeg 9.0)"]
    end

    subgraph DataStorage["Persistence & Keyring"]
        SQLite_DB[("SQLite 3 (WAL Mode)")]
        Secure_Keyring["OS Credential Store (Windows Credential Manager / DPAPI)"]
        Disk_Media["Local Workspace File Storage (Videos, Audio, Ass, Clips)"]
    end

    subgraph AIProviders["Pluggable AI Inference Backends"]
        Local_Ollama["Ollama Daemon (localhost:11434)"]
        Local_LlamaCpp["llama.cpp / LM Studio Server"]
        Cloud_APIs["Optional Cloud (OpenAI, Gemini, Groq, OpenRouter)"]
    end

    UI_Dash -->|REST API| REST_Router
    UI_Player -->|WebSockets| WS_Manager
    REST_Router --> Job_Orchestrator
    WS_Manager <--> Job_Orchestrator

    Job_Orchestrator --> Ingest_Svc
    Job_Orchestrator --> Live_Svc
    Job_Orchestrator --> Whisper_Svc
    Job_Orchestrator --> AI_Svc
    Job_Orchestrator --> Framing_Svc
    Job_Orchestrator --> Render_Svc

    AI_Svc --> Local_Ollama
    AI_Svc --> Local_LlamaCpp
    AI_Svc -.->|Explicit Permission Only| Cloud_APIs

    Ingest_Svc --> Disk_Media
    Whisper_Svc --> SQLite_DB
    AI_Svc --> SQLite_DB
    Live_Svc --> Disk_Media
    Render_Svc --> Disk_Media

    Job_Orchestrator <--> SQLite_DB
    AI_Svc <--> Secure_Keyring
```

---

## 4. Frontend Architecture

### 4.1 Technology Stack Selection & Rationale
- **Framework**: React 19 + TypeScript 5.8 + Vite 6.
  - *Rationale*: Blazing fast HMR, small bundle size, strict type safety for media timestamps and framing coordinates.
- **Styling & Design System**: Tailwind CSS v4 + Radix UI Primitives + Lucide Icons.
  - *Rationale*: Accessible, headless primitives (dialogs, dropdowns, sliders, tabs) styled with high-density dark-mode creator aesthetics.
- **State Management**:
  - **Server State**: `@tanstack/react-query` (v5) for caching, optimistic updates, and background polling.
  - **Client & Playback State**: `zustand` for lightweight, decoupled player state, active timecodes, framing box coordinates, and caption styling.
- **Routing**: `react-router-dom` (v7) for nested project workspaces, settings, and full-screen preview modes.
- **Video Playback & Timeline**: Custom HTML5 `<video>` player synchronized with HTML5 Canvas / WebGL overlay for zero-latency framing previews and subtitle rendering.

### 4.2 Proposed Frontend Directory Structure
```
clipstudio-frontend/
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── assets/                 # SVGs, brand marks, placeholder media
│   ├── components/
│   │   ├── ui/                 # Reusable Radix/shadcn primitives
│   │   │   ├── button.tsx
│   │   │   ├── dialog.tsx
│   │   │   ├── slider.tsx
│   │   │   ├── dropdown-menu.tsx
│   │   │   ├── tooltip.tsx
│   │   │   ├── progress.tsx
│   │   │   └── badge.tsx
│   │   ├── common/             # Shared app components
│   │   │   ├── Header.tsx
│   │   │   ├── Sidebar.tsx
│   │   │   ├── StatusBadge.tsx
│   │   │   └── ConfirmModal.tsx
│   │   ├── workspace/          # Dashboard & project listings
│   │   │   ├── WorkspaceCard.tsx
│   │   │   ├── VideoImportModal.tsx
│   │   │   └── LiveStreamConnectModal.tsx
│   │   ├── player/             # Video playback & timeline
│   │   │   ├── VideoPlayer.tsx
│   │   │   ├── PlaybackControls.tsx
│   │   │   ├── TimelineTrack.tsx
│   │   │   ├── WaveformView.tsx
│   │   │   ├── FramingOverlay.tsx
│   │   │   └── TimecodeDisplay.tsx
│   │   ├── captions/           # Subtitle editor & karaoke preview
│   │   │   ├── CaptionList.tsx
│   │   │   ├── CaptionSegmentItem.tsx
│   │   │   ├── WordTimingEditor.tsx
│   │   │   └── StylePicker.tsx
│   │   ├── clips/              # Highlight & clip cards
│   │   │   ├── ClipGrid.tsx
│   │   │   ├── ClipCard.tsx
│   │   │   ├── HighlightScoreBadge.tsx
│   │   │   └── ExportModal.tsx
│   │   └── livestream/         # Real-time monitoring
│   │       ├── StreamStatusHeader.tsx
│   │       ├── RollingBufferTimeline.tsx
│   │       └── InstantClipButton.tsx
│   ├── hooks/                  # Custom React hooks
│   │   ├── useVideoPlayer.ts
│   │   ├── useWebSocket.ts
│   │   ├── useJobProgress.ts
│   │   └── useKeyboardShortcuts.ts
│   ├── stores/                 # Zustand state stores
│   │   ├── usePlayerStore.ts
│   │   ├── useEditorStore.ts
│   │   ├── useLiveStreamStore.ts
│   │   └── useSettingsStore.ts
│   ├── services/               # API clients
│   │   ├── api.ts              # Axios / Fetch client with interceptors
│   │   ├── videosApi.ts
│   │   ├── clipsApi.ts
│   │   ├── liveApi.ts
│   │   └── aiProvidersApi.ts
│   ├── types/                  # TypeScript interface definitions
│   │   ├── video.ts
│   │   ├── clip.ts
│   │   ├── transcript.ts
│   │   ├── job.ts
│   │   └── ai.ts
│   └── utils/                  # Formatting & calculation utilities
│       ├── timecode.ts         # Seconds to HH:MM:SS.mmm conversions
│       ├── formatters.ts       # Byte sizing, percentages
│       └── assGenerator.ts     # Client-side subtitle export preview
```

---

## 5. Backend Architecture

### 5.1 Technology Stack Selection & Rationale
- **Framework**: Python 3.10 + FastAPI (ASGI).
  - *Rationale*: Native `asyncio`, high-throughput request handling, auto-generated OpenAPI documentation, and strict Pydantic v2 data validation.
- **ORM & Database**: SQLAlchemy 2.0 (asyncio) + Alembic + SQLite (WAL mode).
  - *Rationale*: Zero-config local persistence with zero operational overhead; SQLite with Write-Ahead Logging allows simultaneous reads and writes across background tasks and the web UI. Schema designed with PostgreSQL compatibility in mind.
- **Background Job Execution**: In-process durable async worker queue with persistent database state.
  - *Rationale*: Avoids demanding heavy external message brokers (RabbitMQ/Redis/Celery) on local desktop workstations. Jobs are tracked in a `processing_jobs` table, survive app restarts, and emit granular progress over WebSockets.
- **Real-Time Communication**: FastAPI WebSockets with broadcast channels for job progress, real-time transcription chunks, and stream health status.

### 5.2 Proposed Backend Directory Structure
```
clipstudio-backend/
├── pyproject.toml
├── alembic.ini
├── app/
│   ├── main.py                 # FastAPI application factory & startup hooks
│   ├── config.py               # App configuration & environment parsing
│   ├── database.py             # SQLite async engine & sessionmaker
│   ├── dependencies.py         # FastAPI dependency injection providers
│   ├── api/
│   │   ├── v1/
│   │   │   ├── router.py       # Main API v1 router
│   │   │   ├── videos.py       # Video upload, inspect, list, delete
│   │   │   ├── streams.py      # Live stream connect, buffer, disconnect
│   │   │   ├── transcripts.py  # Transcript retrieval & editing
│   │   │   ├── clips.py        # Clip generation, manual crop, delete
│   │   │   ├── exports.py      # Final rendering trigger & downloads
│   │   │   ├── ai_providers.py # Provider config, health, model discovery
│   │   │   └── jobs.py         # Background job status & control
│   │   └── websockets/
│   │       ├── connection.py   # ConnectionManager for active clients
│   │       └── events.py       # Event schemas & pub/sub router
│   ├── core/
│   │   ├── exceptions.py       # Custom domain exceptions
│   │   ├── security.py         # DPAPI / Windows keyring helpers
│   │   └── logging.py          # Structured rotation logger
│   ├── models/                 # SQLAlchemy 2.0 declarative models
│   │   ├── base.py
│   │   ├── workspace.py
│   │   ├── video.py
│   │   ├── stream.py
│   │   ├── transcript.py
│   │   ├── clip.py
│   │   ├── job.py
│   │   └── ai_provider.py
│   ├── schemas/                # Pydantic v2 validation models
│   │   ├── video.py
│   │   ├── stream.py
│   │   ├── transcript.py
│   │   ├── clip.py
│   │   ├── job.py
│   │   └── ai.py
│   ├── services/               # Core business & processing services
│   │   ├── ingestion_service.py
│   │   ├── live_stream_service.py
│   │   ├── transcription_service.py
│   │   ├── highlight_service.py
│   │   ├── framing_service.py
│   │   ├── rendering_service.py
│   │   ├── ai_provider_service.py
│   │   └── job_queue_service.py
│   └── utils/
│       ├── ffmpeg_runner.py    # Subprocess execution & progress parser
│       ├── srt_parser.py       # Subtitle format converters (SRT, VTT, ASS)
│       └── file_system.py      # Safe directory & path sanitization
├── migrations/                 # Alembic migration scripts
│   ├── env.py
│   └── versions/
└── tests/
    ├── conftest.py
    ├── test_api/
    ├── test_services/
    └── test_ffmpeg/
```

---

## 6. AI Subsystem & Provider Abstraction

### 6.1 Provider Architecture & Guardrails
ClipStudio implements a unified **`AIProvider` abstract interface**. AI capabilities are decoupled into discrete task routers:
1. **Highlight Candidate Detection**: Evaluates transcript segments for narrative tension, laughter, emotional hooks, or advice.
2. **Title & Summary Generation**: Generates viral hooks, short video titles, and description tags.
3. **Smart Framing Assistance**: Analyzes scene composition or transcript context to predict subject regions.

```mermaid
flowchart TD
    Task_Request["AI Task Request (e.g. Detect Highlights)"] --> Task_Router["AI Provider Router"]
    
    Task_Router --> Model_Assignment{"Task Model Assignment"}
    
    Model_Assignment -->|Local Default| Local_Adapter["Local Provider (Ollama / llama.cpp)"]
    Model_Assignment -->|User Explicit Choice| Cloud_Adapter["Cloud Provider (OpenAI / Gemini / Groq)"]
    
    Local_Adapter --> Health_Check_L{"Ollama Daemon Running?"}
    Health_Check_L -->|Yes| Exec_Local["Local CPU Inference (int4/int8)"]
    Health_Check_L -->|No| Fallback_Err["Report Provider Inactive (Zero silent switch)"]

    Cloud_Adapter --> Consent_Check{"Explicit User Permission Granted?"}
    Consent_Check -->|Yes| Secure_Key["Retrieve Key from OS Keyring"]
    Consent_Check -->|No| Refuse_Cloud["Refuse Transmission (Local Privacy Intact)"]
    Secure_Key --> Exec_Cloud["API Request with Timeout & Token Cap"]
```

### 6.2 Strict Safety & Privacy Guardrails
1. **Never Silently Switch**: If Ollama or a local model fails or runs out of memory, the system **NEVER** falls back to an external paid cloud service without the user manually confirming the change.
2. **Explicit Consent for External Data**: Transcripts, audio files, or video frames are never transmitted outside the local machine unless the user explicitly assigns an external provider for that workspace or task.
3. **No Automatic Large Downloads**: Model pulls (e.g. `ollama pull`) must display model size, require explicit user initiation, and verify available RAM and disk space prior to download.
4. **Structured Output Enforcement**: All highlight proposals are returned via constrained JSON schemas (using Pydantic / Ollama format parameters) to prevent parsing errors.

---

## 7. Speech Recognition Subsystem (Faster-Whisper)

Speech recognition is strictly decoupled from LLM understanding.

```mermaid
sequenceDiagram
    participant Job as Job Manager
    participant Ingest as FFmpeg Engine
    participant Whisper as Faster-Whisper Subsystem
    participant DB as SQLite DB
    participant WS as WebSocket Hub

    Job->>Ingest: Extract 16kHz mono audio (PCM 16-bit WAV)
    Ingest-->>Job: Audio file ready (/temp/audio_16k.wav)
    
    Job->>Whisper: Launch chunked transcription (compute_type='int8')
    Note over Whisper: Silero VAD filters non-speech & silence
    
    loop For each 5-minute segment
        Whisper->>Whisper: Process segment & extract word timestamps
        Whisper->>DB: Save TranscriptSegment & WordTimestamp records
        Whisper->>WS: Broadcast progress (% & current timecode)
    end
    
    Whisper-->>Job: Transcription completed
    Job->>DB: Update video status to 'transcribed'
```

### Key Technical Specifications
- **Engine**: `faster-whisper` (CTranslate2 backend).
- **Quantization**: `int8` (CPU execution via AVX2/AVX-512 on i5-1135G7).
- **VAD Pre-filtering**: Built-in Silero VAD prevents hallucination loops during extended silence.
- **Word Timestamps**: `word_timestamps=True` produces exact millisecond boundaries for every word.
- **Recoverable Checkpoints**: Progress is committed per audio segment into SQLite so interrupted jobs can resume without re-transcribing from zero.

---

## 8. Video Processing & FFmpeg Pipeline

Video processing distinguishes between **fast preview stream-copying** and **high-quality re-encoding**.

```mermaid
flowchart TD
    Raw_Video["Raw Source Video (MP4 / MKV / MOV)"] --> Step1["FFprobe Metadata Inspection (Codecs, Bitrate, FPS, SAR)"]
    
    Step1 --> Step2["Audio Extraction (FFmpeg: 16kHz Mono WAV, -vn)"]
    Step2 --> Step3["Speech Recognition (Faster-Whisper int8)"]
    Step3 --> Step4["Highlight Discovery (Local LLM / Heuristic Scoring)"]
    
    Step4 --> Step5{"Action Required"}
    
    Step5 -->|Quick Review Preview| Fast_Cut["Fast Stream-Copy Cut (-c copy -avoid_negative_ts make_zero)"]
    Fast_Cut --> Instant_Preview["Zero-Wait Client Playback"]

    Step5 -->|Final Clip Export| Smart_Render["Smart Re-encoding Pipeline"]
    
    Smart_Render --> Crop_Calc["Calculate 9:16 Crop Coordinates (Face / Center / Manual)"]
    Crop_Calc --> Sub_Gen["Generate Styled Subtitles (.ass / .srt)"]
    Sub_Gen --> FFmpeg_Filter["FFmpeg Filter Graph: crop + subtitles filter"]
    FFmpeg_Filter --> Encoder_Choice{"Intel QSV Available?"}
    
    Encoder_Choice -->|Yes| QSV_Encode["Hardware Encode: -c:v h264_qsv -global_quality 22"]
    Encoder_Choice -->|No| CPU_Encode["CPU Encode: -c:v libx264 -preset veryfast -crf 20"]
    
    QSV_Encode --> Final_Clip["Final 9:16 Viral Clip (.mp4)"]
    CPU_Encode --> Final_Clip
```

### Video Framing & Subtitle Sync Rules
1. **PTS / DTS Synchronization**: All cut operations use `-avoid_negative_ts make_zero` and re-timestamp streams to prevent audio drift.
2. **Karaoke Subtitle Generation**: Advanced SubStation Alpha (`.ass`) tracks are generated dynamically from word timestamps. Word highlights (color fill, scale bounce) are rendered at exact millisecond offsets.
3. **Preview vs. Export**: During interactive editing, the client player crops and displays subtitles in the DOM/Canvas without invoking FFmpeg. FFmpeg re-encoding is only triggered upon final "Export".

---

## 9. Live Streaming Architecture

The live stream subsystem provides real-time monitoring and rolling capture of continuous broadcasts.

```mermaid
flowchart LR
    Stream_Source["Live Ingest (RTMP / HLS / YouTube)"] --> Stream_Worker["Stream Capture Worker (FFmpeg / Streamlink)"]
    
    Stream_Worker --> Ring_Buffer["Rolling Disk Ring-Buffer (5s TS segments, max 60 min)"]
    
    Ring_Buffer --> Live_Preview["Local HLS Proxy -> Frontend Video Element"]
    
    Ring_Buffer --> Micro_Batch["Micro-Batch Transcription (Every 3 closed segments)"]
    Micro_Batch --> Live_Transcript["Live Scrolling Transcript"]
    
    Live_Transcript --> Auto_Highlight["Sliding-Window Highlight Detector"]
    
    Ring_Buffer --> Instant_Clip["One-Click 'Clip Last 60s' Button"]
    Instant_Clip --> Fast_Concat["Concatenate Buffer Segments (Stream-Copy)"]
    Fast_Concat --> New_Clip["Saved Workspace Clip"]
```

### Resilience & Buffer Mechanics
- **Ring Buffer Size**: Retains a sliding window of the last 30–60 minutes in 5-second transport stream (`.ts`) segments. Older segments are automatically pruned, keeping disk usage strictly bounded under 5 GB.
- **Connection Recovery**: Automatic exponential backoff (1s, 2s, 5s, 10s up to 30s) on stream dropouts with seamless buffer continuation.
- **Instant Clipping**: Users can hit "Clip Last 30s/60s/2m" to immediately concatenate buffered segments into a permanent clip with zero transcoding delay.

---

## 10. Database Schema & Entity Relationships

```mermaid
erDiagram
    WORKSPACE ||--o{ IMPORTED_VIDEO : contains
    WORKSPACE ||--o{ LIVE_STREAM : monitors
    WORKSPACE ||--o{ CLIP : stores
    WORKSPACE ||--o{ AI_MODEL_ASSIGNMENT : configures

    IMPORTED_VIDEO ||--o{ PROCESSING_JOB : triggers
    IMPORTED_VIDEO ||--o{ TRANSCRIPT : has
    IMPORTED_VIDEO ||--o{ CLIP : produces

    LIVE_STREAM ||--o{ PROCESSING_JOB : triggers
    LIVE_STREAM ||--o{ CLIP : produces

    TRANSCRIPT ||--o{ TRANSCRIPT_SEGMENT : contains
    TRANSCRIPT_SEGMENT ||--o{ WORD_TIMESTAMP : contains

    CLIP ||--o{ CAPTION_TRACK : styles
    CLIP ||--o{ EXPORT_JOB : renders

    AI_PROVIDER ||--o{ AI_MODEL_ASSIGNMENT : provides

    WORKSPACE {
        string id PK
        string name
        string local_storage_path
        datetime created_at
    }

    IMPORTED_VIDEO {
        string id PK
        string workspace_id FK
        string file_name
        string file_path
        int file_size_bytes
        float duration_seconds
        int width
        int height
        float fps
        string video_codec
        string audio_codec
        string status
        datetime created_at
    }

    LIVE_STREAM {
        string id PK
        string workspace_id FK
        string stream_url
        string platform
        string status
        int buffer_minutes
        datetime started_at
        datetime stopped_at
    }

    PROCESSING_JOB {
        string id PK
        string entity_type
        string entity_id
        string job_type
        string status
        float progress_percent
        string error_message
        datetime created_at
        datetime updated_at
    }

    TRANSCRIPT {
        string id PK
        string video_id FK
        string language
        string model_used
        datetime created_at
    }

    TRANSCRIPT_SEGMENT {
        string id PK
        string transcript_id FK
        int segment_index
        float start_time
        float end_time
        string text
        float confidence
    }

    WORD_TIMESTAMP {
        string id PK
        string segment_id FK
        string word
        float start_time
        float end_time
        float probability
    }

    CLIP {
        string id PK
        string workspace_id FK
        string source_video_id FK
        string title
        string rationale
        float viral_score
        float start_time
        float end_time
        string aspect_ratio
        json crop_coordinates
        string status
        datetime created_at
    }

    CAPTION_TRACK {
        string id PK
        string clip_id FK
        string style_preset
        string font_family
        int font_size
        string primary_color
        string highlight_color
        string animation_type
        string position
    }

    EXPORT_JOB {
        string id PK
        string clip_id FK
        string output_file_path
        string resolution
        string codec
        int output_size_bytes
        string status
        datetime completed_at
    }

    AI_PROVIDER {
        string id PK
        string name
        string provider_type
        string base_url
        boolean is_local
        boolean is_active
    }

    AI_MODEL_ASSIGNMENT {
        string id PK
        string workspace_id FK
        string task_type
        string provider_id FK
        string model_name
    }
```

---

## 11. Security, Privacy & Local Isolation

1. **Local-First Zero Telemetry**: ClipStudio operates strictly on the user's workstation. No analytics, tracking beacons, or telemetry data are collected.
2. **Credential Management**:
   - Cloud API keys (OpenAI, Gemini, Groq) are never stored in the database or `.env` files in plain text.
   - Keys are encrypted using the Windows Data Protection API (DPAPI) via Python's `keyring` library (`keyring.set_password("ClipStudio", provider_name, api_key)`).
3. **Subprocess Sanitization & Path Traversal Prevention**:
   - All FFmpeg and external binary executions use explicit parameter lists (`subprocess.Popen(["ffmpeg", ...])`), completely forbidding `shell=True`.
   - File uploads and path parameters are validated using strict `os.path.commonpath` checks against workspace roots to prevent directory traversal exploits.
4. **Temporary File Life Cycle**:
   - Intermediate 16kHz WAV files, frame dumps, and temporary chunks are created with UUIDs in an isolated `temp/` folder and registered in a cleanup registry that executes upon job completion or termination.

---

## 12. Testing Strategy

| Domain | Scope | Tools & Method | Success Threshold |
| :--- | :--- | :--- | :--- |
| **Backend Unit Tests** | Pydantic models, timecode math, ASS generator, job state transitions | `pytest`, `pytest-asyncio` | 90%+ branch coverage on core logic |
| **API Integration** | Video upload, job trigger, transcript retrieval, clip CRUD | FastAPI `TestClient`, in-memory SQLite | Verified HTTP 200/201 responses & schema validation |
| **FFmpeg Integration** | Synthetic video generation via `testsrc`, audio demux, cut, filter execution | `pytest` with real FFmpeg binaries | Frame-accurate cuts, valid output headers |
| **Speech Recognition** | Synthetic audio transcription with mock & real int8 models | `faster-whisper` test suite on 10s audio | Accurate word timings, zero memory leaks |
| **AI Provider Mocking** | Ollama offline handling, response parsing, JSON schema enforcement | `respx` / `pytest_mock` | Verified error reporting on unreachable host |
| **Frontend Unit & Component** | Radix primitives, Zustand store updates, timecode formatters | `Vitest`, `@testing-library/react` | 100% pass on state mutations |
| **End-to-End Workflow** | Import -> Transcribe -> Highlight -> Edit -> Render | Playwright E2E browser tests | Full clip export cycle verified in UI |

---

## 13. Phased Development Roadmap

### Phase 1: Core Foundation & Database Engine (Current Target)
- **Objective**: Establish monorepo structure, FastAPI server, SQLite WAL database, Alembic migrations, and logging.
- **Milestone Commit**: `feat(core): initialize database schemas, job engine, and fastapi baseline`

### Phase 2: Media Ingestion & FFmpeg Subsystem
- **Objective**: Implement FFprobe metadata inspection, file upload validation, audio extraction (16kHz WAV), and fast stream-copy cut engine.
- **Milestone Commit**: `feat(media): implement ffmpeg audio extraction and video slicing engine`

### Phase 3: Speech Recognition Subsystem (Faster-Whisper)
- **Objective**: Implement chunked transcription service with word timestamps, Silero VAD, and WebSocket progress broadcasting.
- **Milestone Commit**: `feat(whisper): add faster-whisper int8 speech recognition engine`

### Phase 4: Local AI Subsystem & Highlight Engine
- **Objective**: Implement `AIProvider` abstraction, Ollama integration, structured highlight extraction, and viral scoring.
- **Milestone Commit**: `feat(ai): implement ollama provider and structured highlight discovery`

### Phase 5: Smart 9:16 Video Framing & Caption Engine
- **Objective**: Implement bounding-box crop calculator, dynamic `.ass` subtitle generator, and re-encoding export engine.
- **Milestone Commit**: `feat(render): implement 9:16 reframing and karaoke subtitle burn-in`

### Phase 6: Live Stream Monitoring & Buffer Engine
- **Objective**: Build rolling ring-buffer capture for HLS/RTMP streams, instant 60s clipping, and reconnection resilience.
- **Milestone Commit**: `feat(live): add live stream ring buffer and instant clipping engine`

### Phase 7: Creator Studio Frontend
- **Objective**: Build Vite/React studio with custom timeline video player, transcript editor, framing preview, and export controls.
- **Milestone Commit**: `feat(ui): implement creator workspace and interactive video player`

### Phase 8: End-to-End Hardening & Performance Polish
- **Objective**: Integrate full pipeline, memory leak auditing on 16GB RAM, Playwright E2E tests, and installer preparation.
- **Milestone Commit**: `chore(release): complete end-to-end integration and hardware optimizations`

---

## 14. Technical Risks & Hardware Mitigations

| Technical Risk | Impact | Concrete Mitigation Strategy |
| :--- | :--- | :--- |
| **RAM Exhaustion on 16GB Host** | System thrashing or OOM killer during simultaneous Whisper + LLM execution | **Sequential Execution Policy**: Whisper and LLM are scheduled sequentially, never concurrently. Peak RAM during Whisper is ~1.2 GB; during Ollama is ~2.2 GB. Total system memory load stays under 9.0 GB. |
| **CPU Saturation (100% Load)** | System freeze or UI latency on 4-core i5-1135G7 | **Thread Clamping**: Clamp FFmpeg to `-threads 4` and Faster-Whisper to `cpu_threads=4`. The remaining 4 logical cores remain available for the OS and user interface. |
| **Audio/Video Sync Drift in Cuts** | Subtitles and video drift out of sync after cutting | Always cut using keyframe-aware PTS re-indexing: `-avoid_negative_ts make_zero -async 1`. Store timecodes in absolute float seconds. |
| **Live Stream Buffer Overflow** | Disk filling up on multi-hour continuous live streams | Fixed ring-buffer pruning: Worker process enforces max 60-minute buffer window; deletes `.ts` segments older than 60 minutes continuously. |
| **Local LLM Hallucinations in Timestamps** | LLM proposing clips outside actual video boundaries | Prompt constraint: LLM is passed chunk IDs and segment indices, not freeform timestamps. The backend maps proposed segment IDs directly back to Whisper's exact millisecond timestamps. |

---

## 15. Recommended First Implementation Milestone

The recommended first implementation milestone is **Phase 1: Project Scaffolding, Backend Database Engine & Ingestion Baseline**:
1. Create `clipstudio-backend/` scaffolding with `pyproject.toml` and FastAPI application factory.
2. Initialize SQLite async database with WAL mode and Alembic migrations for core entities (`Workspace`, `ImportedVideo`, `ProcessingJob`).
3. Create `clipstudio-frontend/` scaffolding with Vite, React 19, TypeScript, and Tailwind CSS.
4. Verify end-to-end communication between the React frontend and FastAPI backend over REST and WebSockets.
