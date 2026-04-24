# Contributing to AgentBoot

Thanks for your interest. AgentBoot is in pre-alpha; the roadmap moves fast and the codebase is small, so contributions that keep both of those properties healthy are especially welcome.

## Ground rules

1. **Only real code.** If a feature is not implemented end-to-end, do not merge a stub that pretends it is. Add a failing test or a `pytest.skip` instead.
2. **Every feature has a test or a smoke check.** Bug fixes come with a regression test.
3. **Keep the dependency list small.** Each new runtime dependency should be justified in the PR description.
4. **No destructive defaults.** AgentBoot operates on machines with no OS installed; any action that writes to disk, network, or external services must be opt-in and visible to the user.

## Development setup

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

Download the reference model (see [README](README.md)) into `models/`.

## Running the tests

```bash
pytest -v
```

Tests that need the GGUF model auto-skip when it is missing, so `pytest` is green on CI without weights.

## Commit style

- Short imperative subject line, under 72 characters.
- Body explains *why* more than *what* — the diff already shows what.
- Reference the milestone when relevant: `M2: add Claude API fallback`.

## Reporting bugs

Open an issue with:
- What you ran
- What you expected
- What happened (include error output)
- OS, Python version, `llama-cpp-python` version

## Security

If you find a security issue, do not open a public issue. Email the author privately.
