# Runtime Configuration + Feature Flags Plan

This document classifies current `.env` variables into:
- **Bootstrap (env-only):** must stay in environment / secret manager.
- **Runtime config (DB-backed):** can be changed at runtime and applied without redeploy.
- **Feature flags (DB-backed):** enable/disable features/UI/permission gates per tenant and tier.

It also proposes **who can edit what**:
- **Super Admin (GLOBAL):** full control, including global defaults, tier defaults, and any tenant overrides.
- **Admin (GLOBAL):** can edit most runtime config and feature flags, but **not** bootstrap secrets or security-boundary settings.
- **Tenant Admin (Tenant_Admin / TENANT):** can edit their **own organization** overrides within allowed bounds.

## Classification of current `.env` keys

### Bootstrap (env-only; not stored in DB)

These are secrets or infrastructure identifiers that should not be editable at runtime from an admin UI.

- `DYLEN_PG_DSN`, `DATABASE_URL`, `DYLEN_PG_CONNECT_TIMEOUT`, `DYLEN_PG_LESSONS_TABLE`, `DYLEN_PG_JOBS_TABLE`
  - Why: DB connectivity is a deployment boundary; changing it at runtime is unsafe.
  - Editable by: deployment operators only.
- `DYLEN_ALLOWED_ORIGINS`
  - Why: strict CORS is a security boundary; allowlist changes should be a deploy-time change.
  - Editable by: deployment operators only.
- `GEMINI_API_KEY`, `TAVILY_API_KEY`, `DYLEN_MAILERSEND_API_KEY`
  - Why: secrets; do not store in DB unless you introduce envelope encryption/KMS.
  - Editable by: deployment operators only.
- `FIREBASE_PROJECT_ID`, `FIREBASE_SERVICE_ACCOUNT_JSON_PATH`
  - Why: identity boundary; changing it dynamically can break auth and is high-risk.
  - Editable by: deployment operators only.
- `GCP_PROJECT_ID`, `GCP_LOCATION`
  - Why: infrastructure boundary for Vertex AI; keep env-only.
  - Editable by: deployment operators only.
- `DYLEN_DEBUG`
  - Why: affects error disclosure and operational posture.
  - Editable by: deployment operators only.
- `DYLEN_USE_DUMMY_*`, `DYLEN_DUMMY_*`
  - Why: local/test-only toggles; never configurable in production admin UI.
  - Editable by: developers only (local env).

### Runtime config (DB-backed; editable in admin UI)

These are safe to adjust at runtime and should be evaluated per-request (with caching) so changes apply immediately.

- `DYLEN_MAX_TOPIC_LENGTH`
  - Scope: tier default + tenant override.
  - Editable by: Super Admin / Admin (tier defaults), Tenant Admin (their org override).
- `DYLEN_JOB_MAX_RETRIES`
  - Scope: global default (optionally tier default).
  - Editable by: Super Admin / Admin only (cost/safety impact).
- `DYLEN_JOBS_TTL_SECONDS`
  - Scope: global default.
  - Editable by: Super Admin / Admin only.
- `DYLEN_JOBS_AUTO_PROCESS`
  - Scope: global default + tenant override.
  - Editable by: Super Admin / Admin (global), Tenant Admin (their org).
- `DYLEN_CACHE_LESSON_CATALOG`
  - Scope: global default.
  - Editable by: Super Admin / Admin only.
- `DYLEN_SCHEMA_VERSION`, `DYLEN_PROMPT_VERSION`
  - Scope: global default.
  - Editable by: Super Admin only (breaking-change risk).
- `DYLEN_SECTION_BUILDER_PROVIDER`, `DYLEN_SECTION_BUILDER_MODEL`
  - Scope: tier default + tenant override.
  - Editable by: Super Admin / Admin (tier defaults), Tenant Admin (their org override within allowed providers/models).
- `DYLEN_PLANNER_PROVIDER`, `DYLEN_PLANNER_MODEL`
  - Scope: tier default + tenant override.
  - Editable by: Super Admin / Admin (tier defaults), Tenant Admin (their org override within allowed providers/models).
- `DYLEN_REPAIR_PROVIDER`, `DYLEN_REPAIR_MODEL`
  - Scope: global default + tenant override.
  - Editable by: Super Admin / Admin (global), Tenant Admin (their org).
- `DYLEN_FENSTER_PROVIDER`, `DYLEN_FENSTER_MODEL`, `DYLEN_FENSTER_TECHNICAL_CONSTRAINTS`
  - Scope: tier default + tenant override.
  - Editable by: Super Admin / Admin (tier defaults), Tenant Admin (their org).
- Email settings:
  - `DYLEN_EMAIL_FROM_ADDRESS`, `DYLEN_EMAIL_FROM_NAME`, `DYLEN_EMAIL_PROVIDER`, `DYLEN_MAILERSEND_TIMEOUT_SECONDS`, `DYLEN_MAILERSEND_BASE_URL`
  - Scope: global defaults + tenant override (from address/name are often tenant-branded).
  - Editable by: Super Admin / Admin (global), Tenant Admin (their org).

### Feature flags (DB-backed; per tier + per tenant)

These should gate:
- backend endpoints (server enforcement),
- UI visibility (client reads effective flags),
- and optionally “permission-like” actions (RBAC permission + feature flag).

Initial recommended flags:
- `feature.fenster` (default: false; tier-enabled for Plus/Pro)
- `feature.research` (default: false; tier-enabled for Plus/Pro)
- `feature.notifications.email` (default: false; tenant-enabled when configured)
- `feature.ocr` (default: true)
- `feature.writing` (default: true)

Editable by:
- Super Admin / Admin: global defaults + tier defaults + any tenant overrides.
- Tenant Admin: tenant overrides for their org only.

## RBAC guidance for editing

Add dedicated permissions (not tied to `user:manage`):
- `config:read`, `config:write_global`, `config:write_tier`, `config:write_org`
- `flags:read`, `flags:write_global`, `flags:write_tier`, `flags:write_org`

Enforcement:
- GLOBAL roles can edit any org if they have the relevant permission.
- TENANT roles can only edit their own org and only org-scoped settings/flags.
