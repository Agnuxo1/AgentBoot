# AgentBoot — Usage

A tour of the `agentboot` CLI, by subcommand. Every example here is
backed by a passing test; nothing in this document relies on a feature
that isn't implemented.

## Installation

```bash
pip install agentboot            # core
pip install agentboot[cloud]     # + Anthropic / Gemini fallbacks
pip install agentboot[local]     # + llama-cpp-python for on-device LLM
pip install agentboot[all]       # everything
```

## Global flags

| Flag | Purpose |
| --- | --- |
| `-v`, `--verbose` | Drop to DEBUG log level |
| `--config PATH` | Override the default config file location |

## Subcommands

### `chat` — conversational REPL

```bash
agentboot chat --model models/Qwen3.5-0.8B-UD-Q4_K_XL.gguf
```

Slash commands inside the REPL: `/detect`, `/recommend [tag]`,
`/hardware`, `/help`, `/quit`.

### `detect` — hardware detection

```bash
agentboot detect                       # local machine
agentboot detect --ssh 10.0.0.42       # remote via SSH
agentboot detect --json                # machine-readable output
```

### `recommend` — pick an OS for this machine

```bash
agentboot recommend                    # top 3
agentboot recommend --filter nas       # NAS-focussed distros only
agentboot recommend --json --top 5     # JSON, top 5
```

Valid `--filter` values: `server`, `minimal`, `hypervisor`, `nas`,
`desktop`, `container`, `router`.

### `list-isos` — show the curated catalogue

```bash
agentboot list-isos
agentboot list-isos --arch arm64
agentboot list-isos --json
```

### `download` — fetch + verify an installer

```bash
agentboot download ubuntu-server-2404 --dest ~/Downloads/isos
```

Resumes on disconnect (HTTP `Range`), verifies against the vendor's
`SHA256SUMS` when available, emits the final path on stdout.

### `list-devices` — find candidate USB sticks

```bash
agentboot list-devices
```

Lists only **removable, non-system** block devices. The flasher will
refuse to write to anything else.

### `flash` — write an ISO to USB

```bash
agentboot flash \
    --iso ~/Downloads/isos/ubuntu-24.04.3-live-server-amd64.iso \
    --device /dev/sdb \
    --yes-destroy-device /dev/sdb
```

`--yes-destroy-device` must equal `--device` — typo-proofing. The first
call without it prints the plan and exits so you can review.

### `gen-config` — generate autoinstall files

```bash
agentboot gen-config \
    --os ubuntu-server \
    --user alice --password-hash '$6$salt$hash' \
    --hostname rack-01 \
    --package nginx --package docker-ce \
    --output ./cloud-init
```

Supported OS prefixes: `ubuntu-server`, `ubuntu`, `debian`, `rhel`,
`centos`, `rocky`, `alma`, `fedora`, `kickstart`, `windows-server`,
`windows`.

### `session` — inspect / reset

```bash
agentboot session show --dir ./.agentboot-session
agentboot session reset --dir ./.agentboot-session
```

### `install` — full orchestrated flow

```bash
agentboot install \
    --session-dir ./rack-01 \
    --download-dir ./rack-01/iso \
    --filter server \
    --device /dev/sdb \
    --user alice --password-hash '$6$salt$hash' \
    --hostname rack-01 \
    --resume
```

Each phase is idempotent: re-running with `--resume` picks up at the
recorded state instead of re-doing destructive work. Stop the command
at any time — the session file is consistent.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Error during execution (download, detection, etc.) |
| 2 | Bad input (missing file, unknown OS id, unknown session) |
| 3 | Safety refusal (checksum mismatch, cannot flash) |
| 4 | Flash plan printed, confirm token absent |

## Environment variables

- `AGENTBOOT_CONFIG` — path to a JSON config file
- `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY` — cloud LLM fallbacks
