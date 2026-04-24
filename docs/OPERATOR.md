# AgentBoot — Operator's Guide

You have a bare-metal machine in front of you (or at the other end of
an IPMI/KVM). You want an OS installed on it with minimal clicking.
This guide walks a single install end-to-end.

## 0. Prerequisites

- **On your phone / laptop** (the "operator side"):
  - AgentBoot installed: `pip install agentboot-ai[all]`
  - A USB-C / USB-A stick (at least 4 GB; 16 GB recommended)
  - Optional: a Qwen3.5 GGUF model for fully-offline chat
- **On the target machine**:
  - A USB port that can boot
  - Ability to enter the boot menu (usually F11 / F12 / Esc)
  - Network (wired or Wi-Fi with known SSID+PSK)

## 1. Identify the machine

Plug your USB cable (or walk up to a keyboard). Boot a rescue live ISO —
Alpine works great — and run the collector:

```bash
python3 agentboot_collector.py --report-only > /tmp/hw.json
```

…or, if you prefer remote:

```bash
# From your phone:
agentboot detect --ssh 10.0.0.42
```

The summary prints CPU, RAM, disk, NICs, GPU, and whether the machine
is a hypervisor VM.

## 2. Pick an OS

```bash
agentboot recommend
```

The scorer will pick a default based on the hardware class
(workstation, server, NAS, hypervisor). You can narrow it with
`--filter server|nas|hypervisor|minimal|desktop|container|router`.

## 3. Start a persistent session

From the same directory you'll run all subsequent commands:

```bash
mkdir -p ~/agentboot/rack-01
cd ~/agentboot/rack-01
agentboot session show --dir .   # will error first time (expected)
```

The session is just a JSON file that remembers where you are in the
install flow. You can close the terminal, come back tomorrow, and
`agentboot install --resume` picks up exactly where it left off.

## 4. Download the installer

```bash
agentboot list-isos
agentboot download ubuntu-server-2404 --dest ./iso
```

If the download stalls, just re-run it — the HTTP Range resume will
keep your partial file. When finished, the file's SHA256 is verified
against the vendor's published `SHA256SUMS`.

## 5. Flash a USB stick

```bash
agentboot list-devices
# Pick the right one. The ID is what you'll pass as --device.

agentboot flash \
    --iso ./iso/ubuntu-24.04.3-live-server-amd64.iso \
    --device /dev/sdb
```

The first run prints the plan and exits with code 4 — **review it**.
Then add `--yes-destroy-device /dev/sdb` (same value as `--device`) to
confirm.

## 6. Generate the autoinstall config

```bash
# Generate a POSIX crypt hash first (on any Linux host / WSL):
openssl passwd -6 'your-strong-password'

agentboot gen-config \
    --os ubuntu-server \
    --user alice \
    --password-hash '$6$SALT$THEHASH' \
    --hostname rack-01 \
    --timezone Europe/Madrid \
    --package nginx \
    --output ./cfg
```

Copy the contents of `./cfg/nocloud/` into the installer's seed
location — on a USB-based Ubuntu Server install, that's a second
partition labelled `CIDATA` containing `user-data` and `meta-data`.

## 7. Boot & install

1. Plug the USB into the target.
2. Boot from it (boot menu → select the USB).
3. Ubuntu's subiquity sees the NoCloud seed and runs unattended.
4. Back on your phone, mark progress:

```bash
agentboot session show --dir ~/agentboot/rack-01
# When the target reboots into the newly-installed OS:
agentboot session reset --dir ~/agentboot/rack-01   # if you want to retry
```

## 8. Recovery

- **Flash failed partway**: plug the stick, `agentboot list-devices`,
  re-flash. The new flash writes from byte zero.
- **Download checksum mismatch**: delete the partial file, re-run.
  A mismatch usually means the vendor rolled a new point release; run
  `agentboot list-isos` to see the catalogued name.
- **Session JSON got corrupted**: delete `session.json` and start over;
  no destructive phase is silent, so re-doing detect/recommend is safe.

## Safety

AgentBoot never writes to:
- A disk marked as the system / boot disk
- A non-removable device (unless explicitly marked removable)
- A device with a confirm token that doesn't match the device ID
- A device whose size is smaller than the ISO

If all of these refuse, the flasher errors out rather than "trying
anyway".
