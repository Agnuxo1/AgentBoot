# AgentBoot — Phase 2 Report

**Date**: 2026-04-24
**Author**: Francisco Angulo de Lafuente
**Status**: Completed

---

## Executive Summary

Phase 2 (M2) adds automatic hardware detection and intelligent OS selection to AgentBoot.
The CLI can now identify the hardware of any reachable machine — local, remote via SSH, or
bare-metal via USB serial — and recommend the most compatible operating system from a
curated catalogue of 14 OS options.

---

## What Was Completed in Phase 1 (M1)

| Component | File | Status |
|-----------|------|--------|
| Local LLM wrapper | `src/agentboot/llm/local.py` | Working |
| Chat CLI (REPL) | `src/agentboot/cli.py` | Working |
| Qwen3.5 0.8B GGUF model | `models/Qwen3.5-0.8B-UD-Q4_K_XL.gguf` | Present |
| CLI tests | `tests/test_cli.py` | Passing |
| Smoke test | `scripts/smoke_test.py` | Passing |
| pyproject.toml | v0.0.1 | Working |

The M1 CLI is a clean, honest implementation: only what works is claimed to work.

---

## Phase 2 Deliverables

### 1. Hardware Detection Engine — `src/agentboot/hardware_detector.py`

New file, ~480 lines. Three detection strategies:

#### `HardwareDetector.detect_local()`

Detects hardware on the machine running AgentBoot. Platform-aware:

| Component | Linux | Windows | macOS |
|-----------|-------|---------|-------|
| CPU brand, cores, freq | `/proc/cpuinfo` + psutil | `wmic cpu` + psutil | `sysctl` + psutil |
| RAM | psutil | psutil | psutil |
| Storage | psutil disk partitions | psutil disk partitions | psutil disk partitions |
| GPU | `nvidia-smi` → `lspci` | `nvidia-smi` → `wmic` | `nvidia-smi` → `system_profiler` |
| NICs | psutil net_if_addrs | psutil net_if_addrs | psutil net_if_addrs |
| Virtualisation | `/.dockerenv`, `systemd-detect-virt`, DMI | DMI keywords | DMI keywords |

#### `HardwareDetector.detect_remote_ssh(host, port, user)`

Opens an SSH connection using Paramiko and runs:
`hostname`, `uname`, `/proc/cpuinfo`, `lscpu`, `free -m`, `lsblk`, `nvidia-smi`

Then parses the output into a `HardwareProfile`. Requires: `pip install paramiko`.

#### `HardwareDetector.detect_via_usb_serial(port, baud)`

Sends `IDENTIFY\n` over a serial port and reads back a JSON `HardwareProfile`.
Covers two scenarios:
- IPMI/iDRAC/iLO management console
- AgentBoot live USB companion script

Requires: `pip install pyserial`.

#### Data Model

```
HardwareProfile
├── CPUInfo      (brand, arch, cores, freq, flags, vendor)
├── RAMInfo      (total_mb, available_mb, swap_mb)
├── [StorageDevice]  (device, model, size_gb, fstype, mountpoint)
├── [GPUInfo]    (vendor, model, vram_mb, driver)
└── [NICInfo]    (name, mac, speed_mbps, is_wireless)
```

All dataclasses are serialisable to dict and JSON (`to_dict()`, `to_json()`).
The `summary()` method returns a human-readable single-screen overview.

---

### 2. OS Compatibility Database — `src/agentboot/os_compatibility.py`

New file, ~360 lines. Contains:

#### Catalogue (14 OS entries across 7 categories)

| Category | Entries |
|----------|---------|
| General server | Ubuntu Server 24.04 LTS, Debian 12, Rocky Linux 9, Fedora 40 |
| Minimal / IoT | Alpine Linux 3.19, DietPi |
| Hypervisor | Proxmox VE 8, VMware ESXi 8 |
| NAS / Storage | TrueNAS SCALE 24.04, FreeBSD 14 |
| Container / K8s | Talos Linux 1.7 |
| Firewall / Router | OPNsense 24.1 |
| Desktop | Ubuntu Desktop 24.04 |

Each entry stores: ID, name, family, architecture list, min/recommended RAM & disk,
core requirements, download URL(s), ISO size, tags, pros, cons, use cases.

#### Recommendation Engine — `recommend_os(hardware, max_results, tags_filter)`

Scoring model (0–100):

| Factor | Logic |
|--------|-------|
| Architecture | Hard requirement: incompatible → score=0, skipped |
| RAM | Below minimum: -40 pts; below recommended: proportional penalty; excess: +10 |
| Disk | Below minimum: -30 pts; below recommended: -5 pts |
| CPU cores | Below minimum: -20 pts; 4+ cores: +5 pts |
| Tag bonuses | Hypervisor + ≥16 GB RAM: +15; NAS + ≥2 disks: +10; firewall + ≥2 NICs: +12; minimal + ≤1 GB RAM: +15 |

Output: `list[OSRecommendation]`, sorted by (compatible first, score desc).
Optional `tags_filter` limits the catalogue to a category.

Human-readable output via `format_recommendation()` and `format_top_recommendations()`.

---

### 3. Enhanced CLI — `src/agentboot/cli.py`

Rewritten M1 CLI with:

- **Welcome banner** with version and available commands
- **Slash commands**: `/detect`, `/detect ssh HOST`, `/recommend`, `/recommend <filter>`,
  `/hardware`, `/help`, `/quit`
- **Natural-language intent detection**: typing "detect my hardware" triggers detection
  automatically without needing the slash command
- **Hardware context injection**: detected profile is added to the LLM conversation
  history so follow-up questions get accurate answers
- **Auto-recommend**: after any detection, top 3 OS recommendations are shown immediately
- Backwards compatible: pure chat mode still works unchanged

---

### 4. Gradio Demo — `demo/app.py`

Runnable both locally (`python demo/app.py`) and on Hugging Face Spaces.

Features:
- Manual hardware spec form (CPU, arch, cores, RAM, disk, GPU, NIC count)
- **Auto-Detect button** that calls `detect_local()` and fills the form
- Category filter dropdown (All, Server, Minimal/IoT, Hypervisor, NAS, Desktop, Container, Firewall)
- Top 5 recommendations with score, pros/cons, warnings, download URL, ISO size
- 5 preloaded examples covering different hardware profiles
- Responsive two-column layout

---

### 5. Test Suite — `tests/test_hardware.py`

27 new tests covering:
- `HardwareProfile` serialisation (dict, JSON, summary)
- `detect_local()` smoke test (runs without crashing, returns valid types)
- `_parse_size_to_gb()` edge cases (GB, TB, MB, lowercase, empty)
- OS catalogue completeness (required keys, pros/cons, use cases)
- `recommend_os()` behaviour:
  - Returns list, respects `max_results`
  - Sorted by score descending
  - Compatible entries before incompatible
  - Architecture filter works
  - Tag filter works
  - Low RAM prefers lightweight OS
  - Hypervisor scores high with lots of RAM
  - Firewall NIC bonus is applied
  - Download URLs present
  - Formatting functions return strings

---

### 6. README — Updated

Professional README with:
- Annotated demo session transcript
- Architecture diagram (ASCII)
- Detection strategy comparison table
- "vs. sysadmin" cost comparison ($600 vs $0)
- OS catalogue table
- Use cases section
- Updated roadmap (M1 ✅, M2 ✅, M3–M7 planned)
- Project structure tree

---

### 7. pyproject.toml — Updated

Version bumped to `0.2.0`. Added:
- `psutil>=5.9.0` as core dependency
- Optional extras: `ssh` (paramiko), `serial` (pyserial), `demo` (gradio), `all`, `dev`
- `agentboot-demo` entry point
- `ruff` and `mypy` configuration
- HF Space Demo URL in `[project.urls]`

---

## Architecture After M2

```
src/agentboot/
├── __init__.py              (version bump to 0.2.0)
├── cli.py                   (M1 + M2: slash commands, intent detection)
├── hardware_detector.py     (NEW M2: 3 detection strategies, HardwareProfile)
├── os_compatibility.py      (NEW M2: 14 OS entries, scoring engine)
└── llm/
    ├── __init__.py
    └── local.py             (M1: unchanged)

demo/
├── app.py                   (NEW M2: Gradio demo)
└── requirements.txt         (NEW M2)

tests/
├── test_cli.py              (M1: unchanged)
├── test_local_llm.py        (M1: unchanged)
└── test_hardware.py         (NEW M2: 27 tests)
```

---

## Dependencies Added

| Package | Version | Required for | Optional |
|---------|---------|-------------|---------|
| psutil | >=5.9.0 | RAM, disk, NIC detection | No (core) |
| paramiko | >=3.4.0 | SSH detection | Yes (`[ssh]`) |
| pyserial | >=3.5 | USB-serial detection | Yes (`[serial]`) |
| gradio | >=4.36.0 | Gradio demo | Yes (`[demo]`) |

---

## Known Limitations & Technical Debt

1. **USB-serial bare-metal**: Requires the target to run the companion collector script
   (not yet written — planned for M3). The serial protocol is defined but the other
   side is not implemented.

2. **GPU VRAM on Linux**: `lspci` does not reliably report VRAM size; nvidia-smi does.
   For AMD GPUs on Linux, VRAM detection is incomplete.

3. **Windows disk models**: WMIC returns a generic model name when the drive is behind
   a RAID controller. Consider adding `smartmontools` integration in M3.

4. **OS catalogue**: 14 entries covers the most common cases but misses Windows Server,
   SUSE, Gentoo, NixOS, etc. Will be expanded via community contributions.

5. **Score calibration**: The recommendation scoring is heuristic. A ground-truth dataset
   from real deployments would enable ML-based calibration in a later milestone.

---

## Next Steps — Phase 3 (M3)

1. **Network boot server**: DHCP + TFTP + PXE bootstrap served from AgentBoot's host machine
2. **Companion live USB**: Minimal Alpine image with the hardware collector script
   (outputs JSON over serial on boot)
3. **Automated preseed/cloud-init generation**: produce a complete unattended install
   configuration for Ubuntu, Debian and Alpine from the detected hardware profile
4. **Driver database**: match NIC/GPU PCI IDs to driver packages; inject into preseed
5. **Remote LLM fallback**: Claude / Gemini API when the local model is too small for
   complex reasoning tasks

---

## Running the Full Test Suite

```bash
# Install with dev deps
pip install -e ".[dev]"

# All tests
pytest -v

# Hardware tests only
pytest tests/test_hardware.py -v

# With coverage
pytest --cov=agentboot --cov-report=term-missing
```

---

*Generated by AgentBoot Phase 2 implementation — 2026-04-24*
