# AgentBoot — Bare-Metal Collector

`scripts/agentboot_collector.py` is the "target-side" half of
AgentBoot. It runs on whatever minimal OS is currently executing on
the bare-metal machine (a rescue ISO, an installer live environment,
Alpine, etc.) and:

1. Reports hardware facts back to the operator side.
2. Accepts a handful of commands over serial / stdin-stdout.
3. Writes installer config files to the local filesystem.

## Design constraints

- **Stdlib only.** Alpine's minimal install has Python 3 but not pip.
  The collector therefore depends on nothing beyond `json`,
  `subprocess`, `pathlib`, and `os`.
- **Single file.** No imports from `agentboot` — the collector is
  shipped as one script that operators can `curl`/`scp`/copy by hand.
- **No telemetry, no phoning home.** Every command is explicit.
  The only IO is stdin/stdout (or the serial device you point it at).

## Running

```bash
# One-shot hardware report to stdout
python3 agentboot_collector.py --report-only

# Serve command loop over stdin/stdout (useful over SSH)
python3 agentboot_collector.py

# Serve over a serial device (requires pyserial on the target)
python3 agentboot_collector.py --serial /dev/ttyGS0 --baud 115200
```

## Commands

Every command is one JSON object per line. The envelope:

```json
{"v": 1, "id": "unique-id", "kind": "cmd", "name": "hw.report"}
```

Responses mirror `id`:

```json
{"v": 1, "id": "unique-id", "kind": "response", "ok": true, "data": {...}}
```

### `hw.report`

Emits a structured hardware report:

```json
{
  "hostname": "...", "arch": "x86_64",
  "os_running": "Alpine 3.20",
  "kernel": "Linux 6.6.x",
  "is_virtual": false,
  "cpu": {"brand": "...", "arch": "x86_64", "logical_cores": 8, ...},
  "ram": {"total_bytes": ...},
  "storage": [{"path": "/dev/sda", "size_bytes": ..., "model": "..."}, ...],
  "nics": [...],
  "gpus": [...]
}
```

### `ping`

Returns `{"pong": true}` — a liveness check.

### `config.write`

Writes a file to disk. Directories are created as needed.

```json
{"v":1,"id":"w1","kind":"cmd","name":"config.write",
 "data":{"path":"/target/cloud-init/user-data","contents":"..."}}
```

### `system.reboot`, `system.poweroff`

Executes the corresponding `shutdown` command after acknowledging.
If you're running inside an unprivileged chroot these will fail,
which is fine — the error is reported back as a regular `error` frame.

## Error frames

```json
{"v": 1, "id": "...", "kind": "error", "code": "BAD_ARGS",
 "message": "config.write requires 'path' and 'contents'"}
```

Error codes: `BAD_ARGS`, `UNKNOWN_COMMAND`, `INTERNAL`, `IO_ERROR`.

## Extending

New handlers plug into the `_HANDLERS` dict at the top of the script:

```python
def _handle_my_cmd(cmd: dict) -> dict:
    # cmd has keys v, id, kind, name, data
    return {"v": 1, "id": cmd["id"], "kind": "response",
            "ok": True, "data": {...}}

_HANDLERS["my.cmd"] = _handle_my_cmd
```

Keep them dependency-free — the target may not have `psutil`, `requests`
or anything else beyond Python's stdlib. If you need `lspci` /
`dmidecode`, call them via `subprocess.run` and handle missing binaries
gracefully.
