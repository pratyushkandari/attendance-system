# REST API Specification & Engineering Contract

**Service:** VisionAttend Core Attendance & Identity Gateway  
**Protocol:** HTTP/1.1 & HTTP/2 over TLS  
**Base URL:** `http://localhost:5000` (Dev) / `https://attendance-system-60nr.onrender.com` (Prod)  
**Specification Version:** v2.4.2  

---

## 1. Authentication & Security Headers

The gateway implements a dual-mode access control model:

### 1.1 Stateless Bearer JWT Authentication (Mobile / CLI / Microservices)
Include the token returned from `/login_admin` in the standard HTTP `Authorization` header:
```http
Authorization: Bearer <jwt_access_token>
```
* **Algorithm:** HMAC-SHA256 (HS256)
* **Default Token TTL:** 86,400 seconds (24 Hours)
* **Claims Payload:** `sub` (Admin Email), `role` (`admin`), `iat` (Issued Timestamp), `exp` (Expiration Timestamp)

### 1.2 Stateful Session Cookie (Web Dashboard)
Browser clients accessing HTML views authenticate via cryptographically signed HTTP cookies:
```http
Cookie: session=<signed_flask_session_cookie>
```
Cookies include standard security flags: `HttpOnly`, `SameSite=Lax`, `Path=/`.

### 1.3 Rate Limiting & Account Protection
* **Sliding Lockout Window:** 3 consecutive failed authentication attempts against an institutional email trigger an automatic **15-minute temporary lockout** (`403 Forbidden`).
* **Lockout Reset:** A successful login clears the failed counter immediately.

---

## 2. API Endpoints Catalog

### 2.1 Authentication & Operator Identity

#### `POST /login_admin`
Authenticates administrative credentials and issues a stateless 24-hour Bearer JWT token alongside session cookies.

* **Request Body:**
  ```json
  {
    "email": "admin@institution.edu",
    "password": "AdminSecure@2026!"
  }
  ```
* **Success Response (`200 OK`):**
  ```json
  {
    "status": "success",
    "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "Bearer",
    "expires_in": 86400,
    "user": "admin@institution.edu"
  }
  ```
* **Error Responses:**
  * `400 Bad Request`: Missing email or password payload.
  * `401 Unauthorized`: Invalid credentials. Returns remaining attempt count:
    ```json
    {
      "status": "invalid",
      "attempts_left": 2,
      "message": "Invalid credentials. 2 attempts left."
    }
    ```
  * `403 Forbidden`: Account temporarily locked out:
    ```json
    {
      "status": "locked",
      "message": "Account locked due to 3 failed attempts. Try again in 15 minutes."
    }
    ```

---

#### `POST /register_admin`
Provisions a new administrator profile with NIST 800-63B password complexity enforcement and salted cryptographic hashing.

* **Security:** Unrestricted during initial bootstrap; rate-limited and audit-logged.
* **Request Body:**
  ```json
  {
    "email": "operator@institution.edu",
    "password": "AdminSecure@2026!"
  }
  ```
* **Password Validation Rules (NIST 800-63B):**
  * Minimum 8 characters, maximum 128 characters.
  * At least one uppercase character (`A-Z`) and one lowercase character (`a-z`).
  * At least one numeric digit (`0-9`).
  * At least one special symbol (`!@#$%^&*...`).
  * Rejects trivial passwords and email username substrings.
* **Success Response (`200 OK`):**
  ```json
  {
    "status": "registered",
    "message": "Admin registered successfully."
  }
  ```
* **Error Responses:**
  * `400 Bad Request`: `{"status": "weak_password", "message": "Password must contain at least one special symbol."}`
  * `400 Bad Request`: `{"status": "invalid_email", "message": "Email address format is invalid."}`
  * `400 Bad Request`: `{"status": "exists", "message": "An administrator with this email already exists."}`

---

### 2.2 Student Enrollment & Biometric Sampling

#### `POST /register`
Enrolls student metadata into the PostgreSQL database and automatically computes an indexed, collision-resistant roll identifier.

* **Access Control:** Admin required (`Bearer JWT` or Session).
* **Request Body:**
  ```json
  {
    "first_name": "Alexander",
    "last_name": "Wright",
    "department": "CSE",
    "year": "2026",
    "email": "a.wright@institution.edu"
  }
  ```
* **Roll Generation Formula:**
  $$\text{Roll} = \text{Year} + \text{Dept} + \text{PadZeroes}(\text{MaxSeq} + 1, 3) \quad \rightarrow \quad \text{2026CSE042}$$
* **Success Response (`200 OK`):**
  ```json
  {
    "status": "success",
    "roll": "2026CSE042"
  }
  ```
* **Error Responses:**
  * `400 Bad Request`: Missing required field or invalid email format.
  * `400 Bad Request`: Email already registered.
  * `401 Unauthorized`: Missing or invalid Bearer token / session.

---

#### `POST /capture_face`
Processes a base64-encoded webcam frame, runs MTCNN face localization, filters sub-confidence detections, and extracts a normalized 512-D embedding tensor from the cropped face region.

* **Access Control:** Admin required.
* **Request Body:**
  ```json
  {
    "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg..."
  }
  ```
* **Success Response (`200 OK`):**
  ```json
  {
    "status": "success",
    "embedding": [0.0381, -0.0192, ..., 0.0812],
    "box": [142, 88, 185, 210]
  }
  ```
* **Quality Guardrails:**
  * Minimum MTCNN face detection probability: $\ge 0.90$.
  * Minimum face crop dimensions: $40 \times 40 \text{ px}$.
  * Graceful rejection on missing or low-confidence faces without 500 error propagation:
    ```json
    { "error": "no face" }
    ```

---

#### `POST /save_face_data`
Aggregates 5 distinct facial angle samples (front, tilted up, left 15°, right 15°, neutral), calculates their mathematical centroid vector, applies $L_2$ unit normalization, and commits the biometric profile to PostgreSQL.

* **Access Control:** Admin required.
* **Centroid Formula:**
  $$\mathbf{c} = \frac{1}{K} \sum_{i=1}^K \mathbf{v}_i, \quad \mathbf{e}_{\text{final}} = \frac{\mathbf{c}}{\|\mathbf{c}\|_2}$$
* **Request Body:**
  ```json
  {
    "roll": "2026CSE042",
    "embeddings": [
      [0.0381, -0.0192, ...],
      [0.0410, -0.0185, ...],
      [0.0395, -0.0210, ...],
      [0.0378, -0.0199, ...],
      [0.0389, -0.0195, ...]
    ]
  }
  ```
* **Success Response (`200 OK`):**
  ```json
  {
    "status": "saved",
    "message": "Biometric face profile created for 2026CSE042."
  }
  ```

---

### 2.3 Real-Time Recognition & Tracking

#### `POST /recognize_with_box`
Ingests an active video frame from an interactive kiosk client, performs periodic keyframe detection, updates multi-face CSRT correlation trackers, and runs BLAS matrix dot product matching against all registered embeddings.

* **Access Control:** Admin required.
* **Request Body:**
  ```json
  {
    "image": "data:image/jpeg;base64,/9j/4AAQSkZJRg...",
    "client_id": "cam_8f9a2b1c4e"
  }
  ```
* **Success Response (`200 OK`):**
  ```json
  {
    "faces": [
      {
        "roll": "2026CSE042",
        "confidence": 0.892,
        "is_unknown": false,
        "box": [140, 92, 180, 205]
      }
    ]
  }
  ```
* **Environmental Alert (Low Light Condition):**
  When frame brightness ($\mu_{\text{gray}} < 35$):
  ```json
  {
    "faces": [],
    "status": "low_light",
    "error": "low light",
    "message": "Low lighting detected. Switch to dynamic QR check-in if needed."
  }
  ```

---

### 2.4 Attendance Verification & Dynamic QR

#### `POST /mark_attendance`
Commits an idempotent attendance record for a student for the current calendar date in Indian Standard Time (IST, UTC+5:30).

* **Modality 1: Facial Biometrics (`method: "Face"`)**
  * Requires authenticated session or Bearer JWT token.
  * Request Body:
    ```json
    {
      "roll": "2026CSE042",
      "method": "Face"
    }
    ```
* **Modality 2: Dynamic QR Scan (`method: "QR"`)**
  * Public student smartphone endpoint (gated by cryptographic signature).
  * Request Body:
    ```json
    {
      "roll": "2026CSE042",
      "method": "QR",
      "qr_token": "InRlc3Rfbm9uY2Ui.Z2vOlw.9z... (HMAC-SHA256 Token)"
    }
    ```
* **Success Response (`200 OK`):**
  ```json
  {
    "status": "marked",
    "message": "Attendance marked for 2026CSE042 via Face."
  }
  ```
* **Duplicate Same-Day Response (`200 OK`):**
  ```json
  {
    "status": "already marked today",
    "message": "Attendance already marked for 2026CSE042 today."
  }
  ```
* **Error Responses:**
  * `400 Bad Request`: `{"status": "error", "message": "QR code expired. Please rescan."}`
  * `401 Unauthorized`: Unauthenticated face submission.
  * `404 Not Found`: Roll number is not registered in system.

---

#### `GET /generate_qr_token`
Generates a time-bound HMAC-SHA256 cryptographically signed dynamic token for active classroom projection.

* **Access Control:** Admin required.
* **Success Response (`200 OK`):**
  ```json
  {
    "status": "success",
    "token": "eyJhbGciOiJIUzI1NiJ9.eyJub25jZSI6ImY3YTIxYyIsImNyZWF0ZWRfYXQiOjE3MjkxMjM4MDB9...",
    "expires_in": 15
  }
  ```

---

#### `POST /verify_qr_token`
Validates whether a scanned QR token has a valid signature and has not expired past its validity window.

* **Request Body:**
  ```json
  {
    "token": "eyJhbGciOiJIUzI1NiJ9..."
  }
  ```
* **Success Response (`200 OK`):**
  ```json
  {
    "valid": true
  }
  ```
* **Error Response (`400 Bad Request`):**
  ```json
  {
    "valid": false,
    "error": "QR token expired. Please rescan."
  }
  ```

---

### 2.5 Audit Ledger & Data Export

#### `GET /records`
Retrieves all historical attendance events chronologically grouped by calendar date.

* **Access Control:** Admin required.
* **Success Response (`200 OK`):**
  ```json
  {
    "2026-10-15": [
      {
        "roll": "2026CSE042",
        "method": "Face",
        "time": "09:14:22"
      },
      {
        "roll": "2026ECE001",
        "method": "QR",
        "time": "09:15:08"
      }
    ]
  }
  ```

---

#### `GET /export_records`
Streams an RFC 4180 compliant CSV export file containing attendance logs enriched with student profile metadata.

* **Access Control:** Admin required.
* **Query Parameters (Optional Filters):**
  * `date`: Filter by `YYYY-MM-DD`
  * `dept`: Filter by department code (`CSE`, `ECE`)
  * `roll`: Filter by specific student roll number
* **Headers Returned:**
  ```http
  Content-Type: text/csv
  Content-Disposition: attachment; filename=attendance_report_20261015_091530.csv
  ```
* **CSV Columns:**
  `Attendance ID`, `Roll Number`, `Student Name`, `Department`, `Year`, `Email`, `Method`, `Date (IST)`, `Time (IST)`

---

### 2.6 Observability & Telemetry

#### `GET /metrics`
Exposes system runtime telemetry for Prometheus ingestion in OpenMetrics format.

* **Access Control:** Public / Cluster-internal.
* **Exported Metrics:**
  * `http_requests_total{method="POST", endpoint="student.register", status="200"}`
  * `http_request_duration_seconds_bucket{le="0.05", endpoint="attendance.recognize_with_box"}`
  * `attendance_marked_total{method="Face"}`
  * `attendance_marked_total{method="QR"}`
  * `active_camera_clients_total`
  * `liveness_detection_total{status="verified"}`
