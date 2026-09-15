"""
POST sample candidate data to /api/candidates (multipart).
Uses only the Python standard library — no extra pip packages.

Usage (from backend folder, API running on 8000):
  python submit_sample_request.py
  python submit_sample_request.py --variant fresher
  python submit_sample_request.py --pdf C:\\path\\to\\real.pdf
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Minimal valid PDF (few bytes) so the request works without a file on disk.
MINIMAL_PDF = b"""%PDF-1.1
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/MediaBox[0 0 3 3]>>endobj
trailer<</Root 1 0 R>>
%%EOF"""

SAMPLES = {
    "experienced": {
        "firstName": "Aarav",
        "lastName": "Sharma",
        "email": "aarav.sharma.sample@example.com",
        "whatsapp": "9876543210",
        "gender": "Male",
        "industry": "IT & Software",
        "experience": "1-3",
        "college": None,
        "currentCompany": "Sample Tech Pvt Ltd",
        "currentCTC": "12.5",
        "skills": ["Python", "React", "SQL"],
        "state": "Karnataka",
        "city": "Bengaluru",
        "source": "Website",
        "consent": "true",
    },
    "fresher": {
        "firstName": "Priya",
        "lastName": "Nair",
        "email": "priya.nair.sample@example.com",
        "whatsapp": "8123456789",
        "gender": "Female",
        "industry": "Consulting",
        "experience": "Fresher",
        "college": "Indian Institute of Sample Science",
        "currentCompany": None,
        "currentCTC": None,
        "skills": ["Excel", "Communication"],
        "state": "Maharashtra",
        "city": "Mumbai",
        "source": "LinkedIn",
        "consent": "true",
    },
}


def _multipart_body(fields: dict[str, str], file_field: tuple[str, str, bytes, str]) -> tuple[bytes, str]:
    boundary = secrets.token_hex(16)
    crlf = b"\r\n"
    parts: list[bytes] = []

    for name, value in fields.items():
        parts.append(f"--{boundary}".encode() + crlf)
        parts.append(f'Content-Disposition: form-data; name="{name}"'.encode() + crlf)
        parts.append(crlf)
        parts.append(str(value).encode() + crlf)

    fname, filename, content, content_type = file_field
    parts.append(f"--{boundary}".encode() + crlf)
    disp = f'Content-Disposition: form-data; name="{fname}"; filename="{filename}"'
    parts.append(disp.encode() + crlf)
    parts.append(f"Content-Type: {content_type}".encode() + crlf)
    parts.append(crlf)
    parts.append(content)
    parts.append(crlf)
    parts.append(f"--{boundary}--".encode() + crlf)

    return b"".join(parts), boundary


def main() -> int:
    p = argparse.ArgumentParser(description="Submit sample candidate to API")
    p.add_argument(
        "--url",
        default="http://127.0.0.1:8000/api/candidates",
        help="Full URL for POST /api/candidates",
    )
    p.add_argument(
        "--variant",
        choices=("experienced", "fresher"),
        default="experienced",
        help="Which built-in sample to send",
    )
    p.add_argument(
        "--pdf",
        type=Path,
        help="Optional path to a real PDF (otherwise a minimal PDF is embedded)",
    )
    args = p.parse_args()
    data = SAMPLES[args.variant]

    fields = {
        "firstName": data["firstName"],
        "lastName": data["lastName"],
        "email": data["email"],
        "whatsapp": data["whatsapp"],
        "gender": data["gender"],
        "industry": data["industry"],
        "experience": data["experience"],
        "state": data["state"],
        "city": data["city"],
        "source": data["source"],
        "consent": data["consent"],
        "skills": json.dumps(data["skills"]),
    }
    if data.get("college"):
        fields["college"] = data["college"]
    if data.get("currentCompany"):
        fields["currentCompany"] = data["currentCompany"]
    if data.get("currentCTC"):
        fields["currentCTC"] = data["currentCTC"]

    if args.pdf:
        pdf_bytes = args.pdf.read_bytes()
        pdf_name = args.pdf.name
    else:
        pdf_bytes = MINIMAL_PDF
        pdf_name = "sample_resume.pdf"

    body, boundary = _multipart_body(
        fields,
        ("resumeFile", pdf_name, pdf_bytes, "application/pdf"),
    )
    req = urllib.request.Request(
        args.url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(resp.status, resp.read().decode())
    except urllib.error.HTTPError as e:
        print(e.code, e.read().decode(), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

