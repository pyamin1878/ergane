# Authentication & Session Management Design

**Date:** 2026-02-23
**Status:** Approved
**Depends on:** JS rendering (Playwright integration)

## Problem

Ergane cannot scrape content behind authentication. Users hitting login walls have no path forward — the existing `AuthHeaderHook` handles static headers but not interactive login flows. Modern sites use form-based login, OAuth/SSO redirects, 2FA, and CAPTCHAs, all of which require a real browser.

## Decision

**Playwright-first auth.** All login flows run through a Playwright browser instance. After login, cookies are extracted and injected into the httpx `AsyncClient` for crawling. The browser is only used for login — the crawl itself stays on httpx (fast, lightweight).

Two modes:
- **auto:** Headless Playwright fills form selectors and submits programmatically.
- **manual:** Visible browser window; user logs in interactively (handles 2FA, CAPTCHA, SSO). Ergane captures cookies when the user signals completion.

Sessions persist to an encrypted file with a staleness check on reload.

## YAML Configuration

```yaml
auth:
  login_url: "https://example.com/login"
  mode: auto  # "auto" | "manual"

  # Selectors for automated login (mode: auto)
  username_selector: "input[name='email']"
  password_selector: "input[name='password']"
  submit_selector: "button[type='submit']"

  # Credentials (env var interpolation supported)
  username: "${AUTH_USERNAME}"
  password: "${AUTH_PASSWORD}"

  # Session validation
  check_url: "https://example.com/dashboard"
  session_file: ".ergane_session.json"
  session_ttl: 3600

  # Wait condition after login (for SPAs)
  wait_after_login: "networkidle"  # or CSS selector like "#dashboard"
```

Credentials support `${VAR}` interpolation so secrets stay in environment variables.

## Architecture

```
ergane/auth/
├── __init__.py          # re-exports AuthManager
├── manager.py           # AuthManager — orchestrates login flow
├── session_store.py     # SessionStore — encrypted cookie persistence
└── config.py            # AuthConfig — Pydantic model for YAML auth section
```

### AuthConfig

Pydantic model validating the `auth:` YAML section. Parsed during `CrawlOptions.from_sources()`. Env var interpolation resolves `${VAR}` to actual values at parse time.

### SessionStore

- Saves/loads cookies as JSON to `session_file` path.
- Encrypts at rest using `cryptography.Fernet` with a key derived from a user-provided passphrase or a machine-local fallback.
- Tracks `saved_at` timestamp; respects `session_ttl`.
- `is_valid(check_url)` makes an httpx GET with saved cookies, returns True on 2xx.

### AuthManager

Entry point called by `Engine` before crawling starts:

1. Load saved session from `SessionStore`.
2. If session exists and `is_valid()` — inject cookies into httpx client, done.
3. If stale or missing — run login flow:
   - `auto`: headless Playwright navigates to `login_url`, fills selectors, clicks submit, waits for `wait_after_login`.
   - `manual`: visible Playwright navigates to `login_url`, prompts user to log in and press Enter, captures cookies.
4. Extract cookies from Playwright browser context.
5. Save to `SessionStore`.
6. Inject cookies into httpx client.
7. Close Playwright browser.

## Data Flow

```
  ergane.yaml auth
        │
        ▼
    AuthConfig          (validate + resolve env vars)
        │
        ▼
   AuthManager
    ├── saved session valid?  ──yes──▶  inject cookies ──▶ httpx client
    │                                                          │
    └── no ──▶ Playwright Login ──▶ extract cookies            ▼
                     │                     │              Engine crawl
                     ▼                     ▼              (no Playwright)
              SessionStore ◀──── save encrypted
```

Playwright is only used for login. The crawl runs entirely through httpx.

Cookie injection: `client.cookies.update(cookie_dict)` with domain, path, secure, and expiry metadata.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| No `auth` section in YAML | AuthManager is a no-op. Crawl proceeds unauthenticated. |
| `login_url` unreachable | `AuthenticationError` with clear message. Crawl does not start. |
| Auto-login selectors don't match | `AuthenticationError("Selector not found: {selector}")`. |
| Login succeeds but `check_url` returns 403 | `AuthenticationError("Login succeeded but session validation failed")`. |
| Session file corrupt/unreadable | Log warning, delete stale file, re-login. |
| Decryption key wrong | `AuthenticationError("Cannot decrypt session file")`. |
| Playwright not installed | `AuthenticationError("Auth requires playwright. Install: uv pip install ergane[js]")`. |
| Manual mode: user closes browser | `AuthenticationError("Browser closed before login completed")`. |
| Network timeout during login | Respects existing `timeout` config. |

`AuthenticationError(ErganeError)` is raised before crawling starts for immediate feedback.

## CLI Integration

- `--auth-mode manual` — override YAML `mode` to force manual login (one-off 2FA).
- `ergane auth login` — run login flow standalone, populate session file without crawling.
- `ergane auth status` — check if saved session is valid.
- `ergane auth clear` — delete saved session file.

## MCP Integration

No MCP changes. MCP tools run non-interactively; `manual` mode does not apply. MCP crawls needing auth use a pre-populated session file.

## Dependencies

- `cryptography` — added to core `[project.dependencies]` for Fernet encryption.
- `playwright` — already behind `[js]` optional extra. Auth reuses it.

## Testing Strategy

- **Unit:** AuthConfig validation, SessionStore save/load/encrypt/decrypt, env var interpolation.
- **Integration:** AuthManager against a local test server (pytest-httpserver) with a login form.
- **Mocks:** Playwright mocked in unit tests (no real browser in CI).
- **No-op path:** Verify crawl proceeds normally when no `auth` config is present.
- **Error paths:** Bad selectors, unreachable login URL, corrupt session file, missing Playwright.
