"""AgentBoot — Gradio Demo for Hugging Face Spaces.

Demonstrates:
  1. Hardware spec input (manual or auto-detected in the browser environment)
  2. OS recommendation engine
  3. Conversational Q&A about the results

No real OS installation happens here — this is a live demo of the
detection + recommendation pipeline.

Deploy:  Push this file (plus requirements.txt) to a HF Space
         configured as a Gradio SDK space.
"""

from __future__ import annotations

import sys
from pathlib import Path

import gradio as gr

# Make sure the package is importable when running as a Space
# (the Space should have agentboot installed via requirements.txt)
try:
    from agentboot.hardware_detector import (
        HardwareDetector,
        HardwareProfile,
        CPUInfo,
        RAMInfo,
        StorageDevice,
        GPUInfo,
        NICInfo,
    )
    from agentboot.os_compatibility import (
        recommend_os,
        format_recommendation,
        OS_CATALOG,
    )
except ImportError:
    # Running inside the repo without install — add src to path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from agentboot.hardware_detector import (
        HardwareDetector,
        HardwareProfile,
        CPUInfo,
        RAMInfo,
        StorageDevice,
        GPUInfo,
        NICInfo,
    )
    from agentboot.os_compatibility import (
        recommend_os,
        format_recommendation,
        OS_CATALOG,
    )


# ---------------------------------------------------------------------------
# Helper: build a HardwareProfile from the form inputs
# ---------------------------------------------------------------------------

def build_profile_from_form(
    cpu_brand: str,
    arch: str,
    cores: int,
    ram_gb: float,
    disk_gb: float,
    gpu_vendor: str,
    nic_count: int,
) -> HardwareProfile:
    profile = HardwareProfile(
        hostname="demo-machine",
        os_running="bare-metal",
        arch=arch.lower(),
        cpu=CPUInfo(
            brand=cpu_brand or "Generic x86_64",
            arch=arch.lower(),
            logical_cores=int(cores),
            physical_cores=max(1, int(cores) // 2),
        ),
        ram=RAMInfo(
            total_mb=int(ram_gb * 1024),
            available_mb=int(ram_gb * 1024),
        ),
        storage=[
            StorageDevice(
                device="/dev/sda",
                model="Demo Disk",
                size_gb=float(disk_gb),
            )
        ],
    )

    if gpu_vendor and gpu_vendor != "None":
        profile.gpus = [GPUInfo(vendor=gpu_vendor, model=f"{gpu_vendor} GPU")]

    # Simulate NICs
    profile.nics = [
        NICInfo(name=f"eth{i}", mac=f"00:11:22:33:44:{i:02x}")
        for i in range(int(nic_count))
    ]

    return profile


# ---------------------------------------------------------------------------
# Auto-detect (works in the Space environment too)
# ---------------------------------------------------------------------------

def auto_detect_hardware() -> tuple[str, str, int, float, float, str, int]:
    """Run local detection and return form field values."""
    try:
        detector = HardwareDetector()
        profile = detector.detect_local()
        gpu_vendor = profile.gpus[0].vendor if profile.gpus else "None"
        nic_count = len(profile.nics)
        return (
            profile.cpu.brand,
            profile.arch,
            profile.cpu.logical_cores or 2,
            round(profile.ram.total_mb / 1024, 1),
            round(sum(d.size_gb for d in profile.storage), 1) or 100.0,
            gpu_vendor,
            nic_count,
        )
    except Exception as exc:
        return (f"Detection error: {exc}", "x86_64", 2, 4.0, 50.0, "None", 1)


# ---------------------------------------------------------------------------
# Core recommendation function (called by Gradio)
# ---------------------------------------------------------------------------

def get_recommendations(
    cpu_brand: str,
    arch: str,
    cores: int,
    ram_gb: float,
    disk_gb: float,
    gpu_vendor: str,
    nic_count: int,
    filter_tag: str,
) -> tuple[str, str]:
    """Return (hardware_summary, recommendations_markdown)."""
    profile = build_profile_from_form(
        cpu_brand, arch, int(cores), float(ram_gb), float(disk_gb), gpu_vendor, int(nic_count)
    )

    # Hardware summary
    hw_lines = [
        "### Detected Hardware Profile",
        f"- **CPU**: {profile.cpu.brand}",
        f"- **Arch**: {profile.arch}",
        f"- **Cores**: {profile.cpu.logical_cores} logical",
        f"- **RAM**: {profile.ram.total_mb:,} MB ({profile.ram.total_mb/1024:.1f} GB)",
    ]
    if profile.storage:
        hw_lines.append(f"- **Disk**: {profile.storage[0].size_gb:.0f} GB")
    if profile.gpus:
        hw_lines.append(f"- **GPU**: {profile.gpus[0].vendor} {profile.gpus[0].model}")
    hw_lines.append(f"- **NICs**: {len(profile.nics)}")

    hw_summary = "\n".join(hw_lines)

    # Recommendations
    tags = None
    if filter_tag and filter_tag != "All":
        tag_map = {
            "Server": ["server"],
            "Minimal / IoT": ["minimal", "lightweight"],
            "Hypervisor": ["hypervisor"],
            "NAS / Storage": ["nas", "storage"],
            "Desktop": ["desktop"],
            "Container / K8s": ["container-host", "kubernetes"],
            "Firewall / Router": ["firewall", "router"],
        }
        tags = tag_map.get(filter_tag)

    recs = recommend_os(profile, max_results=10, tags_filter=tags)
    compatible = [r for r in recs if r.compatible]

    if not compatible:
        rec_md = "**No compatible OS found for these hardware specs.**\n\nTry increasing RAM or storage."
    else:
        lines = [f"### Top {min(5, len(compatible))} OS Recommendations\n"]
        for i, rec in enumerate(compatible[:5], 1):
            medal = ["🥇", "🥈", "🥉", "4.", "5."][i - 1]
            lines.append(f"#### {medal} {rec.name}")
            lines.append(f"**Score**: {rec.score:.0f}/100 — {'✅ Compatible' if rec.compatible else '❌ Incompatible'}")
            if rec.pros:
                lines.append("**Pros:**")
                for p in rec.pros[:3]:
                    lines.append(f"- {p}")
            if rec.cons:
                lines.append("**Cons:**")
                for c in rec.cons[:2]:
                    lines.append(f"- {c}")
            if rec.warnings:
                for w in rec.warnings:
                    lines.append(f"> ⚠️ {w}")
            if rec.use_cases:
                lines.append(f"**Best for**: {', '.join(rec.use_cases[:3])}")
            if rec.download_url:
                lines.append(f"**Download**: [{rec.download_url[:60]}...]({rec.download_url})")
                lines.append(f"**ISO size**: {rec.download_size_gb:.1f} GB")
            lines.append("---")
        rec_md = "\n".join(lines)

    return hw_summary, rec_md


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------

CSS = """
.gradio-container { font-family: 'JetBrains Mono', monospace; }
.output-markdown { border: 1px solid #e0e0e0; border-radius: 8px; padding: 12px; }
"""

DESCRIPTION = """
# AgentBoot — AI OS Installer
**Phase 2 Demo: Hardware Detection & OS Recommendation**

AgentBoot is a conversational AI agent that installs operating systems on bare-metal machines.
Connect a phone or PC to a server with no OS and chat — the agent identifies the hardware,
selects the right OS, and guides the installation.

**This demo** shows the hardware detection and OS recommendation engine.
Enter your machine's specs manually or click **Auto-Detect** to scan this machine.
"""

FILTER_CHOICES = [
    "All",
    "Server",
    "Minimal / IoT",
    "Hypervisor",
    "NAS / Storage",
    "Desktop",
    "Container / K8s",
    "Firewall / Router",
]

with gr.Blocks(title="AgentBoot — OS Recommender") as demo:
    gr.Markdown(DESCRIPTION)

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### Hardware Specification")

            cpu_input = gr.Textbox(
                label="CPU Model",
                placeholder="e.g. Intel Core i7-12700K",
                value="",
            )
            arch_input = gr.Dropdown(
                label="Architecture",
                choices=["x86_64", "arm64", "armhf", "riscv64"],
                value="x86_64",
            )
            cores_input = gr.Slider(
                label="CPU Cores (logical)",
                minimum=1,
                maximum=128,
                step=1,
                value=4,
            )
            ram_input = gr.Slider(
                label="RAM (GB)",
                minimum=0.125,
                maximum=512,
                step=0.5,
                value=8.0,
            )
            disk_input = gr.Slider(
                label="Disk (GB)",
                minimum=1,
                maximum=20000,
                step=10,
                value=250.0,
            )
            gpu_input = gr.Dropdown(
                label="GPU Vendor",
                choices=["None", "NVIDIA", "AMD", "Intel", "Apple"],
                value="None",
            )
            nic_input = gr.Slider(
                label="Wired NICs",
                minimum=0,
                maximum=8,
                step=1,
                value=1,
            )
            filter_input = gr.Dropdown(
                label="Filter by category",
                choices=FILTER_CHOICES,
                value="All",
            )

            with gr.Row():
                detect_btn = gr.Button("Auto-Detect This Machine", variant="secondary")
                recommend_btn = gr.Button("Get OS Recommendations", variant="primary")

        with gr.Column(scale=2):
            hw_output = gr.Markdown(label="Hardware Profile", elem_classes=["output-markdown"])
            rec_output = gr.Markdown(label="OS Recommendations", elem_classes=["output-markdown"])

    # ---- Detect button ----
    def on_auto_detect():
        cpu, arch, cores, ram, disk, gpu, nics = auto_detect_hardware()
        return cpu, arch, cores, ram, disk, gpu, nics

    detect_btn.click(
        fn=on_auto_detect,
        inputs=[],
        outputs=[cpu_input, arch_input, cores_input, ram_input, disk_input, gpu_input, nic_input],
    )

    # ---- Recommend button ----
    recommend_btn.click(
        fn=get_recommendations,
        inputs=[
            cpu_input, arch_input, cores_input, ram_input,
            disk_input, gpu_input, nic_input, filter_input,
        ],
        outputs=[hw_output, rec_output],
    )

    # ---- Examples ----
    gr.Markdown("### Quick Examples")
    gr.Examples(
        examples=[
            ["Intel Core i7-12700K", "x86_64", 20, 64.0, 1000.0, "NVIDIA", 2, "Hypervisor"],
            ["ARM Cortex-A72", "arm64", 4, 4.0, 32.0, "None", 1, "Minimal / IoT"],
            ["Intel Atom C3758", "x86_64", 8, 16.0, 250.0, "None", 4, "Firewall / Router"],
            ["Intel Xeon E5-2690v4", "x86_64", 28, 128.0, 4000.0, "None", 2, "NAS / Storage"],
            ["AMD Ryzen 9 7950X", "x86_64", 32, 64.0, 2000.0, "AMD", 1, "Container / K8s"],
        ],
        inputs=[
            cpu_input, arch_input, cores_input, ram_input,
            disk_input, gpu_input, nic_input, filter_input,
        ],
    )

    gr.Markdown(
        "---\n"
        "**AgentBoot** by [Francisco Angulo de Lafuente](https://github.com/Agnuxo1) · "
        "[GitHub](https://github.com/Agnuxo1/AgentBoot) · "
        "Apache 2.0 License"
    )


if __name__ == "__main__":
    demo.launch(css=CSS)
