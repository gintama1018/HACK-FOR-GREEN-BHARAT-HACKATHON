# Security Policy — InfraWatch Nexus

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.0.x   | ✅ Active          |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT** open a public GitHub issue.
2. Email the maintainer directly with details of the vulnerability.
3. Include steps to reproduce, expected vs. actual behavior, and impact assessment.

We will acknowledge receipt within 48 hours and provide a fix timeline within 7 days.

---

## Authentication & Authorization

### Admin Token
- All admin-level endpoints (`/api/report/road-issue`, `/api/van/collection`, `/api/demo/simulate-crisis`) require a `Bearer` token via the `Authorization` header.
- The token is configured via the `ADMIN_TOKEN` environment variable.
- **Never hardcode tokens in source code.** Use environment variables or a secrets manager.
- Default token (`INFRAWATCH_ADMIN_2026`) is for development only. **Change it in production.**

### API Keys
- `GEMINI_API_KEY` and `WX_API_KEY` are stored as environment variables, never committed to version control.
- The `.env` file is listed in `.gitignore` to prevent accidental exposure.

---

## CORS Policy

The FastAPI server uses `CORSMiddleware` with the following configuration:
- **Origins:** `*` (all origins allowed) — suitable for hackathon demo. In production, restrict to specific domains.
- **Methods:** All HTTP methods allowed.
- **Headers:** All headers allowed.

**Production Recommendation:** Replace `allow_origins=["*"]` with an explicit allowlist:
```python
allow_origins=["https://yourdomain.com", "https://admin.yourdomain.com"]
```

---

## Rate Limiting

Currently, rate limiting is handled at the platform level (Render.com).

**Production Recommendation:** Add application-level rate limiting using `slowapi` or similar:
- Citizen photo uploads: **10 requests/minute** per IP
- Admin endpoints: **30 requests/minute** per token
- WebSocket connections: **5 concurrent** per IP

---

## Data Protection

- **No PII is collected.** The system only processes infrastructure photos and municipal asset IDs.
- **Uploaded images** are processed in-memory via the Gemini API and are **not stored** on the server filesystem.
- **Event data** (waste reports, road issues) contains only asset IDs, timestamps, and severity scores — no personal information.

---

## Dependency Security

- Dependencies are pinned in `requirements.txt`.
- GitHub Actions CI runs on every push to detect syntax errors and test failures.
- **Production Recommendation:** Add `pip-audit` or `safety` to the CI pipeline to scan for known vulnerabilities in dependencies.

---

## WebSocket Security

- In production, all WebSocket connections use `wss://` (TLS-encrypted).
- The frontend dynamically detects `https` and upgrades to `wss` automatically.
- WebSocket connections are read-only broadcasts — clients cannot inject data through the WebSocket channel.

---

## Infrastructure Security (Render.com)

- The application runs inside an isolated Docker container.
- Environment variables (API keys, tokens) are stored in Render's encrypted secrets manager.
- HTTPS is enforced by default on all Render web services.
- No SSH access is exposed.
