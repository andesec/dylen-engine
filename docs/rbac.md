# RBAC Reference

## Scope Model
- `GLOBAL`: internal platform roles (`Super Admin`, `Admin`, `User`)
- `TENANT`: tenant-scoped roles (`Tenant_Admin`, `Tenant_User`)

## Canonical Roles
- `Super Admin` (`GLOBAL`): full access, including permanent delete operations.
- `Admin` (`GLOBAL`): broad operational/admin access, no permanent delete.
- `User` (`GLOBAL`): self-service access only.
- `Tenant_Admin` (`TENANT`): tenant-scoped management and self-service access, no permanent delete.
- `Tenant_User` (`TENANT`): tenant self-service access only.

## Data Lifecycle Semantics
- `discard`: soft-delete/archive behavior; data is retained but hidden from active flows.
- `restore`: reactivate previously discarded data.
- `delete_permanent`: irreversible deletion; currently assigned only to `Super Admin`.

## Feature Flags
- `feature.tutor.mode`: Enable tutor mode.
- `feature.tutor.active`: Enable active tutor sessions.
- `feature.mock_exams`: Enable mock exams.
- `feature.mock_interviews`: Enable mock interviews.
- `feature.fenster`: Enable fenster widgets.
- `feature.youtube_capture`: Enable YouTube capture.
- `feature.image_generation`: Enable image generation.
- `feature.ocr`: Enable OCR extraction.
- `feature.writing`: Enable writing check.
- `feature.research`: Enable research workflows.
- `feature.notifications.email`: Enable notification emails.

## Feature-Flag Permission Mapping
- Convention: `feature.<path>` -> `feature_<path_with_dots_as_underscores>:use`
- Examples:
  - `feature.research` -> `feature_research:use`
  - `feature.tutor.active` -> `feature_tutor_active:use`

## Core Permission Set
- `user_data:view`: View user account/onboarding data.
- `user_data:edit`: Edit user status/role/tier data.
- `user_data:discard`: Discard users (soft-delete).
- `user_data:restore`: Restore discarded users.
- `user_data:delete_permanent`: Permanently delete users.
- `rbac:role_create`: Create roles.
- `rbac:role_permissions_update`: Update role-permission mappings.
- `flags:read`, `flags:write_global`, `flags:write_tier`, `flags:write_org`
- `config:read`, `config:write_global`, `config:write_tier`, `config:write_org`
- `user:self_read`, `user:quota_read`, `user:features_read`
- `lesson:list_own`, `lesson:view_own`, `lesson:outline_own`, `lesson:generate`, `lesson:outcomes`, `lesson:job_create`
- `section:view_own`
- `job:create_own`, `job:view_own`, `job:retry_own`, `job:cancel_own`
- `media:view_own`
- `notification:list_own`
- `push:subscribe_own`, `push:unsubscribe_own`
- `tutor:audio_view_own`
- `admin:jobs_read`, `admin:lessons_read`, `admin:llm_calls_read`, `admin:artifacts_read`, `admin:maintenance_archive_lessons`
- `lesson_data:discard`, `lesson_data:restore`, `lesson_data:delete_permanent`
- `data_transfer:export_create`, `data_transfer:export_read`, `data_transfer:download_link_create`, `data_transfer:hydrate_create`, `data_transfer:hydrate_read`

## Default Role Grants
- `Super Admin`: all permissions.
- `Admin`: all self-service/admin operational permissions except `*_delete_permanent`.
- `User`: self-service permissions.
- `Tenant_Admin`: tenant-safe management + self-service permissions.
- `Tenant_User`: self-service permissions.

## Permission-To-Role Matrix (Default Grants)
| Permission Family | Super Admin | Admin | User | Tenant_Admin | Tenant_User |
| --- | --- | --- | --- | --- | --- |
| `user_data:view` | Yes | Yes | No | Yes (tenant scope) | No |
| `user_data:edit` | Yes | Yes | No | Yes (tenant scope) | No |
| `user_data:discard` | Yes | Yes | No | Yes (tenant scope) | No |
| `user_data:restore` | Yes | Yes | No | Yes (tenant scope) | No |
| `user_data:delete_permanent` | Yes | No | No | No | No |
| `rbac:*` | Yes | Yes | No | No | No |
| `flags:read` | Yes | Yes | No | Yes | No |
| `flags:write_global` | Yes | Yes | No | No | No |
| `flags:write_tier` | Yes | Yes | No | No | No |
| `flags:write_org` | Yes | Yes | No | Yes | No |
| `config:read` | Yes | Yes | No | Yes | No |
| `config:write_global` | Yes | Yes | No | No | No |
| `config:write_tier` | Yes | Yes | No | No | No |
| `config:write_org` | Yes | Yes | No | Yes | No |
| Self-service (`user:*`, `lesson:*`, `section:*`, `job:*`, `media:*`, `notification:*`, `push:*`, `tutor:*`) | Yes | Yes | Yes | Yes | Yes |
| Admin reads (`admin:*`) | Yes | Yes | No | No | No |
| Data transfer (`data_transfer:*`) | Yes | Yes | Read only | Read only | Read only |
| Feature permissions (`feature_*:use`) | Yes | Yes | By role grants | By role grants | By role grants |

## Enforcement Rules
- Endpoint-level RBAC uses `require_permission(...)`.
- Feature-gated routes use `require_feature_flag(...)`, which now enforces:
  - feature flag enabled for caller context, and
  - mapped `feature_*:use` permission.
- Discarded users are denied by active-user guards and excluded from default user listing/filtering.

## DB Metadata Alignment
- `permissions.display_name` / `permissions.description` are seeded from canonical definitions.
- `feature_flags.description` is upserted from canonical flag definitions.
- See `scripts/seeds/c0d661232a11.py` for source-of-truth seed data.
