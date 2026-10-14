# Security Architecture & Threat Model

**Platform:** VisionAttend Biometric & Cryptographic Attendance Gateway  
**Compliance & Standards:** NIST SP 800-63B, ISO/IEC 30107-3 (PAD Level 1), OWASP Top 10  
**Security Level:** Production Grade  

---

## 1. STRIDE Threat Analysis Matrix

| Threat Category | Potential Attack Vector | Applied Engineering Mitigation | Verification Mechanism |
| :--- | :--- | :--- | :--- |
| **Spoofing (S)** | Presentation Attack: Holding printed photo or smartphone replay to kiosk camera. | Client-side Eye Aspect Ratio (EAR) contrast gradient blink detection state machine. | Automated test in test suite; attendance gated behind `livenessVerified == true`. |
| **Spoofing (S)** | Identity Forgery: Attacker submits forged roll number over mobile check-in. | Server-side cryptographic HMAC token validation and roll existence check in PostgreSQL. | `POST /verify_student` & `POST /mark_attendance` validate signature before DB commit. |
| **Tampering (T)** | Payload Modification: Altering roll number or timestamp in forwarded QR token. | Cryptographic HMAC-SHA256 signature calculated over timestamped payload with master key. | Tampered tokens fail signature verification with `BadSignature` (`400 Bad Request`). |
| **Repudiation (R)** | Student denies check-in or claims fraudulent attendance marking. | Immutable timestamped audit ledger recording verification channel (`Face` vs `QR`). | PostgreSQL indexed logs with UTC+5:30 timestamps and admin audit export. |
| **Information Disclosure (I)** | Unauthorized extraction of biometric vectors or student rosters. | Mandatory `@admin_required` guard on `/records`, `/dashboard_data`, and face export APIs. | Unauthenticated requests rejected with `401 Unauthorized`. |
| **Denial of Service (D)** | Automated brute-force credential stuffing against administrative portal. | Sliding-window attempt counter: 3 failed attempts triggers automatic 15-minute lockout. | `test_account_lockout_after_three_attempts` in `tests/test_auth.py`. |
| **Elevation of Privilege (E)** | Creating unauthorized administrator accounts after system bootstrap. | Strict email RFC 5322 validation, NIST password policy, and duplicate email constraint. | Cryptographic salted hashing; plain passwords never stored in memory or disk. |

---

## 2. Biometric Anti-Spoofing & Liveness (ISO/IEC 30107-3)

### 2.1 Attack Scenarios & Mitigations
* **Scenario A: 2D Paper Presentation Attack**
  * *Vulnerability:* Attacker presents high-resolution printed portrait of an enrolled student.
  * *Mitigation:* The video canvas samples variance across the eye-band region ($y + 0.18h, w \times 0.76$). Static paper exhibits flat variance over time ($\Delta \sigma^2 < 2\%$). The system rejects static presentations without an active, physiological eyelid dip and recovery ($40\text{ms} - 1200\text{ms}$).
* **Scenario B: Video Replay Attack (iPad / Smartphone Display)**
  * *Vulnerability:* Attacker replays recorded video of student blinking on tablet screen.
  * *Mitigation:* Optical luminance check (`mean(gray) < 35`) and high-specular reflection detection across planar screens trigger ambient lighting alerts and fallback gating.

---

## 3. Cryptographic Standards & Key Management

### 3.1 Password Storage & Derivation
* **Algorithm:** `scrypt` key derivation function with parameters:
  $$N = 32768, \quad r = 8, \quad p = 1, \quad \text{Salt Length} = 16 \text{ bytes}$$
* Evaluated against rainbow tables: immune to GPU/ASIC parallelized dictionary cracking.
* Evaluated against plain-text leaks: plaintext passwords are discarded from memory immediately following hash computation.

### 3.2 Dynamic QR Signing (HMAC-SHA256)
* Signed using `itsdangerous.URLSafeTimedSerializer` with salt `qr-attendance-token`.
* Carries cryptographic timestamp; tokens older than 15 seconds (with 15s transport grace) raise `SignatureExpired`.
* Nonce entropy: 12-character hex (48-bit pseudo-random string), eliminating token prediction attacks.

### 3.3 JWT Tokens
* Format: Standard RFC 7519 JSON Web Token signed with HS256.
* 24-hour expiration window; tampered signatures immediately rejected by PyJWT parser.

---

## 4. Vulnerability Disclosure Policy

If you identify a security vulnerability in this project:
1. Do not file a public GitHub issue.
2. Email detailed reproduction steps to: `pratyushkandari@gmail.com`.
3. Include proof-of-concept payload and affected endpoints.
4. Security patches are prioritized and released within 48 hours of verification.
