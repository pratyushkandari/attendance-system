# API Reference

Base URL: `http://localhost:5000` locally, `https://attendance-system-pratyush.onrender.com` for the live demo.

## Conventions

**Authentication.** Admin endpoints accept either of these:

- `Authorization: Bearer <token>`, using the token returned by `POST /login_admin`. Tokens are HS256 JWTs that expire after 24 hours, with the claims `sub` (admin email), `role`, `iat` and `exp`.
- The session cookie set by `POST /login_admin` (`HttpOnly`, `SameSite=Lax`). This is what the browser UI uses.

Without valid credentials, API clients get:

```json
{ "error": "Unauthorized. Bearer JWT token or Admin session required." }
```

with status `401` (or a more specific message for an expired or invalid JWT). A browser loading an admin page (preferred `Accept` type `text/html`) is redirected to `/` instead.

**Request bodies.** `POST` endpoints expect `Content-Type: application/json`. A missing or malformed body is treated as empty and gets the endpoint's normal `400` validation error. Bodies over 10 MB are rejected:

```json
{ "error": "Request body is too large." }
```

with status `413`.

**Lockout.** After `LOCKOUT_THRESHOLD` (default 3) failed logins for an email, that email is locked for `LOCKOUT_DURATION_SECONDS` (default 900). A successful login resets the counter.

**Time zone.** Dates and times in responses are Indian Standard Time (UTC+5:30).

---

## Authentication

### `POST /login_admin`

Signs an admin in. Returns a JWT and sets the session cookie.

```json
{ "email": "admin@institution.edu", "password": "AdminSecure@2026!" }
```

**200**

```json
{
  "status": "success",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 86400,
  "user": "admin@institution.edu"
}
```

**Errors**

- `400`: email or password missing.
- `401`: wrong credentials. The response is the same, and takes the same time, whether or not the email exists.
  ```json
  { "status": "invalid", "attempts_left": 2, "message": "Invalid credentials. 2 attempts left." }
  ```
- `403`: the email is locked.
  ```json
  { "status": "locked", "message": "Account locked due to 3 failed attempts. Try again in 15 minutes." }
  ```

### `POST /register_admin`

Creates an admin account.

**Access:** anyone, while no admin exists yet (so the first admin can sign up from the login page). After that, a signed-in admin. `ALLOW_PUBLIC_ADMIN_SIGNUP=true` opens it to everyone again.

```json
{ "email": "operator@institution.edu", "password": "AdminSecure@2026!" }
```

Password rules: 8 to 128 characters, at least one upper-case letter, one lower-case letter, one digit and one symbol. Common passwords and passwords containing the email's username are rejected.

**200**

```json
{ "status": "registered", "message": "Admin registered successfully." }
```

**Errors**

- `400` with `status` set to `weak_password`, `invalid_email` or `exists`, plus a `message`.
- `403` with `status: "forbidden"` when signup is closed.

### `GET /logout`

Clears the session cookie and redirects to the login page. Issued JWTs stay valid until they expire.

---

## Students and enrollment

### `POST /register`

Creates a student and assigns a roll number. **Access:** admin.

```json
{
  "first_name": "Alexander",
  "last_name": "Wright",
  "department": "CSE",
  "year": "2026",
  "email": "a.wright@institution.edu"
}
```

All fields are required. `year` must be four digits (string or number), `department` a 2 to 10 letter code (stored in upper case), names at most 100 characters and the email at most 120.

The roll number is the year, the department and the next sequence number for that pair, padded to three digits: `2026CSE001`, `2026CSE002`, and so on.

**200**

```json
{ "status": "success", "roll": "2026CSE042" }
```

**Errors:** `400` for a missing or invalid field, an invalid email, or an email that's already registered.

### `POST /capture_face`

Returns the embedding of the largest face in one webcam frame. The capture page calls this five times per student. **Access:** admin.

```json
{ "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg..." }
```

**200**

```json
{
  "status": "success",
  "embedding": [0.0381, -0.0192, "... 512 values ...", 0.0812],
  "box": [142, 88, 185, 210]
}
```

If the frame has no usable face, the response is still `200` but contains an `error` field, so the capture loop just moves on to the next frame. Possible values: `"no face"`, `"low confidence face"` (below `MTCNN_CONFIDENCE_THRESHOLD`), `"face too small"` (under 40 x 40 px), `"invalid face crop"` and `"embedding extraction failed"`.

**Errors**

- `400`: `{"error": "invalid or corrupt image payload"}` when `image` isn't a base64 data URL of a readable image.
- `500`: `{"error": "server error during face capture"}`.

### `POST /save_face_data`

Saves a student's face profile: the average of the submitted embeddings, scaled to unit length. Also clears the recognition cache so the student can be recognised immediately. **Access:** admin.

```json
{
  "roll": "2026CSE042",
  "embeddings": [[0.0381, -0.0192, "..."], [0.0410, -0.0185, "..."]]
}
```

`embeddings` must be a list of 1 to 20 vectors, each exactly 512 finite numbers.

**200**

```json
{ "status": "saved", "message": "Biometric face profile created for 2026CSE042." }
```

**Errors:** `400` for invalid embeddings, `404` for an unknown roll number.

### `POST /verify_student`

Checks that a roll number exists. Used by the phone after the student types their roll number.

**Access:** a QR token no older than 35 seconds in the body, or admin credentials.

```json
{ "roll": "2026cse042", "token": "<QR token>" }
```

**200:** `{"success": true, "roll": "2026CSE042"}` (the roll number in its stored form), or `{"success": false, "roll": null}`.

**Errors:** `400` if `roll` is missing, `401` if the token is missing, expired or invalid.

### `GET /get_student/<roll>`

Returns the details shown on the phone's confirmation screen.

**Access:** an `X-QR-Token` header with a QR token no older than 35 seconds, or admin credentials.

**200**

```json
{ "roll": "2026CSE042", "first_name": "Alexander", "last_name": "Wright", "department": "CSE", "year": "2026" }
```

**Errors:** `401` for a missing, expired or invalid token, `404` for an unknown roll number.

---

## Recognition

### `POST /recognize_with_box`

Processes one kiosk frame: detects faces on keyframes, updates the trackers on the other frames, and matches faces against enrolled students. **Access:** admin.

```json
{
  "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
  "client_id": "cam_8f9a2b1c4e"
}
```

`client_id` identifies the kiosk (one per browser tab), so each kiosk keeps its own trackers.

**200**

```json
{
  "faces": [
    { "roll": "2026CSE042", "confidence": 0.892, "is_unknown": false, "box": [140, 92, 180, 205] }
  ]
}
```

`box` is `[x, y, width, height]` in pixels of the submitted frame. Unrecognised faces have `is_unknown: true`.

Errors are also returned with status `200`, so the kiosk loop keeps running:

- Frame too dark (mean brightness below 35):
  ```json
  {
    "faces": [],
    "status": "low_light",
    "error": "low light",
    "message": "Low lighting detected. Switch to dynamic QR check-in if needed."
  }
  ```
- Unreadable image: `{"faces": [], "error": "Invalid or corrupt image data."}`
- Anything unexpected: `{"faces": [], "error": "Server error during recognition."}`

---

## Attendance and QR codes

### `GET /generate_qr_token`

Creates a QR token for the classroom screen, the check-in URL that contains it, and that URL as a QR code. The QR code is generated on the server. **Access:** admin.

**200**

```json
{
  "status": "success",
  "token": "eyJub25jZSI6Ijk0YjE3ZWE1MmM3ZiIs...",
  "expires_in": 15,
  "checkin_url": "https://attendance-system-pratyush.onrender.com/qr_mobile?token=eyJub25jZSI6...",
  "qr_svg": "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns..."
}
```

The token is an itsdangerous `URLSafeTimedSerializer` string (payload, timestamp and signature) with the payload `{"nonce": "...", "created_at": <epoch>}`, signed with HMAC-SHA256. `qr_svg` can be used directly as an `<img src>`. `checkin_url` uses `https` when the app sits behind a proxy that sets `X-Forwarded-Proto`.

### `POST /verify_qr_token`

Checks a scanned token: valid signature and no more than 30 seconds old. **Access:** public.

```json
{ "token": "eyJub25jZSI6Ijk0YjE3ZWE1MmM3ZiIs..." }
```

**200:** `{"valid": true}`

**400:** `{"valid": false, "error": "QR code expired. Please rescan."}`

### `POST /mark_attendance`

Records attendance for today (IST). The roll number lookup is case-insensitive.

**Face check-in.** **Access:** admin (the kiosk).

```json
{ "roll": "2026CSE042", "method": "Face" }
```

**QR check-in.** **Access:** a QR token no older than 35 seconds.

```json
{ "roll": "2026CSE042", "method": "QR", "qr_token": "eyJub25jZSI6Ijk0YjE3ZWE1MmM3ZiIs..." }
```

**200**

```json
{ "status": "marked", "message": "Attendance marked for 2026CSE042 via Face." }
```

If the student already checked in today, also `200`:

```json
{ "status": "already marked today", "message": "Attendance already marked for 2026CSE042 today." }
```

**Errors**

- `400`: `{"status": "error", "message": "QR code expired. Please rescan."}`, or `"Invalid QR code signature."`
- `401`: a `Face` check-in without admin credentials.
- `404`: unknown roll number.

---

## Records

### `GET /records`

All attendance records, grouped by date. **Access:** admin.

**200**

```json
{
  "2026-10-15": [
    { "roll": "2026CSE042", "method": "Face", "time": "09:14:22" },
    { "roll": "2026ECE001", "method": "QR", "time": "09:15:08" }
  ]
}
```

**500:** `{"error": "Failed to load attendance records."}`

### `GET /dashboard_data`

Counts for today. **Access:** admin.

**200:** `{"total_students": 120, "present": 87, "absent": 33}`

**500:** the same keys set to `0`, plus an `error` message.

### `GET /export_records`

Downloads records as a CSV file. **Access:** admin.

Optional query parameters:

| Parameter | Example | Filters by |
| --- | --- | --- |
| `date` | `2026-10-15` | Date (`YYYY-MM-DD`). Any other format returns `400`. |
| `dept` | `CSE` | Department code |
| `roll` | `2026CSE042` | Roll number |

The response has `Content-Type: text/csv` and a `Content-Disposition` header with a timestamped filename such as `attendance_report_20261015_091530.csv`. Columns: `Attendance ID`, `Roll Number`, `Student Name`, `Department`, `Year`, `Email`, `Method`, `Date (IST)`, `Time (IST)`.

### `POST /clear_records`

Deletes every attendance record. **Access:** admin.

**200:** `{"status": "cleared", "message": "All attendance records cleared."}`

---

## Monitoring

### `GET /metrics`

Prometheus metrics. **Access:** public, so restrict it at the proxy or network level if the deployment is exposed.

| Metric | Type | Description |
| --- | --- | --- |
| `http_requests_total` | counter | Requests by `method`, `endpoint` and `status` |
| `http_request_duration_seconds` | histogram | Request latency by `method` and `endpoint` |
| `attendance_marked_total` | counter | Check-ins by `method` (`Face` or `QR`) |
| `active_camera_clients_total` | gauge | Kiosks active in the last 120 seconds, per process |
