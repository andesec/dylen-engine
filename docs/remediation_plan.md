# Remediation Plan: Engine Defects & Security Vulnerabilities

This document outlines defects identified during code review and static analysis (Semgrep/Snyk). It provides specific instructions for a coding agent to remediate these issues.

> **Note:** File paths have been normalized to the current project structure (e.g., `dylen-engine/app` -> `app`).

## 1. Critical Security: Hardcoded Credentials

**File:** `.env.example`

**Defect:**
The example environment file contains hardcoded database credentials (`dylen:dylen_password`). This poses a risk if developers copy this file to `.env` and deploy without changing defaults.

**Instruction:**
- Replace hardcoded passwords with non-secret placeholders.
- **Action:** Change `postgresql://dylen:dylen_password@...` to `postgresql://<user>:<password>@...`.

## 2. Critical Security: SQL Injection in Database Scripts

**File:** `scripts/init_db.py`

**Defect:**
The script uses Python f-strings within `sqlalchemy.text()` to construct SQL queries (e.g., `CREATE DATABASE`). This bypasses SQLAlchemy's parameter binding and is vulnerable to SQL injection.

**Instruction:**
- **Action:** Since `CREATE DATABASE` cannot be parameterized in Postgres, strictly validate the `target_db` variable against an allowlist or a strict regex (alphanumeric only) before interpolation.
- For `SELECT` queries, use SQLAlchemy's `bindparams` or text binding syntax (e.g., `text("SELECT 1 ... WHERE datname = :name")`).

## 3. Security: Sensitive Data Exposure in Logs (Auth)

**File:** `app/api/routes/auth.py`

**Defect:**
The application logs raw exception messages during token verification failures. If the exception contains the raw token, it leaks credentials into the logs.

**Instruction:**
- **Action:** Modify the `try/except` block handling token verification.
- Log a generic error message (e.g., "Token verification failed") instead of the raw exception string if it risks containing the token.
- Ensure User IDs (UIDs) are only logged if necessary and compliant with privacy policies.

## 4. Security: Sensitive Data Exposure in Logs (Push)

**File:** `app/notifications/push_sender.py`

**Defect:**
The `NullPushSender` logs the prefix of the push token (`token_prefix=%s`). While partially masked, it is flagged as a potential credential leak.

**Instruction:**
- **Action:** Ensure the token is heavily masked (e.g., only last 4 chars) or remove the token from the log entirely.

## 5. Security: SSRF & Arbitrary File Read (Email)

**File:** `app/notifications/email_sender.py`

**Defect:**
The code uses `urllib.request.urlopen` with a dynamic URL constructed from configuration. `urllib` supports `file://` schemes, which could allow an attacker (if they control the config) to read local files.

**Instruction:**
- **Action:** Validate the `base_url` in `MailerSendConfig`.
- Ensure it starts with `https://` or `http://` before making the request.
- Alternatively, switch to the `requests` library which does not support `file://` by default, though the file docstring mentions avoiding dependencies. Explicit validation is preferred here.

## 6. Security: SSRF in Header Verification

**File:** `verify_headers.py`

**Defect:**
Similar to the email sender, this file uses `urllib.request.urlopen` with a dynamic `Origin` header or URL.

**Instruction:**
- **Action:** Validate the URL scheme is `http` or `https` before usage.

## 7. Security: Private Key Committed to VCS

**File:** `.certs/origin.key`

**Defect:**
A private key file is present in the repository history.

**Instruction:**
- **Action:** This file must be removed from git. (Note: As a coding agent, ensure it is added to `.gitignore` if not already present, and delete the file from the working tree).

## 8. Configuration: Python Version Mismatch

**Files:** `.python-version`, `Makefile`

**Defect:**
`.python-version` specifies `3.13`, but Snyk/Makefile configurations reference `3.12`.

**Instruction:**
- **Action:** Update `Makefile` (and any CI configs) to use Python `3.13` to match the project standard.

## 9. Build: Makefile Logic Error (SCA)

**File:** `Makefile`

**Defect:**
The `security-sca` target uses `sed` to remove a placeholder package `myapplication` from `requirements.txt`. This is incorrect for this project.

**Instruction:**
- **Action:** Update the `sed` command in `Makefile` to remove `dylen-engine` (or `app` if installed as such) to prevent local package conflicts during Snyk scans.
- Look for: `sed -i.bak '/^myapplication/d' requirements.txt`
- Replace with: `sed -i.bak '/^app/d' requirements.txt` (or the actual package name defined in `pyproject.toml`).