# AgentBoot

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![PyPI version](https://img.shields.io/badge/pypi-v0.2.0-orange.svg)](https://pypi.org/project/agentboot/)
[![HF Space](https://img.shields.io/badge/HuggingFace-Demo-yellow.svg)](https://huggingface.co/spaces/Agnuxo1/agentboot-demo)
[![Status: Alpha](https://img.shields.io/badge/status-alpha-blue.svg)](#roadmap)

> **AI agent that installs operating systems on bare-metal machines — conversationally, from your phone.**

AgentBoot turns any phone or laptop into a portable sysadmin. Connect it to a server with no OS,
no monitor, no keyboard — and chat with the on-device AI. It identifies the hardware, recommends
the right OS, and guides you through the installation step by step.

---

## The Problem

> "I need to revive this old server. What OS should I install? Does it support EFI?
> Is 4 GB of RAM enough for Ubuntu? Which NIC driver do I need?"

A junior sysadmin spends hours on this. A senior sysadmin charges $150/hr.
**AgentBoot does it in a conversation.**

---

## Demo

```
  ___                    _   ____              _
 / _ \                  | | |  _ \            | |
/ /_\ \ __ _  ___ _ __ | |_| |_) | ___   ___ | |_
|  _  |/ _` |/ _ \ '_ \| __|  _ < / _ \ / _ \| __|
| | | | (_| |  __/ | | | |_| |_) | (_) | (_) | |_
\_| |_/\__, |\___|_| |_|\__|____/ \___/ \___/ \__|

  v0.2.0 — Phase 2: Hardware Detection

you> /detect

[AgentBoot] Running hardware detection...

=============================================================
DETECTED HARDWARE
=============================================================
Hostname : my-server
OS (live): Windows 11 22H2
Arch     : x86_64
Virtual  : no

--- CPU ---
  Intel(R) Core(TM) i7-12700K CPU @ 3.60GHz
  Vendor : GenuineIntel
  Cores  : 12 physical / 20 logical
  Max MHz: 5000

--- RAM ---
  Total    : 32,768 MB  (32.0 GB)
  Available: 24,012 MB
  Swap     : 4,096 MB

--- Storage ---
  C:\: Samsung SSD 980 PRO — 953.9 GB [NTFS]

--- GPU ---
  NVIDIA GeForce RTX 3080  VRAM: 10240 MB

--- NICs ---
  Ethernet: 00:1A:2B:3C:4D:5E  1000 Mbps
=============================================================

Top 3 OS recommendations for your hardware:

  #1  Ubuntu Server 24.04 LTS  [COMPATIBLE]  Score: 78/100
      Download: https://releases.ubuntu.com/24.04/...  (1.4 GB ISO)
      Pros: 5-year LTS support | Huge ecosystem | Cloud-ready
      Best for: web servers, databases, Kubernetes nodes

  #2  Proxmox VE 8  [COMPATIBLE]  Score: 75/100
      Download: https://www.proxmox.com/...  (1.2 GB ISO)
      Pros: KVM+LXC hypervisor | ZFS built in | Web UI
      Best for: home lab, virtualisation host, Kubernetes nodes

  #3  Rocky Linux 9  [COMPATIBLE]  Score: 66/100
      Pros: 10-year support | RHEL-compatible | SELinux
      Best for: enterprise servers, HPC clusters

you> Which one is best if I want to run Docker containers?
bot> For Docker, Ubuntu Server 24.04 LTS is your best choice on this hardware...
```

**[Try the live demo on Hugging Face Spaces →](https://huggingface.co/spaces/Agnuxo1/agentboot-demo)**

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Phone / Laptop running AgentBoot                           │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  AgentBoot CLI                                        │  │
│  │                                                       │  │
│  │  ┌─────────────────┐    ┌──────────────────────────┐  │  │
│  │  │  Local LLM       │    │  Hardware Detector       │  │  │
│  │  │  Qwen3.5 0.8B    │    │                          │  │  │
│  │  │  (llama.cpp)     │    │  detect_local()          │  │  │
│  │  │                  │    │  detect_remote_ssh()     │  │  │
│  │  │  Remote LLM      │    │  detect_via_usb_serial() │  │  │
│  │  │  Claude / Gemini │    └──────────────────────────┘  │  │
│  │  └─────────────────┘                                   │  │
│  │                                                       │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │  OS Compatibility DB (14 OS entries)            │  │  │
│  │  │  recommend_os(hardware) → scored list           │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────┘  │
│                           │ USB / SSH / Serial               │
└───────────────────────────┼─────────────────────────────────┘
                            │
         ┌──────────────────▼──────────────────┐
         │  Target bare-metal machine           │
         │  (no OS, no keyboard, no monitor)    │
         └─────────────────────────────────────┘
```

### Detection strategies

| Method | When to use | How it works |
|--------|-------------|--------------|
| `detect_local()` | Agent runs ON the target | psutil + /proc/cpuinfo + nvidia-smi + wmic |
| `detect_remote_ssh()` | Target has a live OS | Paramiko SSH → lscpu, free, lsblk, nvidia-smi |
| `detect_via_usb_serial()` | Bare metal, no OS | USB serial port / IPMI console → JSON profile |

---

## vs. Hiring a Sysadmin

| Task | Sysadmin ($150/hr) | AgentBoot |
|------|-------------------|-----------|
| Identify server hardware | 30 min ($75) | < 5 seconds |
| Research compatible OS | 1 hr ($150) | instant |
| Find right ISO + drivers | 30 min ($75) | instant |
| Guide through installation | 2 hrs ($300) | conversational |
| Available at 3 AM | No | Yes |
| **Total** | **~$600** | **$0** |

---

## Quick Start

### Prerequisites

- Python 3.10, 3.11, or 3.12
- ~1 GB free disk for the model
- Windows, Linux, or macOS

### Install

```bash
git clone https://github.com/Agnuxo1/AgentBoot.git
cd AgentBoot
python -m venv .venv

# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Core install
pip install -e .

# With SSH support
pip install -e ".[ssh]"

# With USB-serial support
pip install -e ".[serial]"

# Everything
pip install -e ".[all,dev]"
```

Or via PyPI (once published):

```bash
pip install agentboot
```

### Get the model

Download `Qwen3.5-0.8B-UD-Q4_K_XL.gguf` (≈530 MB) from
[unsloth/Qwen3.5-0.8B-GGUF](https://huggingface.co/unsloth/Qwen3.5-0.8B-GGUF)
and place it under `models/`.

### Run

```bash
# Interactive chat with hardware detection
agentboot

# Detect hardware immediately on start
agentboot
you> /detect

# Detect a remote machine
you> /detect ssh 192.168.1.100 22 root

# Filter recommendations to server OS only
you> /recommend server

# Non-default model
agentboot --model /path/to/other.gguf
```

### Run the Demo (Gradio)

```bash
pip install -e ".[demo]"
python demo/app.py
# Open http://localhost:7860
```

### Run the Tests

```bash
pytest -v
```

---

## OS Catalogue (Phase 2)

AgentBoot knows about 14 operating systems across 7 categories:

| Category | OS options |
|----------|-----------|
| General server | Ubuntu Server 24.04, Debian 12, Rocky Linux 9, Fedora 40 |
| Minimal / IoT | Alpine Linux 3.19, DietPi |
| Hypervisor | Proxmox VE 8, VMware ESXi 8 |
| NAS / Storage | TrueNAS SCALE 24.04, FreeBSD 14 |
| Container / K8s | Talos Linux 1.7 |
| Firewall / Router | OPNsense 24.1 |
| Desktop | Ubuntu Desktop 24.04 |

Each entry includes: architecture list, minimum/recommended RAM & disk, pros/cons,
use cases, and ISO download URL.

---

## Use Cases

- **Home Lab**: Reviving old servers, installing Proxmox for VMs, setting up a NAS
- **Datacenter Rescue**: A server crashes at 3 AM; you SSH in from your phone
- **Refurbished Hardware**: Buy a lot of used servers; identify and configure each one
- **Edge / IoT**: Deploy Alpine or DietPi on ARM boards in the field
- **IT Education**: Interactive learning tool for sysadmins in training

---

## Roadmap

| Milestone | Scope | Status |
|----------:|:------|:------:|
| **M1** | Local chat CLI · Qwen3.5 0.8B on llama.cpp | ✅ Done |
| **M2** | Hardware detection · OS compatibility DB · Gradio demo | ✅ Done |
| **M3** | Network boot server · DHCP/TFTP · PXE boot pipeline | 🚧 Next |
| **M4** | Automated OS installer · Preseed/cloud-init generation | ☐ |
| **M5** | Minimal Alpine ISO carrying the agent (VM-tested) | ☐ |
| **M6** | Android companion app (USB gadget: mass storage + RNDIS + serial) | ☐ |
| **M7** | Driver database · automatic NIC/GPU driver injection | ☐ |

---

## Project Structure

```
AgentBoot/
├── src/agentboot/
│   ├── __init__.py
│   ├── cli.py                  # Conversational REPL (M1+M2)
│   ├── hardware_detector.py    # Hardware detection engine (M2)
│   ├── os_compatibility.py     # OS catalogue + recommender (M2)
│   └── llm/
│       ├── __init__.py
│       └── local.py            # llama.cpp wrapper
├── demo/
│   ├── app.py                  # Gradio demo for HF Spaces
│   └── requirements.txt
├── tests/
│   ├── test_cli.py
│   ├── test_local_llm.py
│   └── test_hardware.py        # (M2 tests)
├── scripts/
│   └── smoke_test.py
├── models/                     # GGUF models (gitignored)
├── pyproject.toml
└── requirements.txt
```

---

## Non-Goals

- **AgentBoot is not an operating system.** It installs one.
- **No fake features.** Nothing is claimed to work that does not; every committed feature
  has a passing test or a reproducible smoke check.
- **Not a cloud service.** AgentBoot runs locally, on your hardware, with your LLM.

---

## Contributing

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup,
test conventions, and PR process.

---

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

## Author

Francisco Angulo de Lafuente — [@Agnuxo1](https://github.com/Agnuxo1)
