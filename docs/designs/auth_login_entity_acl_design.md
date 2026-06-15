# Design: Real-auth login + entity-level ACL (MVP)

Date: 2026-06-14
Status: Implemented (MVP shipped). See FUTURE_PLAN.md §8 for the shipped-vs-deferred split; deferred hardening (group ACL, chunk-level ACL, full read-path audit, deny-by-default) is tracked under *Tag And ACL Governance Hardening*.

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
- **Entity-level ACL**: access is granted on normalized `entity_name`, tiers
  `read | write`. Normalization is `strip()` only; names are case-sensitive.
  Blank entity names are not grantable and non-admin uploads/renames with a
  blank entity are rejected. `entity_name` is normalized at every write site
  (upload, rename) and `general_documents.entity_name` is normalized once in
  migration, so the column the ACL checks compare against is always normalized.
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
  `secrets.token_urlsafe` token and stores only its SHA-256 hash in `sessions`;
  the raw token is returned once and the frontend sends it as `Bearer` exactly
  as today. `lookup_user` hashes the presented token, joins `sessions`, and
  checks expiry. This reuses the existing Bearer plumbing
  (`frontend/src/api/client.ts`, `backend/app/deps.py`) and is revocable
  (logout = delete row). TTL: 7 days, sliding renewal throttled to avoid a DB
  write on every request: only extend when `expires_at < now + 24h`.
- **Password hashing: `bcrypt`** (add to `backend/requirements.txt`). Reject
  passwords longer than 72 bytes at the API boundary (bcrypt silently truncates
  past 72 bytes, so two distinct long passwords would otherwise collide).

## Data model (SQLite)

```
users          add  password_hash TEXT
               add  created_at TEXT
               username becomes UNIQUE
               api_token becomes nullable / legacy-only
               (api_token retained only as legacy admin bootstrap, see Migration)
               NOTE: SQLite cannot drop NOT NULL/UNIQUE via ALTER TABLE; the
               api_token constraint change requires a table rebuild (see Migration).

sessions       token_hash  TEXT PRIMARY KEY
               user_id     TEXT NOT NULL
               created_at  TEXT NOT NULL
               expires_at  TEXT NOT NULL
               INDEX idx_sessions_user ON sessions(user_id)

entity_acl     entity_name TEXT NOT NULL
               user_id     TEXT NOT NULL
               permission  TEXT NOT NULL   -- 'read' | 'write'
               PRIMARY KEY (entity_name, user_id)
               INDEX idx_entity_acl_user ON entity_acl(user_id)
               entity_name is normalized and non-blank

general_documents  add  uploaded_by TEXT DEFAULT ''   -- audit only
               add  INDEX idx_general_documents_entity
                       ON general_documents(entity_name)
                   (the new get_allowed_document_ids filters on this column;
                    without the index every non-admin request is a full scan)

document_acl   retired: stop using; migration backfills entity_acl from it.
```

### ACL & entity aliases

ACL checks operate on the **literal normalized `entity_name`** stored on
`general_documents` — there is **no alias expansion** in `has_permission` or
`get_allowed_document_ids`. This matches how retrieval actually filters today:
`entity_confirm_node` (`rag/query/entity_confirm.py`) maps query text to a
*canonical* entity name via the alias map, then `search.py` builds
`entity_name == "<canonical>"` — a document whose stored `entity_name` is an
alias value is **not** matched either. Keeping ACL on the literal value
preserves that same property instead of inventing a broader access semantic
for ACL only.

Consequence: a grant on canonical `远景能源` does not cover a document stored
under the alias `远景`. This is a known data-hygiene gap shared with retrieval,
mitigated at the write side rather than at the ACL read side:

- On **upload** and **rename**, normalize `entity_name` (`strip()`), then if the
  resulting value matches an **unambiguous** alias in `entity_aliases`
  (exactly one canonical), canonicalize to that canonical name before storing.
  Ambiguous aliases (≥2 canonicals) or unknown values are stored as-is — never
  guess.
- The normalize+canonicalize logic is shared by upload, rename, and migration,
  so it lives in a single helper (`core/entity.py` — a small shared entity
  utility alongside the existing `entity_aliases` / `entity_cache` modules), not
  duplicated inside `documents.py` or `database.py`.
- During **migration**, scan `general_documents.entity_name` for values that
  match an alias but not a canonical, and include them in the startup report:
  `(entity_name, is_alias, canonical(s), document_count)`. Ambiguous cases are
  flagged for admin resolution. Unambiguous alias-stored docs are canonicalized
  in the migration pass.

Explicit alias expansion inside ACL checks is a possible future behavior delta,
explicitly out of scope for this MVP.

## Backend changes

### `core/auth.py` (rework around `entity_acl`)
- `lookup_user(token)` → if token matches `.env API_TOKEN`, return bootstrap
  admin; otherwise hash token, join `sessions`, reject expired, maybe
  throttled-renew, and return `CurrentUser`.
- `get_allowed_document_ids(user)` → `None` for admin; else
  `SELECT document_id FROM general_documents WHERE entity_name IN (<granted entities>)`.
  **Signature unchanged** so retrieval/query filtering
  (`api/query_chat.py`, `api/retrieval_test.py`) is untouched. Backed by
  `idx_general_documents_entity`. No alias expansion (see "ACL & entity aliases").
- `has_permission(user, document_id, min_permission, entity_name=None)` →
  resolve the document's `entity_name` (or accept it as an optional arg so
  routes that already fetched the document — most of them — avoid a second
  query), check `entity_acl` on the literal value. `read` satisfied by
  `read|write`; `write` requires `write`. Admin always true. (Existing
  `'owner'` callers in `api/documents.py` become `'write'`.)
- New: `user_entities(user, min_permission='read')`, `can_write_entity(user, entity_name)`.
  Both compare against the literal normalized `entity_name`; no alias expansion.
- New: `normalize_entity_name(entity_name)`, `grant_entity(entity_name, user_id, permission)`,
  `revoke_entity(entity_name, user_id)` (replace `grant_permission` /
  `remove_document_acl`). `grant_entity` rejects blank names, unknown users, and
  invalid permissions.
- New: `hash_password`, `verify_password`, `create_session(user_id)`,
  `hash_session_token`, `delete_session(token)`, `touch_session(token)`
  (throttled sliding renew).
- Add `purge_expired_sessions()` helper and call it once per successful login
  (`DELETE FROM sessions WHERE expires_at < now`) so expired rows do not
  accumulate; logout and sliding renew remain the only other delete/rewrite paths.
- Keep `core.auth.require_admin(user)` as the pure checker (raise 403 if not
  admin). Do **not** turn it into a FastAPI dependency here — that would require
  importing `verify_token` from `deps.py`, which already imports `core.auth`,
  creating a cycle. Instead add an API-layer dependency in `deps.py`:
  `async def require_admin_user(current_user: CurrentUser = Depends(verify_token)) -> CurrentUser`
  that calls `require_admin(current_user)` and returns `current_user`. All
  admin routes (new and existing) use `Depends(require_admin_user)`, replacing
  the current inline `if current_user.role != "admin": raise HTTPException(403)`
  pattern.

### New `api/auth.py`
- `POST /auth/login` — `{username, password}` → `{token, user, expires_at}` on
  success (include `expires_at` so the frontend can warn on impending expiry);
  401 on failure. On success, call `purge_expired_sessions()` for that user.
- `POST /auth/logout` — deletes the current session.
- `GET /me` — unchanged (moves here or stays in `auth_me.py`).

### New `api/admin_users.py` (admin-only)
- `POST /admin/users` — create user `{username, password, role}`.
  `username` is unique; duplicate usernames return 409. Enforce a minimum
  password length of 8 at this boundary (admin-provisioned, so no complexity
  rules, but a floor prevents empty/trivial passwords).
- `GET /admin/users` — list users.
- `POST /admin/users/{user_id}/reset-password` — set a new password and delete
  that user's existing sessions.
- `DELETE /admin/users/{user_id}` — delete user (and their sessions + grants).
  Reject deleting the last admin and reject deleting the bootstrap admin user.
- `GET /admin/entities` — list known non-blank entity names (distinct
  `general_documents.entity_name` ∪ `entity_acl.entity_name`, normalized).
- `POST /admin/acl/grant` — `{entity_name, user_id, permission}` (creates entity on first grant).
- `POST /admin/acl/revoke` — `{entity_name, user_id}`.

**Bootstrap admin identity (pinned):** the `.env API_TOKEN` always resolves to
exactly one row — the row whose `user_id` equals the settings key
`bootstrap_admin_user_id` (seeded to `u_admin` at migration). `DELETE
/admin/users/{user_id}` rejects that `user_id` unconditionally. This stays
deterministic even if more admins are created via `POST /admin/users`.

### `api/documents.py`
- Upload: normalize `entity_name` (`strip()`), then canonicalize if it matches
  an unambiguous alias (see "ACL & entity aliases"); validate result ∈ caller's
  `write` entities (admin: any); set `uploaded_by = current_user.user_id`; drop
  the per-doc owner grant.
- Entity rename / metadata edit: require write on the current document and, for
  non-admins, `can_write_entity(user, new_entity_name)` before moving a document
  into another entity. The target is normalized + canonicalized the same way as
  upload. Blank target entity is rejected. Admin may move to any non-blank entity.
- Write-gated ops (delete / reprocess): `has_permission(..., 'write')`.
- Read-gated ops and list: unchanged in shape (`get_allowed_document_ids` /
  `has_permission(..., 'read')`).
- Retire `POST /documents/{document_id}/grant`: remove it or return 410. Entity
  grants are handled only through `POST /admin/acl/grant`.
- **Asset access** (`_verify_asset_access`, `documents.py:350`): the `?token=`
  query-param path stays (needed for `<img>` src rendering that cannot set
  headers) and routes through the new `lookup_user`. Sliding renewal does **not**
  invalidate the token (it updates `expires_at` on the same `token_hash` row; the
  raw token the client holds is unchanged), so embedded URLs only go stale on
  real expiry (7 days) or logout — clients already reload on 401 via `client.ts`,
  and the response interceptor clears the stored token, so the user simply
  re-logs in. A non-expiring signed-URL scheme is out of scope for MVP.

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
- Retire `POST /settings/token` from the UI and normal operator flow. The
  bootstrap `API_TOKEN` remains env-only lockout recovery, is not a session,
  is not affected by logout, and should not be rotated through the app UI.
  The backend route is removed or returns 410 so there is no app-mediated
  bootstrap-token rotation path.
- **Remove the demo-token switcher** in `components/layout/AppLayout.vue`
  (`DEMO_TOKENS` + `switchUser()` + the `<a-select>` user picker). It writes
  hardcoded raw tokens to `localStorage` and reloads — a parallel auth path
  that would bypass the new login flow. The login view replaces it.

## Migration / seeding

On startup, idempotently (matching the existing migration style in
`core/database.py`):
- Add `users.password_hash`, `users.created_at`, `general_documents.uploaded_by`;
  add `idx_general_documents_entity` on `general_documents(entity_name)`.
- **Migrate `users.api_token` via table rebuild.** SQLite cannot drop `NOT NULL`
  or `UNIQUE` from an existing column with `ALTER TABLE`, so do a controlled
  rebuild: create `users_new` with the target shape (`api_token TEXT` nullable,
  non-unique; `username TEXT UNIQUE`; `password_hash TEXT`; `created_at TEXT`),
  copy rows across (`api_token` carried as-is for the bootstrap admin, `NULL` or
  `''` for others), `DROP TABLE users`, `ALTER TABLE users_new RENAME TO users`,
  recreate indexes. Wrap in a transaction and log the row count. The only
  meaningful raw token after migration is `.env API_TOKEN`.
  **Sequencing:** no table in the current schema declares `FOREIGN KEY`
  constraints (so `PRAGMA foreign_keys=ON` is effectively a no-op today), but
  perform the `users` rebuild **before** creating `sessions` and `entity_acl`,
  and keep the rebuild inside its own transaction. This is defensive: if FK
  constraints are added later, a rebuild of a referenced parent table under
  `foreign_keys=ON` would fail or orphan rows. Doing the rebuild first keeps the
  migration forward-safe at zero cost.
- **Refactor the seed loop** (`database.py:375-387`). Today it runs on every
  startup and force-overwrites `users.api_token` from `.env API_TOKEN` via
  `ON CONFLICT(user_id) DO UPDATE SET api_token = excluded.api_token`. After
  migration it must stop writing `api_token` (the column is legacy and the
  bootstrap bypass lives in `lookup_user`), and must not clobber
  password-created users. Seed only `password_hash` / `role` for the demo users,
  idempotently, and only on first run (e.g. `INSERT OR IGNORE` keyed on `user_id`).
- Set the settings key `bootstrap_admin_user_id = 'u_admin'` so the bootstrap
  bypass and the delete-protection rule resolve deterministically.
- Normalize existing `general_documents.entity_name` (`strip()`), then
  canonicalize values that match an **unambiguous** alias in `entity_aliases`
  (rewrite to the single canonical). Leave ambiguous alias matches and unknown
  values as-is. Emit a report section listing `(entity_name, is_alias,
  canonical(s), document_count)` so the admin can see what was canonicalized
  and resolve ambiguous cases manually. This makes the stored column match the
  canonicalization that upload/rename will apply going forward, so `entity_acl`
  grants on canonical names line up with stored values.
- Enforce unique usernames (covered by the rebuild's `username UNIQUE`). If an
  existing DB has duplicate usernames, fail migration with a clear operator
  message instead of guessing which account login should target — detect this
  *before* the rebuild and abort.
- Create `sessions`, `entity_acl`.
- Backfill `entity_acl` from `document_acl` (map each doc grant to its
  document's normalized non-blank `entity_name`; `owner → write`, `read → read`).
  This intentionally broadens access from per-document to per-entity: a grant
  on one document now grants the same tier on all documents in that entity.
  If multiple document grants collapse to the same `(entity_name, user_id)`,
  `write` wins over `read` deterministically.
  Emit a startup migration report listing `(user_id, entity_name, permission,
  source_document_count, total_entity_document_count)` so the admin can audit
  the broadened grants. Skip blank entity names during backfill, and surface
  in the report the count of documents left at a blank `entity_name` — these
  become admin-only (no grant possible on blank) until an admin moves them to
  a non-blank entity. That is the operator remedy and should be stated plainly.
- Seed demo users **with passwords**: Alice/Bob = `write` on the demo entity
  (e.g. `远景能源`), Admin = role `admin`. Document the demo passwords in the
  demo guide.
- Keep `.env` `API_TOKEN` as an admin **bootstrap** credential: `lookup_user`
  accepts it directly (bypassing the `sessions` table) and resolves to the
  bootstrap admin row (see `bootstrap_admin_user_id` above), so the operator is
  never locked out even with no valid session. This credential is env-managed
  only; deleting sessions or logging out does not invalidate it.

## Testing

- Unit: `hash_password`/`verify_password`; `create_session`/expiry/`lookup_user`;
  `get_allowed_document_ids` and `has_permission` across entity grants
  (read vs write vs none vs admin); upload entity-write validation including the
  escalation case (write-user uploading into an unauthorized entity → rejected);
  entity rename target validation; blank entity rejection; duplicate username
  rejection; session token hash lookup; throttled renewal; over-72-byte password
  rejection; **sub-8-byte password rejection**; empty-grant user →
  `get_allowed_document_ids` returns `[]` and consumers treat `[]` as
  "see nothing" (never "no filter"); **`purge_expired_sessions()` deletes only
  rows with `expires_at < now`**.
- **Canonicalization (no ACL alias expansion)**: unit-test that upload/rename
  with an `entity_name` matching an unambiguous alias rewrites to the canonical
  before storing; that an ambiguous alias (≥2 canonicals) and an unknown value
  are stored as-is; and that `get_allowed_document_ids` / `has_permission` use
  the literal stored value (a grant on canonical `远景能源` does **not** cover a
  doc still stored under alias `远景`). This pins the design choice that ACL
  matches retrieval's literal-`entity_name` behavior rather than expanding
  aliases at read time.
- API: login success/failure, logout invalidates, expired session → 401, admin
  user CRUD, grant/revoke, non-admin blocked from admin endpoints,
  reset-password invalidates that user's sessions, last-admin and
  bootstrap-admin delete rejected.
- Update existing ACL tests from per-document to per-entity.
- **Remove** `tests/unit/test_security_regressions.py` cases covering
  `_update_env_file` and the 512-char `TokenUpdate` limit — that route is
  retired. Keep any non-token cases in the same file.

## Out of scope (explicit)

Per-document ownership inside a shared entity; delegated granting (write-users
inviting others); password-reset email; rate-limiting / account lockout;
SSO / 2FA.

## Implementation checklist

Ordered so each step leaves the app runnable. Backend before frontend.

### 1. Schema & migration (`core/database.py`)
- [ ] Add `bcrypt` to `backend/requirements.txt`.
- [ ] Add columns: `users.password_hash`, `users.created_at`,
      `general_documents.uploaded_by`; add `idx_general_documents_entity`.
- [ ] Detect duplicate usernames *before* rebuild; abort with a clear message.
- [ ] Rebuild `users` table: `users_new` (`api_token` nullable/non-unique,
      `username UNIQUE`, `password_hash`, `created_at`) → copy → drop → rename →
      reindex, in its own transaction. **Perform this rebuild before creating
      `sessions`/`entity_acl`** (defensive against future FK constraints).
- [ ] Refactor the demo seed loop: stop writing `api_token`; seed
      `password_hash`/`role` idempotently (`INSERT OR IGNORE` on `user_id`).
- [ ] Seed settings key `bootstrap_admin_user_id = 'u_admin'`.
- [ ] Create `sessions(token_hash, user_id, created_at, expires_at)` + user index.
- [ ] Create `entity_acl(entity_name, user_id, permission)` + user index.
- [ ] Normalize existing `general_documents.entity_name` (`strip()`), then
      canonicalize unambiguous-alias values to their single canonical; leave
      ambiguous/unknown as-is; emit the alias report section.
- [ ] Backfill `entity_acl` from `document_acl` (`owner→write`, `read→read`,
      write wins on conflicts, skip blank entities); emit the broadening report
      including the count of blank-entity docs left admin-only.
- [ ] Seed demo users with `password_hash` (Alice/Bob `write` on demo entity,
      Admin role `admin`); keep `.env API_TOKEN` bootstrap.

### 2. Auth core (`core/auth.py`)
- [ ] `hash_password` / `verify_password` (reject >72 bytes).
- [ ] `hash_session_token`, `create_session`, `delete_session`,
      `touch_session` (renew only when `expires_at < now + 24h`),
      `purge_expired_sessions()`.
- [ ] `lookup_user`: bootstrap `API_TOKEN` → bootstrap admin row (by
      `bootstrap_admin_user_id`); else hash token, join `sessions`, reject
      expired, throttled-renew.
- [ ] `normalize_entity_name`; `grant_entity` / `revoke_entity` (reject blank
      names, unknown users, bad permission).
- [ ] `user_entities(user, min='read')`, `can_write_entity` — literal
      `entity_name` comparison only, **no alias expansion**.
- [ ] Rewrite `get_allowed_document_ids` (entity-based on literal value; `[]`
      for no grants) and `has_permission(..., entity_name=None)` (resolve doc
      entity → literal `entity_acl`; `'owner'`→`'write'`).
- [ ] Delete `grant_permission` / `remove_document_acl` (or thin-wrap).
- [ ] Keep `core.auth.require_admin(user)` as the pure checker. Add the
      API-layer dependency `deps.require_admin_user(current_user =
      Depends(verify_token))` in `deps.py` (NOT in `core/auth.py` — avoids the
      import cycle since `deps.py` already imports `core.auth`). Admin routes
      use `Depends(require_admin_user)`.

### 3. API endpoints
- [ ] `api/auth.py`: `POST /auth/login` (returns `token, user, expires_at`;
      calls `purge_expired_sessions()` on success), `POST /auth/logout`, `GET /me`.
- [ ] `api/admin_users.py` (admin-only via `Depends(require_admin_user)`): user
      CRUD (min password length 8; 409 on duplicate username) + reset-password
      (deletes the user's sessions); reject deleting the last admin and the
      `bootstrap_admin_user_id` row; `GET /admin/entities`, ACL grant/revoke.
- [ ] `api/documents.py`: upload normalizes+canonicalizes `entity_name`
      (unambiguous alias → canonical), validates write on result, sets
      `uploaded_by`, drops owner grant; rename/move canonicalizes and validates
      write on target entity; delete/reprocess → `has_permission(..., 'write')`;
      `_verify_asset_access` continues via the new `lookup_user`.
- [ ] Retire `POST /documents/{document_id}/grant` (remove or 410).
- [ ] Retire backend `POST /settings/token` (remove or 410); bootstrap token is
      env-only.
- [ ] Register new routers; retire `admin_acl.py` audit route (or repoint UI).

### 4. Frontend
- [ ] Login view + route guard (redirect on no token / 401).
- [ ] `stores/auth.ts`: `login()`, `logout()`.
- [ ] Replace `AclAuditView.vue` with managed Access view (users + entity grants).
- [ ] Retire `TokenSettingsPanel.vue` and the `/settings/token` UI path.
- [ ] Remove `AppLayout.vue` demo-token switcher (`DEMO_TOKENS` / `switchUser` /
      `<a-select>` picker).

### 5. Tests
- [ ] Unit: password hash/verify (+>72B reject, sub-8 reject), session
      create/expire/lookup/throttled-renew, `purge_expired_sessions`,
      entity `has_permission` & `get_allowed_document_ids`
      (read/write/none/admin), `[]`-means-nothing consumer check, upload
      escalation reject, rename-target reject, blank-entity reject, duplicate
      username reject, canonicalization on upload/rename (unambiguous alias →
      canonical stored; ambiguous/unknown stored as-is), and no-alias-expansion
      at ACL read time (grant on canonical does not match doc stored under
      alias).
- [ ] API: login ok/fail, logout invalidates, expired→401, admin CRUD,
      reset-password invalidates sessions, last/bootstrap admin delete rejected,
      grant/revoke, retired document-grant/token-rotation endpoints, non-admin
      blocked from admin routes.
- [ ] Update existing per-document ACL tests to per-entity.
- [ ] Remove `_update_env_file` / `TokenUpdate` cases in
      `test_security_regressions.py` (route retired); keep non-token cases.
