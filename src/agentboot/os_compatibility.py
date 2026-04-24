"""AgentBoot — OS Compatibility Database (M2).

Contains a curated catalogue of installable operating systems and a
recommendation engine that scores each OS against a detected HardwareProfile.

Usage::

    from agentboot.hardware_detector import HardwareDetector
    from agentboot.os_compatibility import recommend_os

    detector = HardwareDetector()
    hw = detector.detect_local()
    recommendations = recommend_os(hw)
    for rec in recommendations[:3]:
        print(rec.name, rec.score, rec.notes)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from agentboot.hardware_detector import HardwareProfile

# ---------------------------------------------------------------------------
# OS Catalogue
# ---------------------------------------------------------------------------

OS_CATALOG: list[dict] = [
    # -------------------------------------------------------------------------
    # General-purpose server distributions
    # -------------------------------------------------------------------------
    {
        "id": "ubuntu-server-2404",
        "name": "Ubuntu Server 24.04 LTS",
        "family": "debian",
        "arch": ["x86_64", "arm64", "riscv64"],
        "min_ram_mb": 512,
        "recommended_ram_mb": 1024,
        "min_disk_gb": 5,
        "recommended_disk_gb": 20,
        "min_cores": 1,
        "url": "https://releases.ubuntu.com/24.04/ubuntu-24.04-live-server-amd64.iso",
        "url_arm64": "https://cdimage.ubuntu.com/releases/24.04/release/ubuntu-24.04-live-server-arm64.iso",
        "size_gb": 1.4,
        "tags": ["server", "lts", "popular", "cloud-ready", "container-host"],
        "pros": [
            "5-year LTS support (2029)",
            "Huge community & package ecosystem",
            "First-class cloud & container support",
            "Automated installer (subiquity) is very smooth",
        ],
        "cons": [
            "Snapd and some Canonical tooling included by default",
            "Heavier than Alpine or Debian minimal",
        ],
        "use_cases": ["web servers", "databases", "Kubernetes nodes", "development VMs"],
    },
    {
        "id": "debian-12",
        "name": "Debian 12 Bookworm",
        "family": "debian",
        "arch": ["x86_64", "arm64", "armhf", "riscv64", "mips64el"],
        "min_ram_mb": 256,
        "recommended_ram_mb": 512,
        "min_disk_gb": 4,
        "recommended_disk_gb": 10,
        "min_cores": 1,
        "url": "https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/debian-12.5.0-amd64-netinst.iso",
        "size_gb": 0.4,
        "tags": ["server", "stable", "minimal", "universal"],
        "pros": [
            "Rock-solid stability, 5-year support cycle",
            "Supports more hardware architectures than any other distro",
            "Minimal netinst ISO (400 MB)",
            "No proprietary services by default",
        ],
        "cons": [
            "Older package versions than Ubuntu",
            "Less beginner-friendly installer",
        ],
        "use_cases": ["servers", "embedded systems", "internet-facing services"],
    },
    {
        "id": "rocky-linux-9",
        "name": "Rocky Linux 9",
        "family": "rhel",
        "arch": ["x86_64", "arm64"],
        "min_ram_mb": 1024,
        "recommended_ram_mb": 2048,
        "min_disk_gb": 10,
        "recommended_disk_gb": 40,
        "min_cores": 1,
        "url": "https://download.rockylinux.org/pub/rocky/9/isos/x86_64/Rocky-9-latest-x86_64-minimal.iso",
        "size_gb": 1.8,
        "tags": ["server", "enterprise", "rhel-compatible"],
        "pros": [
            "RHEL-compatible — same packages, same lifecycle",
            "10-year support (until 2032)",
            "SELinux by default, strong security posture",
            "Preferred in enterprise and HPC environments",
        ],
        "cons": [
            "Higher RAM requirement",
            "Less cutting-edge packages",
        ],
        "use_cases": ["enterprise servers", "HPC clusters", "RHEL replacements"],
    },
    # -------------------------------------------------------------------------
    # Lightweight / minimal
    # -------------------------------------------------------------------------
    {
        "id": "alpine-319",
        "name": "Alpine Linux 3.19",
        "family": "alpine",
        "arch": ["x86_64", "arm64", "armhf", "x86", "s390x", "ppc64le", "riscv64"],
        "min_ram_mb": 128,
        "recommended_ram_mb": 256,
        "min_disk_gb": 0.1,
        "recommended_disk_gb": 2,
        "min_cores": 1,
        "url": "https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-standard-3.19.1-x86_64.iso",
        "size_gb": 0.2,
        "tags": ["minimal", "lightweight", "embedded", "container-base", "iot"],
        "pros": [
            "Tiny ISO (< 200 MB) and RAM footprint",
            "musl libc — minimal attack surface",
            "Ideal base for Docker images",
            "Wide architecture support including RISC-V",
        ],
        "cons": [
            "musl compatibility issues with some software",
            "Not suitable for general desktop use",
            "Sparse documentation compared to Debian/Ubuntu",
        ],
        "use_cases": ["containers", "IoT/embedded", "firewalls", "single-purpose appliances"],
    },
    {
        "id": "dietpi",
        "name": "DietPi",
        "family": "debian",
        "arch": ["x86_64", "arm64", "armhf"],
        "min_ram_mb": 256,
        "recommended_ram_mb": 512,
        "min_disk_gb": 2,
        "recommended_disk_gb": 8,
        "min_cores": 1,
        "url": "https://dietpi.com/downloads/images/DietPi_VM-x86_64-Bookworm.7z",
        "size_gb": 0.3,
        "tags": ["minimal", "lightweight", "arm", "sbc"],
        "pros": [
            "Extremely low footprint, based on Debian",
            "Automated software installer (dietpi-software)",
            "Excellent for ARM boards (Pi, OrangePi, etc.)",
        ],
        "cons": [
            "Custom tooling can diverge from standard Debian",
            "Smaller community than Ubuntu",
        ],
        "use_cases": ["Raspberry Pi", "ARM SBCs", "home servers", "NAS"],
    },
    # -------------------------------------------------------------------------
    # Virtualisation / Hypervisor
    # -------------------------------------------------------------------------
    {
        "id": "proxmox-ve-8",
        "name": "Proxmox VE 8",
        "family": "debian",
        "arch": ["x86_64"],
        "min_ram_mb": 2048,
        "recommended_ram_mb": 8192,
        "min_disk_gb": 32,
        "recommended_disk_gb": 100,
        "min_cores": 2,
        "url": "https://www.proxmox.com/en/downloads/proxmox-virtual-environment/iso",
        "size_gb": 1.2,
        "tags": ["hypervisor", "virtualisation", "server", "enterprise"],
        "pros": [
            "Full-featured KVM + LXC hypervisor with web UI",
            "ZFS support built in",
            "Clustering and HA out of the box",
            "Based on Debian Bookworm",
        ],
        "cons": [
            "x86_64 only",
            "High RAM requirement (8 GB+ recommended for guests)",
            "Not suitable for non-virtualisation workloads",
        ],
        "use_cases": ["home lab", "virtualisation host", "Kubernetes nodes", "NAS + VMs"],
    },
    {
        "id": "esxi-8",
        "name": "VMware ESXi 8",
        "family": "vmware",
        "arch": ["x86_64"],
        "min_ram_mb": 4096,
        "recommended_ram_mb": 16384,
        "min_disk_gb": 8,
        "recommended_disk_gb": 32,
        "min_cores": 2,
        "url": "https://customerconnect.vmware.com/en/downloads/info/slug/datacenter_cloud_infrastructure/vmware_vsphere/8_0",
        "size_gb": 0.4,
        "tags": ["hypervisor", "enterprise", "vmware", "bare-metal"],
        "pros": [
            "Industry standard enterprise hypervisor",
            "Outstanding hardware driver support",
            "vSphere ecosystem integration",
        ],
        "cons": [
            "Requires VMware account / license for full features",
            "Community Edition has limitations",
            "Broadcom acquisition changed licensing",
        ],
        "use_cases": ["enterprise datacenter", "VMware shop workloads"],
    },
    # -------------------------------------------------------------------------
    # NAS / Storage
    # -------------------------------------------------------------------------
    {
        "id": "truenas-scale",
        "name": "TrueNAS SCALE 24.04",
        "family": "debian",
        "arch": ["x86_64"],
        "min_ram_mb": 8192,
        "recommended_ram_mb": 16384,
        "min_disk_gb": 16,
        "recommended_disk_gb": 64,
        "min_cores": 2,
        "url": "https://download.sys.truenas.net/TrueNAS-SCALE-DragonFish/24.04.0/TrueNAS-SCALE-24.04.0.iso",
        "size_gb": 2.5,
        "tags": ["nas", "storage", "zfs", "hyperconverged"],
        "pros": [
            "ZFS with deduplication, snapshots, replication",
            "App marketplace (Docker/Kubernetes based)",
            "Web UI with SMART monitoring and alerts",
            "Native SMB, NFS, iSCSI, S3",
        ],
        "cons": [
            "Requires lots of RAM for ZFS (1 GB per TB of storage recommended)",
            "x86_64 only",
            "Opinionated about storage layout",
        ],
        "use_cases": ["home NAS", "media server", "backup target", "ZFS storage"],
    },
    # -------------------------------------------------------------------------
    # Container / Kubernetes
    # -------------------------------------------------------------------------
    {
        "id": "talos-linux",
        "name": "Talos Linux 1.7",
        "family": "talos",
        "arch": ["x86_64", "arm64"],
        "min_ram_mb": 2048,
        "recommended_ram_mb": 4096,
        "min_disk_gb": 10,
        "recommended_disk_gb": 50,
        "min_cores": 2,
        "url": "https://github.com/siderolabs/talos/releases/download/v1.7.0/talos-amd64.iso",
        "size_gb": 0.1,
        "tags": ["kubernetes", "container", "immutable", "gitops"],
        "pros": [
            "Immutable OS purpose-built for Kubernetes",
            "No SSH, no shell — managed entirely via API",
            "Tiny attack surface",
            "Automatic node upgrades",
        ],
        "cons": [
            "No general-purpose use — only Kubernetes",
            "Steep learning curve if unfamiliar with Talos/K8s",
        ],
        "use_cases": ["Kubernetes clusters", "GitOps infrastructure", "production k8s"],
    },
    # -------------------------------------------------------------------------
    # Desktop / General purpose
    # -------------------------------------------------------------------------
    {
        "id": "ubuntu-desktop-2404",
        "name": "Ubuntu Desktop 24.04 LTS",
        "family": "debian",
        "arch": ["x86_64", "arm64"],
        "min_ram_mb": 2048,
        "recommended_ram_mb": 4096,
        "min_disk_gb": 10,
        "recommended_disk_gb": 25,
        "min_cores": 2,
        "url": "https://releases.ubuntu.com/24.04/ubuntu-24.04-desktop-amd64.iso",
        "size_gb": 5.7,
        "tags": ["desktop", "gui", "beginner-friendly"],
        "pros": [
            "Best-supported Linux desktop",
            "GNOME 46 with Wayland by default",
            "Full hardware support including modern GPUs",
        ],
        "cons": [
            "Heavier resource usage",
            "Not suitable for headless servers",
        ],
        "use_cases": ["developer workstations", "media PCs", "refurbished laptops"],
    },
    {
        "id": "fedora-40",
        "name": "Fedora 40 Server",
        "family": "rhel",
        "arch": ["x86_64", "arm64"],
        "min_ram_mb": 1024,
        "recommended_ram_mb": 2048,
        "min_disk_gb": 10,
        "recommended_disk_gb": 20,
        "min_cores": 1,
        "url": "https://download.fedoraproject.org/pub/fedora/linux/releases/40/Server/x86_64/iso/Fedora-Server-dvd-x86_64-40-1.14.iso",
        "size_gb": 2.3,
        "tags": ["server", "cutting-edge", "rhel-upstream"],
        "pros": [
            "Cutting-edge packages — upstream of RHEL",
            "Excellent systemd and container integration",
            "Cockpit web console built in",
        ],
        "cons": [
            "13-month release cycle (not LTS)",
            "Frequent upgrades needed",
        ],
        "use_cases": ["dev/test servers", "RHEL staging", "modern toolchains"],
    },
    # -------------------------------------------------------------------------
    # BSD family
    # -------------------------------------------------------------------------
    {
        "id": "freebsd-14",
        "name": "FreeBSD 14.0",
        "family": "bsd",
        "arch": ["x86_64", "arm64", "armv7"],
        "min_ram_mb": 512,
        "recommended_ram_mb": 1024,
        "min_disk_gb": 3,
        "recommended_disk_gb": 20,
        "min_cores": 1,
        "url": "https://download.freebsd.org/releases/amd64/amd64/ISO-IMAGES/14.0/FreeBSD-14.0-RELEASE-amd64-disc1.iso",
        "size_gb": 1.1,
        "tags": ["server", "bsd", "networking", "zfs", "jail"],
        "pros": [
            "ZFS built in, outstanding for storage",
            "Jails (containers) — lightweight isolation",
            "Best-in-class network stack",
            "pfSense/OPNsense are based on FreeBSD",
        ],
        "cons": [
            "Smaller Linux software ecosystem",
            "Less hardware driver coverage than Linux",
        ],
        "use_cases": ["firewalls", "NAS", "jail-based isolation", "network appliances"],
    },
    # -------------------------------------------------------------------------
    # Networking / Router
    # -------------------------------------------------------------------------
    {
        "id": "opnsense-241",
        "name": "OPNsense 24.1",
        "family": "bsd",
        "arch": ["x86_64"],
        "min_ram_mb": 1024,
        "recommended_ram_mb": 2048,
        "min_disk_gb": 4,
        "recommended_disk_gb": 16,
        "min_cores": 1,
        "url": "https://mirror.fra10.de.leaseweb.net/opnsense/releases/24.1/OPNsense-24.1-dvd-amd64.iso",
        "size_gb": 0.7,
        "tags": ["firewall", "router", "networking", "bsd"],
        "pros": [
            "Best open-source firewall/router",
            "Web UI with IDS/IPS, VPN, traffic shaping",
            "Weekly security updates",
        ],
        "cons": [
            "Not a general-purpose OS",
            "Requires at least 2 NICs for router use",
        ],
        "use_cases": ["home router", "enterprise firewall", "VPN gateway"],
    },
]


# ---------------------------------------------------------------------------
# Recommendation engine
# ---------------------------------------------------------------------------


@dataclass
class OSRecommendation:
    os_id: str
    name: str
    score: float          # 0.0 – 100.0
    compatible: bool      # False means hard requirement not met
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    use_cases: list[str] = field(default_factory=list)
    download_url: str = ""
    download_size_gb: float = 0.0


def recommend_os(
    hardware: HardwareProfile,
    max_results: int = 10,
    tags_filter: Optional[list[str]] = None,
) -> list[OSRecommendation]:
    """Score and rank all OS entries against *hardware*.

    Parameters
    ----------
    hardware:
        A HardwareProfile from any of the three detection strategies.
    max_results:
        Maximum number of results to return (default 10).
    tags_filter:
        If provided, only return OSes that have at least one of these tags.
        Examples: ``["server"]``, ``["minimal", "lightweight"]``,
        ``["hypervisor"]``.

    Returns
    -------
    list[OSRecommendation]
        Sorted by score (highest first), limited to *max_results*.
    """
    results: list[OSRecommendation] = []

    arch = hardware.arch.lower()
    # Normalise common aliases
    arch_map = {"amd64": "x86_64", "x86-64": "x86_64", "aarch64": "arm64"}
    arch = arch_map.get(arch, arch)

    ram_mb = hardware.ram.total_mb
    cores = hardware.cpu.logical_cores or hardware.cpu.physical_cores

    total_disk_gb = sum(d.size_gb for d in hardware.storage if not d.is_removable)
    # If no storage detected (bare-metal), use a generous default so we don't
    # wrongly exclude OS options.
    if total_disk_gb == 0:
        total_disk_gb = 1000.0

    has_nvidia_gpu = any(g.vendor == "NVIDIA" for g in hardware.gpus)
    has_gpu = bool(hardware.gpus)
    nic_count = len([n for n in hardware.nics if not n.is_wireless])
    has_wired_nics = nic_count > 0

    for entry in OS_CATALOG:
        # ---- Tag filter ----
        if tags_filter:
            if not any(t in entry.get("tags", []) for t in tags_filter):
                continue

        reasons: list[str] = []
        warnings: list[str] = []
        score = 50.0
        compatible = True

        # ---- Architecture check (hard requirement) ----
        supported_arches = entry.get("arch", [])
        if arch not in supported_arches and arch != "unknown":
            compatible = False
            reasons.append(
                f"Architecture {arch} not supported (supports: {', '.join(supported_arches)})"
            )
            score = 0.0
            results.append(
                OSRecommendation(
                    os_id=entry["id"],
                    name=entry["name"],
                    score=score,
                    compatible=False,
                    reasons=reasons,
                    pros=entry.get("pros", []),
                    cons=entry.get("cons", []),
                    use_cases=entry.get("use_cases", []),
                    download_url=entry.get("url", ""),
                    download_size_gb=entry.get("size_gb", 0.0),
                )
            )
            continue

        # ---- RAM check ----
        min_ram = entry.get("min_ram_mb", 0)
        rec_ram = entry.get("recommended_ram_mb", min_ram)

        if ram_mb > 0:
            if ram_mb < min_ram:
                compatible = False
                reasons.append(
                    f"Insufficient RAM: have {ram_mb} MB, need {min_ram} MB minimum"
                )
                score -= 40.0
            elif ram_mb < rec_ram:
                ratio = ram_mb / rec_ram
                score -= (1 - ratio) * 20
                warnings.append(
                    f"RAM is below recommended ({ram_mb} MB / {rec_ram} MB). "
                    "Performance may be limited."
                )
            else:
                # Bonus for having plenty of RAM
                score += min(10.0, (ram_mb / rec_ram - 1) * 5)
                reasons.append(f"RAM adequate ({ram_mb} MB >= {rec_ram} MB recommended)")

        # ---- Disk check ----
        min_disk = entry.get("min_disk_gb", 0)
        rec_disk = entry.get("recommended_disk_gb", min_disk)

        if total_disk_gb < min_disk:
            compatible = False
            reasons.append(
                f"Insufficient storage: have {total_disk_gb:.1f} GB, need {min_disk} GB minimum"
            )
            score -= 30.0
        elif total_disk_gb < rec_disk:
            warnings.append(
                f"Storage below recommended ({total_disk_gb:.1f} GB / {rec_disk} GB). "
                "Consider adding more disk."
            )
            score -= 5.0
        else:
            reasons.append(f"Storage adequate ({total_disk_gb:.1f} GB >= {rec_disk} GB recommended)")

        # ---- Core count check ----
        min_cores_req = entry.get("min_cores", 1)
        if cores > 0 and cores < min_cores_req:
            compatible = False
            reasons.append(f"CPU cores too few: have {cores}, need {min_cores_req}")
            score -= 20.0
        elif cores >= 4:
            score += 5.0

        # ---- Tag-based bonuses ----
        tags = entry.get("tags", [])

        # Hypervisor — bonus for lots of RAM and cores
        if "hypervisor" in tags:
            if ram_mb >= 16384:
                score += 15.0
                reasons.append("Plenty of RAM for running VMs")
            if cores >= 8:
                score += 10.0
                reasons.append("High core count suits a hypervisor")

        # NAS / storage — bonus for multiple disks
        if "nas" in tags or "storage" in tags:
            disk_count = len([d for d in hardware.storage if not d.is_removable])
            if disk_count >= 2:
                score += 10.0
                reasons.append(f"{disk_count} storage devices — good for RAID/ZFS")

        # Container / Kubernetes — GPU bonus
        if "kubernetes" in tags or "container-host" in tags:
            if has_nvidia_gpu:
                score += 8.0
                reasons.append("NVIDIA GPU detected — GPU workloads in containers possible")

        # Networking / firewall — bonus for multiple NICs
        if "firewall" in tags or "router" in tags:
            if nic_count >= 2:
                score += 12.0
                reasons.append(f"{nic_count} NICs detected — ideal for firewall/router setup")
            else:
                warnings.append("Only one NIC detected — firewall needs at least 2 NICs")
                score -= 10.0

        # Minimal / lightweight — extra points for very constrained hardware
        if "minimal" in tags or "lightweight" in tags:
            if ram_mb <= 1024:
                score += 15.0
                reasons.append("Low RAM — lightweight OS is a smart choice")
            if total_disk_gb <= 8:
                score += 10.0
                reasons.append("Limited disk — minimal OS saves space")

        # Server — penalise if this looks like a desktop machine
        if "server" in tags and "desktop" not in tags:
            if has_gpu and ram_mb < 4096:
                # GPU without lots of RAM = desktop-class machine
                score -= 5.0

        # Clamp score
        score = max(0.0, min(100.0, score))

        # Download URL — prefer arch-specific URL when available
        url_key = f"url_{arch}" if f"url_{arch}" in entry else "url"
        url = entry.get(url_key, entry.get("url", ""))

        results.append(
            OSRecommendation(
                os_id=entry["id"],
                name=entry["name"],
                score=round(score, 1),
                compatible=compatible,
                reasons=reasons,
                warnings=warnings,
                pros=entry.get("pros", []),
                cons=entry.get("cons", []),
                use_cases=entry.get("use_cases", []),
                download_url=url,
                download_size_gb=entry.get("size_gb", 0.0),
            )
        )

    # Sort: compatible first, then by score descending
    results.sort(key=lambda r: (not r.compatible, -r.score))
    return results[:max_results]


def format_recommendation(rec: OSRecommendation, rank: int) -> str:
    """Return a formatted text block for one OS recommendation."""
    compat_str = "COMPATIBLE" if rec.compatible else "INCOMPATIBLE"
    lines = [
        f"  #{rank}  {rec.name}  [{compat_str}]  Score: {rec.score:.0f}/100",
        f"      Download: {rec.download_url or 'see website'}  ({rec.download_size_gb:.1f} GB ISO)",
    ]
    if rec.pros:
        lines.append("      Pros: " + " | ".join(rec.pros[:3]))
    if rec.cons:
        lines.append("      Cons: " + " | ".join(rec.cons[:2]))
    if rec.warnings:
        for w in rec.warnings:
            lines.append(f"      [!] {w}")
    if rec.use_cases:
        lines.append("      Best for: " + ", ".join(rec.use_cases[:3]))
    return "\n".join(lines)


def format_top_recommendations(recs: list[OSRecommendation], n: int = 3) -> str:
    """Return a human-readable block of the top-n recommendations."""
    compatible = [r for r in recs if r.compatible][:n]
    lines = [f"\nTop {len(compatible)} OS recommendations for your hardware:\n"]
    for i, rec in enumerate(compatible, 1):
        lines.append(format_recommendation(rec, i))
        lines.append("")
    return "\n".join(lines)
