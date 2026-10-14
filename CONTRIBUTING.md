# Contributing Guide

Thank you for your interest in contributing to the **Enterprise Biometric Attendance System**. This project adheres to production engineering standards practiced across high-reliability systems.

---

## 1. Development Environment Setup

### Prerequisites
- Python 3.9+ (Python 3.10 recommended)
- PostgreSQL 14+ (or local SQLite fallback)
- Redis 7+ (optional; transparent in-memory fallback enabled)
- Git 2.30+

### Local Setup
```bash
# Clone the repository
git clone https://github.com/pratyushkandari/attendance-system.git
cd attendance-system

# Initialize Python virtual environment
python -m venv venv
source venv/bin/activate       # On Linux/macOS
.\venv\Scripts\Activate.ps1    # On Windows PowerShell

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
```

---

## 2. Coding Standards & Repository Conventions

### Style & Linting
- **PEP 8**: Strict adherence required.
- **PEP 484**: All public functions, methods, and classes must include explicit type annotations.
- **PEP 257**: All modules, classes, and exported functions must feature Google-style docstrings.
- **Formatting**: Line length capped at 100 characters.

Run linter checks before committing:
```bash
ruff check app/ tests/
```

### Git Commit Guidelines
We enforce the [Conventional Commits](https://www.conventionalcommits.org/) specification:

| Prefix | Usage | Example |
| :--- | :--- | :--- |
| `feat` | New user-facing capability | `feat(api): add batch student embedding export endpoint` |
| `fix` | Bug fix or error resolution | `fix(crypto): prevent timing side-channel in token validation` |
| `refactor` | Code restructuring without functional change | `refactor(vector): vectorize matrix dot product matching` |
| `test` | Adding or updating unit/integration tests | `test(e2e): cover replay attack prevention in QR validation` |
| `docs` | Documentation and architecture updates | `docs(rfc): add ADR-005 on distributed cache fallback` |
| `chore` | Build scripts, dependencies, CI configuration | `chore(deps): bump facenet-pytorch to 2.6.0` |

---

## 3. Testing Policy & Verification

Pull Requests will not be merged unless:
1. **100% of existing test cases pass** with zero warnings or deprecation regressions.
2. **New endpoints or business logic are accompanied by automated tests** under `tests/`.
3. Code coverage does not drop below the repository baseline ($>85\%$).

### Running Test Suites
```bash
# Run all unit and integration tests
python -m pytest -v

# Run with coverage report
python -m pytest --cov=app --cov-report=term-missing tests/

# Execute end-to-end integration scenario
python -m pytest tests/test_attendance.py -k "test_e2e"
```

---

## 4. Branching & Pull Request Workflow

1. Create a focused branch off `main`:
   ```bash
   git checkout -b feat/add-liveness-threshold-config
   ```
2. Make atomic, well-documented commits following the Conventional Commit syntax.
3. Validate locally:
   ```bash
   python -m pytest -v
   ```
4. Push branch to your fork or remote origin and open a Pull Request targeting `main`.
5. Ensure PR description details:
   - Summary of changes and architectural motivation.
   - Related Issue or RFC reference.
   - Benchmark or profiling data if modifying vector math or AI pipelines.

---

## 5. Security Vulnerability Reporting

Please review [SECURITY.md](docs/SECURITY.md) before disclosing potential security vulnerabilities. Do **not** open public GitHub issues for critical zero-day exploits or credential leakages.
