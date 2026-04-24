# AgentBoot — Developer's Guide

## Layout

```
src/agentboot/
├── __init__.py            # package version
├── _errors.py             # base AgentBootError
├── cli.py                 # argparse subcommands + dispatch
├── config.py              # JSON config loader
├── errors.py              # public error re-exports
├── logging_setup.py       # setup_logging() helper
├── hardware_detector.py   # local + SSH detection
├── os_compatibility.py    # OS catalog + scorer
├── iso/                   # catalogue + verifying downloader
├── flasher/               # enumeration + dd-style flasher
├── autoinstall/           # cloud-init / preseed / kickstart / unattend
├── serial_link/           # JSON-over-serial protocol + transports
├── agent/                 # InstallSession + Orchestrator
└── llm/                   # LocalLLM, cloud backends, router
scripts/
└── agentboot_collector.py # stdlib-only, runs on the target
tests/                     # pytest; every module has tests
docs/                      # USAGE / OPERATOR / DEVELOPER / COLLECTOR
```

## Design principles

1. **No stubs, no TODOs in main code.** Every exported symbol has
   a real implementation and at least one test.
2. **Failure is explicit.** Functions raise `AgentBootError` (or a
   subclass) rather than returning sentinels. Callers catch the base
   class when they want to be generic.
3. **Side-effects behind safety rails.** Any function that wipes a
   disk, overwrites a file, or sends a destructive command requires
   an explicit, matching confirm token.
4. **Idempotency by persistence.** `InstallSession` records each
   decision atomically. Re-running `orchestrator.detect()` recomputes
   detection but does not re-download or re-flash.
5. **Stdlib first.** Cloud LLMs are optional extras; llama-cpp is an
   optional extra; PyYAML is never a dependency. The core pipeline
   works with a plain `pip install agentboot-ai`.

## Testing

```bash
pytest                         # everything
pytest tests/test_flasher.py   # one module
pytest -k "session"            # by keyword
```

The slow/flaky tests are isolated:
- `test_local_llm.py` requires a real GGUF model. Skipped in CI by
  default; `pytest --ignore=tests/test_local_llm.py`.
- Network-dependent tests use an in-process `http.server` fixture —
  no external network.

## Adding a new OS to the catalog

1. Edit `src/agentboot/os_compatibility.py` → append to `OS_CATALOG`
   with min RAM / disk / architecture tags. Add a scoring tiebreak
   if needed.
2. Edit `src/agentboot/iso/catalog.py` → append an `IsoEntry` per
   architecture. Prefer vendor URLs that include a `SHA256SUMS` file
   next to the ISO.
3. Add a generator entry in `src/agentboot/autoinstall/generators.py`
   `_DISPATCH` map if this OS uses an autoinstall format not already
   covered (cloud-init / preseed / kickstart / unattend).
4. Add a smoke test under `tests/`.

## Adding a new LLM backend

Implement the `LLMBackend` protocol in `agentboot.llm.base`:

```python
class MyBackend:
    name = "mybackend"
    def generate(self, prompt: str, **kw) -> str: ...
    def chat(self, messages, **kw) -> str: ...
    def chat_stream(self, messages, **kw): ...
```

Then register it with a `Router` in priority order. `LLMUnavailable`
means "skip me"; `LLMError` means "fail hard".

## Cutting a release

1. Bump `src/agentboot/__init__.py` `__version__` and the
   `[project] version` key in `pyproject.toml`.
2. `pytest --ignore=tests/test_local_llm.py` must be green.
3. `git tag vX.Y.Z && git push --tags`.
4. `python -m build && python -m twine upload dist/*`.
