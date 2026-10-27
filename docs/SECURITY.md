# Security

## Reporting a vulnerability

Please don't open a public issue. Email **pratyushkandari@gmail.com** with the affected endpoint, steps to reproduce and, if you have one, a proof of concept. I'll reply as soon as I can.

## Threat model

| Threat | Example | Mitigation | Covered by |
| --- | --- | --- | --- |
| Photo spoofing | Holding a printed photo up to the kiosk | Each recognised face must blink before it's marked; there is no time-based bypass | Manual test: a static photo is recognised but never marked |
| Proxy check-in | Sending a photo of the classroom QR code to an absent friend | Tokens rotate every 5 s and expire after 35 s | `tests/test_crypto.py` |
| Token tampering | Editing the timestamp in a QR token | HMAC-SHA256 signature over the payload; tampered tokens fail with `400` | `tests/test_crypto.py` |
| Admin email discovery | Timing failed logins to find which emails are admins | Unknown emails are checked against a dummy scrypt hash, so both cases take the same time | `test_login_hashes_password_for_unknown_email` |
| Student data scraping | Walking through sequential roll numbers to collect names | Phone-side lookups require a live QR token; everything else requires an admin | `tests/test_attendance.py` |
| Token leakage | Live check-in URLs sent to a third-party QR service | QR codes are generated on the server with segno | `test_generate_qr_token_renders_qr_code_locally` |
| Password guessing | Brute-forcing the admin login | 3 failures lock the email for 15 minutes (shared through Redis when configured) | `tests/test_auth.py` |
| Oversized requests | Very large request bodies | Bodies over 10 MB are rejected with `413` before being read | `test_oversized_request_body_is_rejected_with_json_413` |
| Unauthorised admin accounts | Signing up as admin on a live deployment | Only the first admin can sign up anonymously; after that an admin must create accounts | `tests/test_auth.py` |
| CSRF | A cross-site form posting to `/clear_records` | Session cookie is `HttpOnly` and `SameSite=Lax`, so it isn't sent on cross-site POSTs | `test_session_cookie_is_httponly_and_samesite_lax` |

## Liveness

For each recognised face, the kiosk browser tracks the contrast across the eye region. A printed photo has flat contrast over time, so it's never marked. A real face blinking, a quick dip and recovery lasting 40 to 1200 ms, marks that face only. Someone blinking next to a photo doesn't make the photo pass.

What this doesn't stop: a video of the student blinking, played on a phone or tablet, produces the same pattern and will pass. The check also runs in the browser; the server trusts any `Face` check-in that comes from a signed-in admin.

## Passwords

- Stored as scrypt hashes (Werkzeug's `generate_password_hash`: N=32768, r=8, p=1, 16-byte salt). Plain-text passwords are never stored or logged.
- 8 to 128 characters, with at least one upper-case letter, lower-case letter, digit and symbol. A short list of common passwords and passwords containing the email's username are rejected.

## Tokens

**QR tokens.** Signed with itsdangerous `URLSafeTimedSerializer` using HMAC-SHA256 and a fixed salt. The screen rotates them every 5 seconds; `/verify_qr_token` rejects tokens older than 30 seconds, and the lookup and check-in endpoints reject tokens older than 35 seconds. The random nonce just makes each token unique. It isn't stored, so tokens aren't single-use.

**JWTs.** HS256, valid for 24 hours. There's no revocation list, so a token stays valid until it expires, even after the admin logs out.

**Session cookie.** Signed by Flask, `HttpOnly`, `SameSite=Lax`.

## Secret key

`SECRET_KEY` signs session cookies, JWTs and QR tokens. There's no default: the app refuses to start if it's empty, or if it matches a value that has been committed to this repository. Use at least 32 random bytes:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Docker Compose reads it from `.env`, Kubernetes from the `attendance-secrets` Secret, and Render from the service's environment variables. Changing it signs everyone out and invalidates all JWTs and QR tokens.

## Known limitations

- **QR window.** A token can be used by anyone for up to 35 seconds, with any roll number, so a student in the room can still check in an absent friend.
- **Client-side liveness.** Video replays aren't detected, and the server can't verify that a blink happened.
- **Lockout abuse.** Lockout is keyed by email, so anyone who knows an admin's email can lock that account for 15 minutes. There's no per-IP rate limit.
- **JWT lifetime.** Tokens can't be revoked and last 24 hours.
- **Duplicate check-ins.** One record per student per day is enforced in application code, not by a unique constraint, so two simultaneous requests could both be recorded. `/records` de-duplicates when displaying.
- **Per-process state.** Without `REDIS_URL`, lockout counters are per worker or pod. Kiosk tracker state is always per process.
- **Public metrics.** `/metrics` has no authentication.
