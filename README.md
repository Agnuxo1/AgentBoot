# AgentBoot

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Status: Pre-Alpha](https://img.shields.io/badge/status-pre--alpha-orange.svg)](#roadmap)

> AI agent that installs operating systems on bare-metal machines — conversationally, over USB, from your phone.

AgentBoot turns a smartphone into a portable sysadmin: connect the phone to a server that has no OS, no monitor, no keyboard, and chat with an on-device AI agent that identifies the hardware, fetches drivers, and installs the right operating system.

## Why

Anyone who has tried to revive an old server, a headless mini-PC, or an unfamiliar piece of hardware knows the drill: hours of research to identify the machine, find drivers, and pick a compatible OS. AgentBoot collapses that into a conversation.

## Status

**Phase 1 — Proof of concept.** Desktop CLI running a local small LLM with optional cloud API fallback. No fake features, no stubs: if it is committed, it runs.

Current milestone: **M1 completed** — local Qwen3.5 0.8B chat CLI on llama.cpp.

## Architecture (Phase 1)

```
┌──────────────────────────────────────────┐
│  Developer machine (Windows/Linux)       │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  AgentBoot CLI (Python)            │  │
│  │                                    │  │
│  │  Local LLM ──▶ Qwen3.5 0.8B GGUF  │  │
│  │                (llama.cpp backend) │  │
│  │                                    │  │
│  │  Remote LLM ─▶ Claude / Gemini    │  │  (M2)
│  │                                    │  │
│  │  Hardware ───▶ lshw, dmidecode,   │  │  (M3)
│  │   tools         lspci, smartctl   │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

## Quick start

### Prerequisites

- Python 3.10, 3.11 or 3.12
- ~1 GB free disk for the model
- Windows, Linux or macOS

### Install

```bash
git clone https://github.com/Agnuxo1/AgentBoot.git
cd AgentBoot
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
pip install -e ".[dev]"
```

### Get the model

Download `Qwen3.5-0.8B-UD-Q4_K_XL.gguf` (≈530 MB) from [unsloth/Qwen3.5-0.8B-GGUF](https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF) and place it under `models/`.

### Run

```bash
# Interactive chat
agentboot

# Non-default model
agentboot --model /path/to/other.gguf

# Smoke test (one-shot, verifies inference works)
python scripts/smoke_test.py
```

### Run the tests

```bash
pytest -v
```

## Roadmap

| Milestone | Scope | Status |
|----------:|:------|:------:|
| **M1** | Local chat CLI with Qwen3.5 0.8B on llama.cpp | ✅ |
| **M2** | Remote API fallback (Claude / Gemini) + network detection | 🚧 |
| **M3** | Real hardware-identification tools wired into the agent | ☐ |
| **M4** | Virtual serial channel for agent-to-agent communication | ☐ |
| **M5** | Minimal Alpine bootable ISO carrying the agent (VM-tested) | ☐ |
| **M6** | Android companion app (USB gadget: mass storage + RNDIS + serial) | ☐ |

## Non-goals

- **AgentBoot is not an operating system.** It installs one.
- **No fake features.** Nothing is claimed to work that does not; every committed feature has a passing test or a reproducible smoke check.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for how to set up the dev environment, run the tests, and submit a pull request.

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Author

Francisco Angulo de Lafuente — [@Agnuxo1](https://github.com/Agnuxo1)
