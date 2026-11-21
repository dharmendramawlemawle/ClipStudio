# ClipStudio

ClipStudio is an independent, local-first, AI-powered video clipping and creator workspace platform. It is designed to empower content creators, video editors, and live streamers to ingest long-form media, transcribe speech, detect highlights, generate viral-ready vertical and horizontal clips, edit captions, and manage publishing workflows seamlessly.

---

## Current Development Status

> **Status: Initial Setup / Repository Foundation**  
> All features, capabilities, and system architectures described below are in the design and planning phase. There is currently no application code or feature implemented.

---

## Core Product Vision

ClipStudio aims to deliver an end-to-end studio experience that bridges the gap between raw video/stream archives and polished, platform-ready short-form content. By combining high-performance media processing pipelines with locally hosted or cloud-based AI models, creators can automatically identify key moments, generate synchronized subtitles, adjust framing (9:16 vertical re-framing), and preview results in a real-time creator dashboard.

### Planned Capabilities (Roadmap)

- **Video Ingestion & Stream Capture (Planned)**:
  - Local video file imports (MP4, MKV, MOV, etc.).
  - YouTube, Twitch, and RTMP/HLS live stream monitoring and scheduled recording.
- **Audio Extraction & Transcription Pipeline (Planned)**:
  - Audio demuxing with FFmpeg.
  - Speech-to-text using local Whisper models (faster-whisper / Whisper.cpp) and cloud STT fallback.
  - Word-level timestamps and speaker diarization.
- **AI Highlight Detection & Scoring (Planned)**:
  - Multimodal and text-based highlight detection using local LLMs (via Ollama) or hosted AI providers.
  - Viral potential scoring, topic extraction, and automated summary titling.
- **Smart Aspect Ratio & Video Framing (Planned)**:
  - Intelligent auto-framing with subject tracking and face detection for vertical (9:16) platforms (TikTok, YouTube Shorts, Instagram Reels).
- **Interactive Caption & Clip Editor (Planned)**:
  - Word-level subtitle editor with custom styles, animations, and emoji overlays.
  - Real-time video preview player with synchronized transcript scrubbing.
- **Export & Rendering Engine (Planned)**:
  - Hardware-accelerated video cutting, caption burning, and multi-format rendering via FFmpeg.
  - Queue-based background export worker.

---

## Planned Architecture (Not Implemented)

```
┌─────────────────────────────────────────────────────────────────┐
│                    ClipStudio Creator UI (Planned)             │
│            React / Next.js / Tailwind CSS / Video Preview        │
└─────────────────────────────────┬───────────────────────────────┘
                                  │ HTTP / WebSockets
┌─────────────────────────────────▼───────────────────────────────┐
│                    FastAPI Backend Core (Planned)                │
│       API Endpoints • Job Queue Orchestration • State Engine     │
└───────┬─────────────────────────┬─────────────────────────┬─────┘
        │                         │                         │
┌───────▼─────────────┐   ┌───────▼─────────────┐   ┌───────▼─────────────┐
│  FFmpeg Engine      │   │  Local AI (Ollama)  │   │  SQLite / Metadata  │
│  Demux / Cut / Burn │   │  Whisper / LLM      │   │  Projects & Clips   │
│  (Planned)          │   │  (Planned)          │   │  (Planned)          │
└─────────────────────┘   └─────────────────────┘   └─────────────────────┘
```

> *Note: The architectural components outlined above are planned and subject to refinement as technical implementation proceeds.*

---

## Local-First AI Philosophy

ClipStudio prioritizes privacy, predictability, and zero-cloud-cost workflows:
- **Local Inference First**: Designed to utilize local inference engines (such as Ollama and local Whisper variants) where hardware permits.
- **Cloud Optionality**: Support for external API providers as pluggable alternatives when local compute is constrained.
- **Data Privacy**: Raw media assets, transcripts, and generated metadata remain on the user's local disk.

---

## PeakCut — Reference-Only Policy

ClipStudio references PeakCut strictly as a conceptual and usability design benchmark:

- **What ClipStudio learns from PeakCut**:
  - High-level workflow paradigms: stream ingestion, highlight identification, clip card management, and caption editing UX.
  - Usability patterns for video review and subtitle synchronization.

- **Strict Independent Development Policy**:
  - **Zero Code Reuse**: ClipStudio does not use, copy, fork, or adapt PeakCut source code, components, backend logic, or database schemas.
  - **Independent Implementation**: All frontend components, backend endpoints, processing engines, and data models are engineered independently from scratch.
  - **No Shared Git History**: ClipStudio is initialized in a fresh, isolated repository with its own standalone commit lineage.
