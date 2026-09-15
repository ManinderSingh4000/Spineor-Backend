# Backend Integration Requirements — Job Application Submission

Audience: backend engineers implementing the job-application endpoint the frontend now calls.

The frontend (React 19 + Vite, `src/pages/JobApply.jsx`) submits a candidate's job application as
`multipart/form-data` to a single endpoint. The backend must validate the payload, email it (with the
resume attached) to HR, delete the temporary resume, and return a JSON result. **No S3 / cloud / permanent
resume storage** — the file exists only for the lifetime of the request.

Items marked **Needs Confirmation** are decisions the frontend could not make on its own.

---

## 1. Endpoint

```
POST /api/v1/job-applications
Content-Type: multipart/form-data   (boundary set by the browser/axios — do not require a fixed value)
Accept: application/json
```

How the frontend reaches it (`src/utils/jobApplicationApi.js`):

| Environment | Request URL | Notes |
| --- | --- | --- |
| Local dev, `VITE_API_BASE_URL` empty | `http://localhost:5174/api/v1/job-applications` | Vite proxies `/api` → `https://spineor-backend-xsi9.onrender.com` (`vite.config.js`). |
| Local dev, `VITE_API_BASE_URL=http://localhost:<PORT>` | `http://localhost:<PORT>/api/v1/job-applications` | Direct, cross-origin → CORS required (§9). |
| Production (pm2 / `server.js`) | `https://<frontend-domain>/api/v1/job-applications` | `server.js` proxies `/api` → `BACKEND_URL` (`ecosystem.config.cjs`). Same-origin, no CORS needed. |

The path `/api/v1/job-applications` is sent intact through both proxies (no prefix stripping).

---

## 2. Request fields (exactly what the frontend sends)

All text parts are UTF-8 strings. Values are already `.trim()`-ed client-side; trim again server-side.

| Field | Type | Required | Source in UI | Server-side rule |
| --- | --- | --- | --- | --- |
| `job_id` | string (numeric) | yes | URL route `/job-apply/:id` | Must parse to an integer and match a known, active job (§3). |
| `job_title` | string | sent always | Job header on the page | Informational only — **do not trust for lookup**; see §3 **Needs Confirmation**. |
| `first_name` | string | yes | "First name" | 1–100 chars. |
| `last_name` | string | yes | "Family name" | 1–100 chars. |
| `email` | string | yes | "Email address" | Valid email (RFC 5322 practical check). The "Confirm email" input is validated client-side only and is **not** sent. |
| `phone` | string | yes | "Phone number" | Free text; suggest E.164-ish check: digits, `+`, spaces, `()-`, 7–20 chars. |
| `alternate_phone` | string | no (omitted when empty) | "Alternate phone" | Same rule as `phone` when present. |
| `skills` | string | no (omitted when empty) | "Skills" textarea | ≤ 2 000 chars. |
| `experience` | string | no (omitted when empty) | "Work experience" textarea | ≤ 5 000 chars. |
| `accept_terms` | `"true"` / `"false"` | yes | Terms checkbox | Must be `"true"`; the UI cannot submit otherwise, but re-check server-side. |
| `resume` | file | yes | Resume upload | See §4. **Field name must be exactly `resume`.** |

Fields that do **not** exist in the UI and are therefore **not** sent: `full_name`, `location`,
`linkedin_url`, `cover_letter`. Do not require them.

---

## 3. Job validation

- Reject when `job_id` is missing, non-numeric, or unknown.
- Reject when the job is inactive / closed / expired.

**Needs Confirmation — job source of truth.** The job catalogue currently lives only in the frontend
(`src/data/jobs.js`, fields `id`, `title`, `closingInDays`, `date`, …). The backend has no job table.
Options, pick one:

1. Backend keeps its own list/table of active job IDs + titles (frontend list must be mirrored/kept in sync).
2. Backend accepts a configured allow-list of active IDs via env/config.
3. Backend trusts the frontend-supplied `job_title` and only sanity-checks `job_id` is a positive integer
   (weakest; the title in the HR email could then be spoofed).

Until decided, the frontend sends both `job_id` and `job_title` so any option works without a frontend change.

---

## 4. Resume file rules

| Rule | Value |
| --- | --- |
| Field name | `resume` |
| Allowed extensions | `.pdf`, `.doc`, `.docx` |
| Allowed MIME types | `application/pdf`, `application/msword`, `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| Max size | **5 MB** (5 × 1024 × 1024 = 5 242 880 bytes) — **Needs Confirmation** (spec said "recommended"). The frontend enforces 5 MB; if the backend picks a different limit, update `RESUME_MAX_SIZE` in `src/utils/jobApplicationApi.js` and the hint copy in `JobApply.jsx`. |
| Required | yes |

Server-side handling:

- Validate **both** extension and content. Do not rely on the client-supplied `Content-Type` alone
  (browsers send an empty or generic type for `.doc/.docx` on some platforms). Sniff magic bytes
  (`%PDF-`, OLE2 `D0 CF 11 E0`, ZIP `PK\x03\x04` for `.docx`).
- Enforce the size limit at the multipart parser / reverse-proxy level (return `413` if exceeded before
  buffering the whole body).
- Save to a temp directory with a **generated filename** (UUID + validated extension). Never use the
  original filename for the path. Keep the original name only for the email attachment name, sanitised.
- Delete the temp file in a `finally` block — on success, on validation failure, and on email failure.
- Optional: run an antivirus scan (e.g. ClamAV) before attaching — **Needs Confirmation**.

---

## 5. Email to HR

Send one email per successful submission.

- **To:** `HR_EMAIL` (env). Current mailto fallback in the codebase used `hrd@spineor.com` — **Needs Confirmation** that this is the correct HR inbox.
- **From:** `EMAIL_FROM` (env). **Reply-To:** the candidate's `email` so HR can reply directly.
- **Subject (suggested):** `Job Application: <job_title> (#<job_id>) — <first_name> <last_name>`
- **Body (plain text + optional HTML):**
  - Job ID and job title
  - Candidate name, email, phone, alternate phone (if any)
  - Skills, experience (if any)
  - Terms accepted: yes, timestamp (UTC), application ID
  - Submission metadata: IP address, user-agent (useful for spam triage) — **Needs Confirmation** for privacy policy compliance
- **Attachment:** the resume, with a sanitised filename such as
  `<Last>_<First>_<job_id>.<ext>` or the original name stripped of path/control characters.
- HTML-escape every candidate-supplied value if an HTML body is rendered (XSS in mail clients).
- Send synchronously within the request unless a queue already exists; the frontend waits up to
  **60 s** before timing out. If a queue is used, only return `success: true` once the job is durably enqueued.

**Needs Confirmation:** should the candidate also receive a confirmation email? The UI copy ("We'll use
this email to confirm your application") implies yes, but nothing is implemented.

---

## 6. Response contract (the frontend depends on this shape)

The frontend treats a response as success **only** when HTTP 2xx **and** `body.success === true`.
Every other case shows `body.message` (if a string) and lists `body.errors` values under it.

### Success — `201 Created` (200 also accepted)

```json
{
  "success": true,
  "message": "Your application has been submitted successfully.",
  "data": {
    "application_id": "app_12345",
    "job_id": 102,
    "status": "submitted"
  }
}
```

### Validation error — `422 Unprocessable Entity` (400 also accepted)

```json
{
  "success": false,
  "message": "Please correct the highlighted fields.",
  "errors": {
    "email": "Enter a valid email address.",
    "resume": "Only PDF, DOC, and DOCX files are allowed."
  }
}
```

`errors` keys should be the request field names above. The frontend shows `errors.resume` next to the
upload control and every other key in the alert banner.

### Job not found / inactive — `404 Not Found` (or `410 Gone` for closed)

```json
{ "success": false, "message": "This job is no longer accepting applications." }
```

### File too large — `413 Payload Too Large`

```json
{ "success": false, "message": "Resume must be 5 MB or smaller.", "errors": { "resume": "Resume must be 5 MB or smaller." } }
```

### Rate limited — `429 Too Many Requests`

```json
{ "success": false, "message": "Too many attempts. Please wait a moment and try again." }
```

### Server / email failure — `500` or `502`

```json
{
  "success": false,
  "message": "We could not submit your application right now. Please try again later."
}
```

Never leak stack traces, SMTP errors, or file paths in `message`. If the body is not JSON or has no
`message`, the frontend falls back to a generic message based on the HTTP status.

---

## 7. Error cases — expected backend behaviour

| Case | Backend response | Frontend behaviour |
| --- | --- | --- |
| Missing / non-numeric `job_id` | 422, `errors.job_id` | Banner with message + field list |
| Job inactive / closed / unknown | 404 or 410, message | Banner: message (fallback "This job is no longer available.") |
| Missing required field | 422, `errors.<field>` | Banner + field list |
| Invalid email / phone | 422, `errors.email` / `errors.phone` | Banner + field list |
| Missing resume | 422, `errors.resume` | Message shown under the upload box |
| Unsupported resume type | 422, `errors.resume` | Under the upload box |
| Resume too large | 413 (+ `errors.resume`) | Under the upload box / banner |
| Network failure / backend down | (no response) | "Network error…" banner; form data preserved so the user can retry |
| Request > 60 s | (timeout) | "The request timed out…" banner |
| Email sending failure | 502 or 500, generic message; temp file deleted; error logged server-side | Generic banner |
| Double-click submit | Idempotency not required — frontend blocks it (ref lock + disabled button). Optional: dedupe same `email + job_id` within N minutes → return the original success response. **Needs Confirmation.** | — |
| Spam / abuse | 429 after rate limit (§10) | "Too many attempts…" banner |

---

## 8. Environment variables (backend)

```
# Recipient: HR receives every job application here
HR_EMAIL=hrd@spineor.com

# SMTP account that sends email from your backend
SMTP_HOST=smtp.your-email-provider.com
SMTP_PORT=587
SMTP_USER=no-reply@spineor.com
SMTP_PASSWORD=your-app-password
SMTP_SECURE=false

# What HR sees in the “From” field
EMAIL_FROM="Spineor Careers <no-reply@spineor.com>"

# Optional but recommended:
# HR clicks Reply → response goes directly to the candidate
# Do NOT put this in .env; set it dynamically from form email:
# replyTo = candidate.email

MAX_RESUME_SIZE_BYTES=5242880
TEMP_UPLOAD_DIR=/tmp/spineor-resumes

CORS_ALLOWED_ORIGINS=http://localhost:5174,https://spineortechnologies.com,https://www.spineortechnologies.com

RATE_LIMIT_WINDOW_SECONDS=600
RATE_LIMIT_MAX_REQUESTS=5
```

None of these values exist in, or should ever be added to, the frontend repo.

---

## 9. CORS

Required only when the browser calls the backend origin directly (local dev with `VITE_API_BASE_URL`
set, or if production ever stops proxying through `server.js`).

- `Access-Control-Allow-Origin`: exact origins from `CORS_ALLOWED_ORIGINS` (no `*` — not needed and
  discouraged with credentials).
  - Local: `http://localhost:5174` (Vite dev port from `vite.config.js`), `http://localhost:5173` (pm2/`server.js` port).
  - Production: `https://spineortechnologies.com`, `https://www.spineortechnologies.com` (from `allowedHosts` in `vite.config.js`). **Needs Confirmation** for any staging domain.
- `Access-Control-Allow-Methods: POST, OPTIONS`
- `Access-Control-Allow-Headers: Content-Type, Accept`
- Answer `OPTIONS /api/v1/job-applications` with 204.
- No cookies/credentials are sent by the frontend.

---

## 10. Spam / rate limiting

- Per-IP rate limit on `POST /api/v1/job-applications` (suggested 5 requests / 10 min → 429).
- Reject obviously malformed bodies before parsing the file (check text fields first when the parser allows).
- Optional honeypot field: the frontend can add a hidden `website` input that must be empty — **Needs
  Confirmation** (not implemented; requires a small frontend change).
- Optional CAPTCHA (Turnstile/reCAPTCHA) — **Needs Confirmation**; requires a frontend change and a site key.
- Log `application_id`, `job_id`, hashed email, IP, outcome — never log the resume contents.

---

## 11. Processing sequence (reference)

1. Enforce body-size limit (reject > ~6 MB total early with 413).
2. Rate-limit check → 429.
3. Parse multipart; stream `resume` to `TEMP_UPLOAD_DIR/<uuid>.<ext>`.
4. Validate `job_id` → 422/404/410.
5. Validate text fields → 422 (collect **all** field errors into `errors`, don't stop at the first).
6. Validate resume extension, MIME, magic bytes, size → 422/413.
7. Generate `application_id`.
8. Build and send the HR email with the attachment.
9. `finally`: delete the temp file.
10. Return 201 JSON (or the appropriate error above).

---

## 12. Values the frontend needs back from the backend team

| Item | Where it goes on the frontend |
| --- | --- |
| API base URL for local dev (e.g. `http://localhost:8000`) | `.env` → `VITE_API_BASE_URL` (see `.env.example`) |
| Production backend URL | `ecosystem.config.cjs` → `BACKEND_URL` and `vite.config.js` proxy target (currently `https://spineor-backend.onrender.com`) |
| Final endpoint path (confirm `/api/v1/job-applications`) | `JOB_APPLICATIONS_ENDPOINT` in `src/utils/jobApplicationApi.js` |
| Confirmed response shape (`success`, `message`, `errors`, `data`) | Error handling in `src/utils/jobApplicationApi.js` |
| Final max upload size | `RESUME_MAX_SIZE` in `src/utils/jobApplicationApi.js` + hint text in `src/pages/JobApply.jsx` |
| Allowed CORS origins (local + prod) | Backend config only; no frontend change |
| Job source of truth decision (§3) | May remove `job_title` from the payload once decided |
| Whether candidates get a confirmation email (§5) | Success-screen copy in `src/pages/JobApply.jsx` |
