# GCP Cloud Run CI/CD (Stage → Prod Promotion)

> **Goal**
>
> Set up a secure, low‑cost CI/CD system using **GitHub Actions + GCP** that:
> - Deploys **Stage on `main`**
> - Promotes **Prod only from Stage (no rebuilds)**
> - Keeps **Artifact Registry storage minimal**
> - Runs **DB migrations at deploy time, not runtime**
> - Uses **no long‑lived credentials**

---

## 1. High‑Level Architecture

```
GitHub (push main / tag)
   │
   │  (OIDC)
   ▼
GitHub Actions
   │
   ├─ Build image (Cloud Build recommended)
   ├─ Push → Artifact Registry (stage)
   ├─ Run migrations (Cloud Run Job)
   └─ Deploy Cloud Run service (stage)

Promotion flow:
Stage image DIGEST ──▶ Prod Artifact Registry (retag only)
                         ├─ Run prod migration job
                         └─ Deploy prod Cloud Run service
```

**Key rule:**
> ❌ Never build directly for prod
> ✅ Prod is always a promoted **stage image digest**

---

## 2. Authentication (Required): Workload Identity Federation (WIF)

**What this replaces:**
- ❌ Service account JSON keys in GitHub secrets

**What this gives:**
- Short‑lived credentials
- Safer + free
- GitHub‑native OIDC auth

### Required IAM Roles (per project)
Assign to the CI service account:
- `roles/run.admin`
- `roles/iam.serviceAccountUser`
- `roles/artifactregistry.writer`
- `roles/secretmanager.secretAccessor` (if runtime pulls secrets)

> ⚠️ Create **separate service accounts** for **stage** and **prod** projects.

---

## 3. Environment & Project Layout

### GCP Projects
- `dylen-stage`
- `dylen-prod`

### Artifact Registry
- Repo name (example): `dylen`
- Format: Docker
- Region: same as Cloud Run

### Image Tag Strategy (important)
| Purpose | Tag |
|------|-----|
| Current stage | `stage-current` |
| Current prod | `prod-current` |
| Immutable release | `release-vX.Y.Z` |

> All deployments should ultimately reference **image digests**, not mutable tags.

---

## 4. Artifact Registry Storage Control

**Requirement:** only keep stage + prod (+ optional releases).

### Cleanup Policy (Mandatory)
Configure Artifact Registry cleanup policies to:
- Keep images tagged:
  - `stage-current`
  - `prod-current`
  - `release-*`
- Delete everything else older than N days

This guarantees:
- Minimal storage usage
- No manual cleanup

---

## 5. Docker Image Requirements

### Dockerfile
- Must support:
  - **normal web startup**
  - **migration execution** via command or env flag

### Migration configuration (CRITICAL)

❗ **Migrations must NOT run automatically on container startup.**

The container already has a migration flag/config.

**Instruction to implementer:**
> Locate the existing migration configuration in the container (env var, command flag, or entrypoint switch) and use it.
>
> Do NOT invent a new mechanism.

Expected behavior:
- Default: web server only
- When explicitly invoked: run migrations + seed, then exit

---

## 6. Running Migrations Correctly (Deploy‑Time Only)

### Correct Pattern (Required)

Use **Cloud Run Jobs**:
- Same image as the service
- Different command/args
- Executes **once per deployment**

Example flow:
1. New image built
2. Run migration job using that image
3. Deploy Cloud Run service with migrations disabled

### Why this matters
- Cloud Run scales horizontally
- Instances restart unpredictably
- Startup hooks **will re‑run** migrations if embedded in app boot

---

## 7. CI/CD Workflows

### Stage Deployment
**Trigger:** push to `main`

Steps:
1. Authenticate to **stage project** via WIF
2. Build image (Cloud Build preferred)
3. Push image to stage Artifact Registry
4. Tag digest as `stage-current`
5. Run **stage migration job**
6. Deploy Cloud Run service using **that digest**

---

### Prod Deployment (Promotion‑Only)
**Trigger:** Git tag `v*.*.*`

Steps:
1. Resolve image digest from stage build
2. Copy/retag digest into **prod Artifact Registry**
3. Tag as:
   - `prod-current`
   - `release-vX.Y.Z`
4. Run **prod migration job**
5. Deploy prod Cloud Run using promoted digest

> ❗ No Docker build allowed in prod pipeline

---

## 8. GitHub Actions Notes (Free‑Tier Friendly)

- GitHub Actions used only for orchestration
- Heavy work (builds) should run in **Cloud Build**
- No secrets beyond:
  - GCP project IDs
  - Service account emails

This keeps usage minimal and secure.

---

## 9. Cloud Run Configuration Rules

- Use **separate services**:
  - `api-stage`
  - `api-prod`
- Use **separate databases** or credentials
- Never share mutable resources between envs

---

## 10. Non‑Negotiable Rules

- ❌ No runtime migrations
- ❌ No prod builds
- ❌ No service account keys in GitHub
- ✅ Promote by digest only
- ✅ Migrations via Cloud Run Jobs
- ✅ Cleanup policies enabled

---

## 11. Implementation Checklist

- [ ] WIF configured for stage + prod projects
- [ ] Artifact Registry repos created
- [ ] Cleanup policy applied
- [ ] Cloud Run Job defined for migrations
- [ ] Docker image supports migration command/flag
- [ ] Stage workflow deployed
- [ ] Prod promotion workflow deployed

---

## Final Note to Implementing Agent

> **Before writing any code**:
> - Inspect the existing Dockerfile and startup logic
> - Identify how migrations are currently triggered
> - Use that mechanism explicitly for Cloud Run Jobs
> - Do **not** rely on application startup for migrations

This system is designed for correctness, safety, and low ongoing cost.

