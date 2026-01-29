# Security Policy

## Reporting Security Vulnerabilities

If you discover a security vulnerability in this project, please report it by emailing the security team. Please do not create public GitHub issues for security vulnerabilities.

## Security Scanning

This project uses multiple security scanning tools to identify and prevent vulnerabilities:

### 1. SCA (Software Composition Analysis) - Snyk

**What it scans:** Dependencies in `pyproject.toml` and `uv.lock`

**Detects:**
- Known vulnerabilities in open-source dependencies
- License compliance issues
- Outdated packages with security fixes

**Run locally:**
```bash
make security-sca
```

**CI/CD:** Runs on every commit

---

### 2. SAST (Static Application Security Testing) - Bandit

**What it scans:** Python source code in `dylen-engine/app/`

**Detects:**
- Hardcoded passwords and secrets
- SQL injection vulnerabilities
- Use of insecure functions
- Weak cryptography
- And 40+ other Python security issues

**Run locally:**
```bash
make security-sast-bandit
```

**CI/CD:** Runs on every commit, uploads results to GitHub Security tab

---

### 3. SAST (Static Application Security Testing) - Semgrep

**What it scans:** Python source code with advanced pattern matching

**Detects:**
- OWASP Top 10 vulnerabilities
- FastAPI-specific security issues
- Complex security patterns
- Data flow vulnerabilities
- Custom security rules

**Run locally:**
```bash
make security-sast-semgrep
```

**CI/CD:** Runs on every commit, uploads results to GitHub Security tab

---

### 4. Container Scanning - Snyk Container

**What it scans:** Docker image `dylen-engine`

**Detects:**
- OS package vulnerabilities
- Application dependency vulnerabilities in the container
- Base image security issues

**Run locally:**
```bash
make security-container
```

**CI/CD:** Runs on every commit

---

### 5. DAST (Dynamic Application Security Testing) - OWASP ZAP

**What it scans:** Running application API endpoints

**Detects:**
- SQL injection
- Cross-site scripting (XSS)
- Security misconfigurations
- Authentication/authorization issues
- API-specific vulnerabilities

**Run locally:**
```bash
make security-dast
```

**CI/CD:** Runs on pull requests and main branch only

---

## Running All Security Scans

Run all scans (except DAST) locally:

```bash
make security-all
```

This will run:
- SCA (Snyk dependency scan)
- SAST (Bandit + Semgrep code scans)
- Container scan

Reports will be saved to the `reports/` directory.

---

## Interpreting Results

### GitHub Security Tab

SAST results from Bandit and Semgrep are automatically uploaded to the GitHub Security tab in SARIF format. You can view them at:

`https://github.com/<org>/<repo>/security/code-scanning`

### Snyk Dashboard

SCA and Container scan results are uploaded to your Snyk dashboard at:

`https://app.snyk.io/org/<your-org>/projects`

### Local Reports

When running scans locally, reports are saved to the `reports/` directory:

- `bandit-report.json` / `bandit-report.sarif` - Bandit results
- `semgrep-report.json` / `semgrep-report.sarif` - Semgrep results
- `zap-report.html` / `zap-report.json` - OWASP ZAP results

---

## Handling Security Issues

### Severity Levels

- **Critical/High:** Must be fixed before merging to main
- **Medium:** Should be fixed or documented with justification
- **Low:** Can be addressed in future updates

### Ignoring False Positives

#### Snyk

Add to `.snyk` file:

```yaml
ignore:
  SNYK-PYTHON-PACKAGE-12345:
    - '*':
        reason: False positive - not exploitable in our context
        expires: 2026-06-01T00:00:00.000Z
```

#### Bandit

Add to `pyproject.toml`:

```toml
[tool.bandit]
skips = ["B101"]  # Skip specific check
```

Or use inline comments in code:

```python
password = get_password()  # nosec B105
```

#### Semgrep

Add to `.semgrep.yml`:

```yaml
rules:
  - id: rule-to-ignore
    paths:
      exclude:
        - "specific/file.py"
```

---

## Required Setup

### Local Development

1. **Install Snyk CLI:**
   ```bash
   brew install snyk
   # or
   npm install -g snyk
   ```

2. **Authenticate Snyk:**
   ```bash
   snyk auth
   ```

3. **Install Semgrep:**
   ```bash
   pip install semgrep
   # or
   brew install semgrep
   ```

### GitHub Actions

Add the following secrets to your GitHub repository:

1. **SNYK_TOKEN** (Required)
   - Go to https://app.snyk.io/account
   - Navigate to Account Settings → API Token
   - Copy the token and add to GitHub Secrets

2. **SEMGREP_APP_TOKEN** (Optional)
   - For Semgrep Cloud integration and PR comments
   - Get from https://semgrep.dev/manage/settings/tokens

---

## Security Best Practices

1. **Keep dependencies updated:** Regularly run `uv sync` and review updates
2. **Review security scan results:** Check GitHub Security tab and Snyk dashboard weekly
3. **Fix high/critical issues promptly:** Don't let security debt accumulate
4. **Use `.env` for secrets:** Never commit secrets to version control
5. **Run scans before pushing:** Use `make security-all` to catch issues early

---

## Contact

For security concerns or questions, please contact the security team.
