# Contributing

Issues and pull requests are welcome. For anything bigger than a small fix, please open an issue first so we can agree on the approach.

## Setup

```bash
git clone https://github.com/pratyushkandari/attendance-system.git
cd attendance-system
python -m venv venv
source venv/bin/activate          # Windows: .\venv\Scripts\activate
make install                      # CPU-only PyTorch, then requirements-dev.txt
cp .env.example .env              # set SECRET_KEY
```

`requirements.txt` has the runtime dependencies (installed in the Docker image) and `requirements-dev.txt` adds the test and lint tools. If you change the PyTorch version, update it everywhere it's pinned: the Dockerfile, `.github/workflows/ci.yml`, the Makefile and the README.

## Before opening a pull request

Run the same checks as CI:

```bash
make lint     # ruff check . && bandit -r app/ -ll
make test     # pytest
```

The tests use in-memory SQLite and an in-process cache (see `tests/conftest.py`), so they never touch your local PostgreSQL or Redis.

If you change enrollment, recognition or check-in, also run the end-to-end tests. They exercise the real stack with real faces: start it with `docker compose up -d`, then run `make e2e`. They use LFW photos, which `make accuracy` downloads into `data/` the first time. They also clear the stack's attendance records, so don't run them against data you want to keep.

- Add or update tests for any behaviour you change. Bug fixes should come with a test that fails without the fix.
- Keep lines under 100 characters and add type hints to new functions; ruff enforces the rest (see `pyproject.toml`).
- Keep pull requests focused on one change, and describe what changed and why.

## Commit messages

This repository uses [Conventional Commits](https://www.conventionalcommits.org/):

```
fix(qr): reject tokens signed with the old SHA-1 digest
feat(kiosk): show the match score under each face
docs: document the Render deployment
```

Common types: `feat`, `fix`, `perf`, `refactor`, `test`, `docs`, `chore`.

## Security issues

Please don't report vulnerabilities in public issues. See [docs/SECURITY.md](docs/SECURITY.md).
