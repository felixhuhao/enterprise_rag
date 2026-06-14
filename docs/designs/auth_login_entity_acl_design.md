# Design: Real-auth login + entity-level ACL (MVP)

Date: 2026-06-14
Status: Approved (pending spec review)

## Goal & context

The platform is production-shaped everywhere except auth: today access is
token-only — the frontend stores a raw token in `localStorage` and sends it as
`Bearer`, with no login screen (an admin pastes a token in Settings). The
`users` table holds `user_id, username, api_token (plaintext), role`, and ACL is
per-document via `document_acl(document_id, user_id, permission)` with a
read-only admin audit view but **no UI to grant/revoke or to create users**.

This rework brings auth up to the level of the rest of the platform: real
password login with expiring sessions, and an entity-level ACL that is actually
manageable from the UI. Scope is a tight MVP — real mechanics, minimal surface.

## Decisions (locked)

- **Real auth, tight scope**: hashed passwords + expiring server-side sessions.
  Out: SSO/OAuth/2FA/email verification/password-reset-email.
- **Admin-provisioned users only** — no public signup.
- **Entity-level ACL**: access is granted on `entity_name`, tiers `read | write`.
- **Grant defines the entity, not the upload.** A user can only upload into /
  manage an entity they already hold `write` on; the server validates an
  upload's `entity_name` against the user's grants and rejects anything else, so
  uploading can never mint or claim an entity. Admin is the only role that
  creates an entity (issues the first grant on a new name) and the only role
  that grants access to others.
- **Write-tier users self-serve content** (upload / delete / reprocess) within
  their entities. Shared entities are shared stewardship: anyone with `write` on
  an entity can manage all documents in it. `uploaded_by` is recorded for audit
  only; there is no per-document ownership.
- **Admin** keeps full bypass (role `admin`): sees all documents, manages all
  users and grants.

## Implementation choices (decided, not asked)

- **Sessions: opaque DB-backed tokens, not JWT.** Login mints a random
  `secrets.token_urlsafe` token with an expiry row; the frontend sends it as
  `Bearer` exactly as today; `lookup_user` joins `sessions` and checks expiry.
  This reuses the existing Bearer plumbing (`frontend/src/api/client.ts`,
  `backend/app/deps.py`) and is revocable (logout = delete row). TTL: 7 days,
  sliding-renewed on use.
- **Password hashing: `bcrypt`** (add to `backend/requirements.txt`).

## Data model (SQLite)

```
users          add  password_hash TEXT
               add  created_at TEXT
               (api_token retained only as legacy admin bootstrap, see Migration)

sessions       token       TEXT PRIMARY KEY
               user_id     TEXT NOT NULL
               created_at  TEXT NOT NULL
               expires_at  TEXT NOT NULL
               INDEX idx_sessions_user ON sessions(user_id)

entity_acl     entity_name TEXT NOT NULL
               user_id     TEXT NOT NULL
               permission  TEXT NOT NULL   -- 'read' | 'write'
               PRIMARY KEY (entity_name, user_id)
               INDEX idx_entity_acl_user ON entity_acl(user_id)

general_documents  add  uploaded_by TEXT DEFAULT ''   -- audit only

document_acl   retired: stop using; migration backfills entity_acl from it.
```

## Backend changes

### `core/auth.py` (rework around `entity_acl`)
- `lookup_user(token)` → join `sessions`, reject expired; return `CurrentUser`.
- `get_allowed_document_ids(user)` → `None` for admin; else
  `SELECT document_id FROM general_documents WHERE entity_name IN (<granted entities>)`.
  **Signature unchanged** so retrieval/query filtering
  (`api/query_chat.py`, `api/retrieval_test.py`) is untouched.
- `has_permission(user, document_id, min_permission)` → resolve the document's
  `entity_name`, check `entity_acl`. `read` satisfied by `read|write`; `write`
  requires `write`. Admin always true. (Existing `'owner'` callers in
  `api/documents.py` become `'write'`.)
- New: `user_entities(user, min_permission='read')`, `can_write_entity(user, entity_name)`.
- New: `grant_entity(entity_name, user_id, permission)`, `revoke_entity(entity_name, user_id)`
  (replace `grant_permission` / `remove_document_acl`).
- New: `hash_password`, `verify_password`, `create_session(user_id)`,
  `delete_session(token)`, `touch_session(token)` (sliding renew).

### New `api/auth.py`
- `POST /auth/login` — `{username, password}` → `{token, user}` on success, 401 on failure.
- `POST /auth/logout` — deletes the current session.
- `GET /me` — unchanged (moves here or stays in `auth_me.py`).

### New `api/admin_users.py` (admin-only)
- `POST /admin/users` — create user `{username, password, role}`.
- `GET /admin/users` — list users.
- `POST /admin/users/{user_id}/reset-password` — set a new password.
- `DELETE /admin/users/{user_id}` — delete user (and their sessions + grants).
- `GET /admin/entities` — list known entity names (distinct `general_documents.entity_name`
  ∪ `entity_acl.entity_name`).
- `POST /admin/acl/grant` — `{entity_name, user_id, permission}` (creates entity on first grant).
- `POST /admin/acl/revoke` — `{entity_name, user_id}`.

### `api/documents.py`
- Upload: validate `entity_name` ∈ caller's `write` entities (admin: any); set
  `uploaded_by = current_user.user_id`; drop the per-doc owner grant.
- Write-gated ops (delete / reprocess / edit): `has_permission(..., 'write')`.
- Read-gated ops and list: unchanged in shape (`get_allowed_document_ids` /
  `has_permission(..., 'read')`).

## Frontend changes

- **Login view** (new): username/password form; on success store the session
  token in `localStorage('api_token')` (same key → `client.ts` unchanged); a
  route guard redirects to login when there is no token or on a 401.
- **Auth store** (`stores/auth.ts`): add `login()`, `logout()`; keep `fetchMe()`.
- **Admin → Access management**: replace the read-only
  `components/admin/AclAuditView.vue` with a managed view — create/list users,
  grant/revoke entity access (`read|write`). Backed by `api/admin_users.py`.
- Retire `components/settings/TokenSettingsPanel.vue` (raw-token paste is no
  longer the auth path).

## Migration / seeding

On startup, idempotently (matching the existing migration style in
`core/database.py`):
- Add `users.password_hash`, `users.created_at`, `general_documents.uploaded_by`.
- Create `sessions`, `entity_acl`.
- Backfill `entity_acl` from `document_acl` (map each doc grant to its
  document's `entity_name`; `owner → write`, `read → read`).
- Seed demo users **with passwords**: Alice/Bob = `write` on the demo entity
  (e.g. `远景能源`), Admin = role `admin`. Document the demo passwords in the
  demo guide.
- Keep `.env` `API_TOKEN` as an admin **bootstrap** credential: `lookup_user`
  accepts it directly (bypassing the `sessions` table) and resolves to the admin
  user, so the operator is never locked out even with no valid session.

## Testing

- Unit: `hash_password`/`verify_password`; `create_session`/expiry/`lookup_user`;
  `get_allowed_document_ids` and `has_permission` across entity grants
  (read vs write vs none vs admin); upload entity-write validation including the
  escalation case (write-user uploading into an unauthorized entity → rejected).
- API: login success/failure, logout invalidates, expired session → 401, admin
  user CRUD, grant/revoke, non-admin blocked from admin endpoints.
- Update existing ACL tests from per-document to per-entity.

## Out of scope (explicit)

Per-document ownership inside a shared entity; delegated granting (write-users
inviting others); password-reset email; rate-limiting / account lockout;
SSO / 2FA.
