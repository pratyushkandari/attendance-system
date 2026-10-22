# Security Architecture & Threat Model

**Platform:** VisionAttend Biometric & Cryptographic Attendance Gateway  
**Reference Standards:** NIST SP 800-63B (password length/blocklist guidance), ISO/IEC 30107-3 (presentation-attack terminology), OWASP Top 10. These are design references; the system has not been certified or independently tested against them.  

---

## 1. STRIDE Threat Analysis Matrix

| Threat Category | Potential Attack Vector | Applied Engineering Mitigation | Verification Mechanism |
| :--- | :--- | :--- | :--- |
| **Spoofing (S)** | Presentation Attack: Holding a printed photo to the kiosk camera. | Client-side, per-face eye-region contrast-variance blink detection; no time-based bypass. | Verified in a browser run with a static photo as the webcam (not marked) vs. a clip with a blink (marked). |
| **Spoofing (S)** | Identity Forgery: Attacker submits another student's roll number over mobile check-in. | Live HMAC QR token required (30–35 s window) plus roll existence check. A student who is in the room can still type a friend's roll number; the QR channel does not authenticate the student. | `POST /verify_student`, `GET /get_student` & `POST /mark_attendance` validate the token before any lookup or DB commit. |
| **Tampering (T)** | Payload Modification: Altering roll number or timestamp in forwarded QR token. | Cryptographic HMAC-SHA256 signature calculated over timestamped payload with master key. | Tampered tokens fail signature verification with `BadSignature` (`400 Bad Request`). |
| **Repudiation (R)** | Student denies check-in or claims fraudulent attendance marking. | Immutable timestamped audit ledger recording verification channel (`Face` vs `QR`). | PostgreSQL indexed logs with UTC+5:30 timestamps and admin audit export. |
| **Information Disclosure (I)** | Unauthorized extraction of biometric vectors or student rosters. | Mandatory `@admin_required` guard on `/records`, `/dashboard_data`, and face APIs; phone-facing student lookups require a live QR token. | Unauthenticated requests rejected with `401 Unauthorized`. |
| **Denial of Service (D)** | Automated brute-force credential stuffing against administrative portal. | Failed-login counter in `SafeCacheStore` (shared via Redis when configured): `LOCKOUT_THRESHOLD` (3) failures trigger a `LOCKOUT_DURATION_SECONDS` (15 min) lockout. | Lockout tests in `tests/test_auth.py`. |
| **Elevation of Privilege (E)** | Creating unauthorized administrator accounts after system bootstrap. | Anonymous `/register_admin` is accepted only while no admin exists; afterwards an authenticated admin is required (`ALLOW_PUBLIC_ADMIN_SIGNUP=true` reopens it for demos). | `test_register_admin_*` tests in `tests/test_auth.py`. |
| **Tampering (T)** | Cross-site request forgery against cookie-authenticated endpoints (e.g. `/clear_records`). | Session cookie is `HttpOnly` and `SameSite=Lax`, so browsers do not attach it to cross-site POSTs. | `test_session_cookie_is_httponly_and_samesite_lax`. |

---

## 2. Biometric Anti-Spoofing & Liveness (ISO/IEC 30107-3)

### 2.1 Attack Scenarios & Mitigations
* **Scenario A: 2D Paper Presentation Attack**
  * *Vulnerability:* Attacker presents high-resolution printed portrait of an enrolled student.
  * *Mitigation:* For each recognised face, the kiosk samples variance across the eye-band region ($y + 0.18h, w \times 0.76$). Static paper exhibits flat variance over time, so the face is never marked unless its own eyelid dip and recovery ($40\text{ms} - 1200\text{ms}$) is observed. Liveness state is per face, so a real person blinking next to a photo does not verify the photo.
* **Scenario B: Video Replay Attack (iPad / Smartphone Display)**
  * *Vulnerability:* Attacker replays recorded video of student blinking on tablet screen.
  * *Status:* **Not mitigated.** A blinking face on a screen produces the same variance pattern. The low-light check (`mean(gray) < 35`) only triggers the QR fallback prompt; it is not a screen-replay detector.

---

## 3. Cryptographic Standards & Key Management

### 3.1 Password Storage & Derivation
* **Algorithm:** `scrypt` key derivation function with parameters:
  $$N = 32768, \quad r = 8, \quad p = 1, \quad \text{Salt Length} = 16 \text{ bytes}$$
* Per-password random salts defeat rainbow tables, and scrypt's memory-hardness makes GPU/ASIC dictionary attacks expensive (not impossible).
* Plaintext passwords are never written to the database or logs.
* **Policy:** 8–128 characters, a small blocklist, and no email-handle substring (per NIST 800-63B), plus upper/lower/digit/symbol composition rules. NIST 800-63B does not require composition rules; they are kept as an institutional policy choice.

### 3.2 Dynamic QR Signing (HMAC-SHA256)
* Signed using `itsdangerous.URLSafeTimedSerializer` with salt `qr-attendance-token`.
* Carries cryptographic timestamp; the kiosk rotates codes every 5 s, `/verify_qr_token` rejects tokens older than 30 s and the student lookup / `/mark_attendance` endpoints reject tokens older than 35 s (`SignatureExpired`).
* Nonce entropy: 12-character hex (48-bit pseudo-random string), eliminating token prediction attacks.

### 3.3 JWT Tokens
* Format: Standard RFC 7519 JSON Web Token signed with HS256.
* 24-hour expiration window; tampered signatures immediately rejected by PyJWT parser.
* There is no revocation list: a leaked token stays valid until it expires, and logging out clears only the browser session cookie.

### 3.4 Secret Management
* `SECRET_KEY` signs session cookies, JWTs and QR tokens. If it is not set, a hard-coded development default is used and the app logs a warning at startup; every deployment must set its own random value.

---

## 4. Known Limitations

* **QR forwarding window:** a QR token can be reused by anyone for up to 35 seconds, so a student can still forward a fresh code (or type an absent friend's roll number) within that window.
* **Client-side liveness:** blink detection runs in the kiosk browser; the server trusts authenticated kiosk sessions. Video replays of a blinking face are not detected.
* **Third-party QR rendering:** the classroom QR image is generated by `api.qrserver.com`, so short-lived check-in URLs are sent to that service.
* **One attendance per day:** enforced by an application-level check, not a database unique constraint.
* **In-memory state per process:** without `REDIS_URL`, lockout counters are per Gunicorn worker/pod; kiosk tracker state is always per process.

---

## 5. Vulnerability Disclosure Policy

If you identify a security vulnerability in this project:
1. Do not file a public GitHub issue.
2. Email detailed reproduction steps to: `pratyushkandari@gmail.com`.
3. Include proof-of-concept payload and affected endpoints.
4. Security patches are prioritized and released within 48 hours of verification.
