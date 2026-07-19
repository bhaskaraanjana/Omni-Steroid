<!-- ─────────────────────────── HERO ─────────────────────────── -->
![header](https://capsule-render.vercel.app/api?type=waving&color=0F766E&height=240&section=header&text=Omni%20Steroid&fontSize=52&fontColor=ffffff&fontAlignY=38&desc=Meeting%20notes%20that%20stay%20yours.&descAlignY=58&descSize=20&animation=fadeIn)

<div align="center">

### Local-first meeting intelligence — no bot in the call, no cloud by default.

Capture dual audio streams on your machine. Transcribe on-device. Turn rough notes into clean enhanced notes. Ask your vault with real citations. Approve every action before it runs.

<br/>

![License](https://img.shields.io/badge/license-MIT-22c55e?style=for-the-badge)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-0F766E?style=for-the-badge)
![Local-first](https://img.shields.io/badge/local--first-yes-1C1B18?style=for-the-badge)
![Telemetry](https://img.shields.io/badge/telemetry-zero-22c55e?style=for-the-badge)
[![CI](https://img.shields.io/github/actions/workflow/status/bhaskaraanjana/Omni-Steroid/ci.yml?style=for-the-badge&label=CI)](https://github.com/bhaskaraanjana/Omni-Steroid/actions/workflows/ci.yml)

<br/>

<a href="#-see-it-in-action">
  <img src="https://img.shields.io/badge/▶_Product_Tour-0F766E?style=for-the-badge" alt="Product tour"/>
</a>
&nbsp;
<a href="#-quick-start">
  <img src="https://img.shields.io/badge/⚡_Quick_Start-1C1B18?style=for-the-badge" alt="Quick start"/>
</a>
&nbsp;
<a href="https://github.com/bhaskaraanjana/Omni-Steroid/releases">
  <img src="https://img.shields.io/badge/⬇_Releases-Installers-6366f1?style=for-the-badge" alt="Releases"/>
</a>

</div>

---

## ✨ See it in action

> [!NOTE]
> Screenshots and the demo are the **current Omni Steroid app** (Daylight UI) running against the **real Python engine** with seeded synthetic meetings — not mockups, not the legacy monochrome Omni build. Capture notes: [`media/README.md`](media/README.md).

<p align="center">
  <img src="assets/readme/daylight/hero.webp" width="880" alt="Omni Steroid Home — Welcome back with Record, Ask, Voice notes, and Import cards"/>
</p>

<p align="center">
  <img src="assets/readme/daylight/demo.gif" width="880" alt="Omni Steroid product tour — Home, Meetings, meeting detail, Ask, Settings, Voice notes"/>
</p>

<p align="center">
  <sub>Recorded product tour · also as <a href="assets/readme/daylight/demo.mp4"><code>assets/readme/daylight/demo.mp4</code></a></sub>
</p>

### Home

<p align="center">
  <img src="assets/readme/daylight/home.png" width="880" alt="Omni Steroid Home dashboard with Record Meeting, Keyboard Voice Replacement, Ask Across Notes, and Import Audio File"/>
</p>

<p align="center"><em>Home — one place to record, dictate, ask, and import. Data stays on this device.</em></p>

### Meetings library & detail

<table>
  <tr>
    <td width="50%" align="center">
      <img src="assets/readme/daylight/meetings.png" width="100%" alt="Omni Steroid Meetings library grouped by day"/>
    </td>
    <td width="50%" align="center">
      <img src="assets/readme/daylight/meeting-detail.png" width="100%" alt="Meeting detail with enhanced notes, commitments, and transcript"/>
    </td>
  </tr>
  <tr>
    <td align="center"><em>Meetings — search, import, record</em></td>
    <td align="center"><em>Detail — enhanced notes around your words</em></td>
  </tr>
</table>

### Ask across your vault

<p align="center">
  <img src="assets/readme/daylight/ask.png" width="880" alt="Omni Steroid Ask screen querying Northwind renewal"/>
</p>

<p align="center"><em>Ask — natural-language questions over meetings and notes (live synthesis uses your BYOK keys)</em></p>

### Settings

<table>
  <tr>
    <td width="50%" align="center">
      <img src="assets/readme/daylight/settings.png" width="100%" alt="Omni Steroid Settings screen"/>
    </td>
    <td width="50%" align="center">
      <img src="assets/readme/daylight/settings-privacy.png" width="100%" alt="Omni Steroid Settings privacy and advanced controls"/>
    </td>
  </tr>
  <tr>
    <td align="center"><em>Essentials &amp; Advanced — devices, quality, providers</em></td>
    <td align="center"><em>Privacy, ledger, and key custody</em></td>
  </tr>
</table>

### Voice notes

<p align="center">
  <img src="assets/readme/daylight/voice-notes.png" width="880" alt="Omni Steroid Voice notes screen"/>
</p>

<p align="center"><em>Global dictation history — push-to-talk, cleanup styles, searchable notes</em></p>

### First run

<table>
  <tr>
    <td width="25%" align="center"><img src="assets/readme/daylight/onboarding-welcome.png" width="100%" alt="Welcome to Omni Steroid"/></td>
    <td width="25%" align="center"><img src="assets/readme/daylight/onboarding-vault.png" width="100%" alt="Onboarding vault step"/></td>
    <td width="25%" align="center"><img src="assets/readme/daylight/onboarding-keys.png" width="100%" alt="Onboarding keys step"/></td>
    <td width="25%" align="center"><img src="assets/readme/daylight/onboarding-models.png" width="100%" alt="Onboarding models step"/></td>
  </tr>
  <tr>
    <td align="center"><sub>Welcome</sub></td>
    <td align="center"><sub>Vault</sub></td>
    <td align="center"><sub>Keys</sub></td>
    <td align="center"><sub>Models</sub></td>
  </tr>
</table>

---

## 🚀 Features

| | Feature | Description |
|--|---------|-------------|
| 🎧 | **Bot-free capture** | Dual labelled streams — system audio (`them`) + mic (`me`). Works with headphones on Windows (WASAPI). macOS/Linux via monitor devices (BlackHole / PipeWire). |
| 🧠 | **On-device STT** | Silero VAD + streaming transcription (Parakeet-TDT live; Whisper / BYOK cloud for import & retranscribe). Audio stays as local MP3 by default. |
| 📝 | **Enhanced notes** | Your rough notes stay primary. AI fills structure *around* them in clearly marked managed regions. |
| 🔍 | **Ask + citations** | Local RAG over Obsidian vault + transcripts. Inline citations to exact note + line range when synthesis keys are configured. |
| ✅ | **Approval cards** | Calendar, contacts, vault writes, **Gmail drafts only (never send)**. Nothing executes without you. |
| 🎙️ | **Global dictation** | Push-to-talk, locked recording, cleanup styles, inject into any app (Windows), searchable history. Raw text always kept. |
| 📦 | **Export & import** | Markdown, PDF, DOCX, SRT, VTT. Import audio/video; optional speaker identity. |
| 🌊 | **Naomi** | Optional voice agent over the same vault and approval path (when a voice provider is configured). |

> [!TIP]
> **Privacy is the product.** Zero telemetry. Transcripts, embeddings, and keys stay on your machine except the minimum excerpt you send to a model you configured. One control pauses all cloud AI; capture and vault keep working offline.

Full catalog: [`docs/features.md`](docs/features.md).

---

## 🛠️ Built with

<p align="center">
  <img src="https://skillicons.dev/icons?i=react,ts,rust,python,fastapi,sqlite" alt="Tech stack"/>
</p>

<p align="center">

![Tauri](https://img.shields.io/badge/Tauri_2-FFC131?style=for-the-badge&logo=tauri&logoColor=black)
![React](https://img.shields.io/badge/React_18-61DAFB?style=for-the-badge&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)
![Python](https://img.shields.io/badge/Python_3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Rust](https://img.shields.io/badge/Rust-000000?style=for-the-badge&logo=rust&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)

</p>

**Desktop shell:** Tauri 2 + React · **Engine sidecar:** Python FastAPI over localhost WebSocket · **Storage:** SQLite + `sqlite-vec` + your Obsidian vault · **Speech:** Silero VAD, Parakeet / Whisper · **Models (BYOK):** Groq, Gemini, Claude, OpenAI-compatible, Ollama, …

Architecture notes: [`docs/architecture.md`](docs/architecture.md).

---

## ⚡ Quick start

### Prerequisites

| Tool | Purpose |
|------|---------|
| [uv](https://docs.astral.sh/uv/) | Python 3.11 toolchain for the engine |
| [pnpm](https://pnpm.io/) | UI packages |
| [Rust](https://tauri.app/start/prerequisites/) | Tauri shell (MSVC on Windows) |

### From source

```bash
git clone https://github.com/bhaskaraanjana/Omni-Steroid.git
cd Omni-Steroid

uv sync

cd apps/ui
pnpm install
pnpm tauri dev
```

Tauri starts the engine sidecar for you. Health check when running standalone:

```bash
uv run python -m engine.server
# → GET http://127.0.0.1:8765/health
```

UI only (engine already up): `cd apps/ui && pnpm dev`

### First run (about two minutes)

1. Point Omni Steroid at your **Obsidian vault**
2. Add **API keys** you want (all optional — skip what you don’t need):

   | Key | Unlocks | Free tier |
   |-----|---------|-----------|
   | [Groq](https://console.groq.com/keys) | Fast live answers | Yes |
   | [Gemini](https://aistudio.google.com/app/apikey) | Long-context synthesis | Yes |
   | [Anthropic](https://console.anthropic.com/settings/keys) | Agentic / high-quality synthesis | Paid |
   | [Cartesia](https://play.cartesia.ai/) | Naomi voice | Yes |

3. Download **on-device models** (VAD, STT, embeddings)

> [!IMPORTANT]
> With **no keys**, capture, transcription, and vault still work fully offline. Cloud features stay off until you add a key.

### Installers

Tagged releases ship **Windows** (NSIS/MSI), **macOS** (DMG), and **Linux** (deb/AppImage) with signature-verified auto-update when published:

**→ [github.com/bhaskaraanjana/Omni-Steroid/releases](https://github.com/bhaskaraanjana/Omni-Steroid/releases)**

Packaging details: [`packaging/README.md`](packaging/README.md).

---

## 🔒 Privacy by design

| Guarantee | How |
|-----------|-----|
| Local-first | Transcripts, embeddings, notes, and keys stay on-device except minimum model excerpts you opt into |
| No audio upload | Recordings kept as local MP3 with the transcript (or discarded after STT if you opt out) |
| Zero telemetry | No analytics, no phone-home |
| DPAPI keys | Entered at onboarding; engine-only; never plaintext on disk |
| Approve before execute | Calendar / contacts / vault / Gmail draft — deny by default |
| Gmail draft-only | Never sends mail |
| Kill-switch | Halts all external model calls; local features continue |
| Audit log | Append-only record of every external call and executed action |

Threat model: [`docs/threat-model.md`](docs/threat-model.md).

---

## 📦 Repo map

| Path | What lives there |
|------|------------------|
| `apps/ui/` | Tauri shell + React UI |
| `engine/` | Capture, STT, index/RAG, router, agents, vault, Naomi, dictation |
| `assets/readme/daylight/` | Product images used on this page (current Daylight UI) |
| `media/` | Full showcase media + capture notes |
| `docs/` | Architecture, features, design, plans |
| `evidence/` | Measured benchmarks and diagrams |
| `tests/` | Engine + UI test suites |

---

## 🤝 Contributing

Contributions welcome. Before a PR, run the gate:

```bash
uv run ruff check .
uv run mypy
uv run pytest
cd apps/ui && pnpm test
```

See [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md).

## 📄 License

Released under the [MIT License](LICENSE).

![footer](https://capsule-render.vercel.app/api?type=waving&color=0F766E&height=120&section=footer)
