"""
Smoke-test POST /api/v1/job-applications (multipart). Stdlib only.

  python submit_job_application.py                      # happy path, embedded PDF
  python submit_job_application.py --resume C:\cv.docx
  python submit_job_application.py --case invalid       # expect 422 with errors{}
  python submit_job_application.py --url http://127.0.0.1:8000/api/v1/job-applications
"""

from __future__ import annotations

import argparse
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

MINIMAL_PDF = b"""%PDF-1.1
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj
trailer<</Root 1 0 R>>
%%EOF"""

CASES = {
    "valid": {
        "job_id": "102",
        "job_title": "Frontend Engineer",
        "first_name": "Aarav",
        "last_name": "Sharma",
        "email": "aarav.sharma.sample@example.com",
        "phone": "+91 98765 43210",
        "alternate_phone": "",
        "skills": "React, TypeScript, Vite",
        "experience": "3 years building SPAs.",
        "accept_terms": "true",
    },
    "invalid": {
        "job_id": "102",
        "job_title": "Frontend Engineer",
        "first_name": "",
        "last_name": "Sharma",
        "email": "not-an-email",
        "phone": "12",
        "accept_terms": "false",
    },
}

MIME = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _multipart(fields: dict[str, str], file_part: tuple[str, str, bytes, str] | None) -> tuple[bytes, str]:
    boundary = secrets.token_hex(16)
    crlf = b"\r\n"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts += [f"--{boundary}".encode() + crlf,
                  f'Content-Disposition: form-data; name="{name}"'.encode() + crlf, crlf,
                  str(value).encode() + crlf]
    if file_part:
        fname, filename, content, ctype = file_part
        parts += [f"--{boundary}".encode() + crlf,
                  f'Content-Disposition: form-data; name="{fname}"; filename="{filename}"'.encode() + crlf,
                  f"Content-Type: {ctype}".encode() + crlf, crlf, content, crlf]
    parts.append(f"--{boundary}--".encode() + crlf)
    return b"".join(parts), boundary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8000/api/v1/job-applications")
    p.add_argument("--case", choices=CASES, default="valid")
    p.add_argument("--resume", type=Path, help="real .pdf/.doc/.docx (default: embedded PDF)")
    p.add_argument("--no-resume", action="store_true", help="omit the file to test errors.resume")
    args = p.parse_args()

    fields = {k: v for k, v in CASES[args.case].items() if v != ""}
    if args.no_resume:
        file_part = None
    elif args.resume:
        ext = args.resume.suffix.lower()
        file_part = ("resume", args.resume.name, args.resume.read_bytes(), MIME.get(ext, "application/octet-stream"))
    else:
        file_part = ("resume", "sample_resume.pdf", MINIMAL_PDF, "application/pdf")

    body, boundary = _multipart(fields, file_part)
    req = urllib.request.Request(
        args.url, data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(resp.status, resp.read().decode())
            return 0
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
