"""Generate a self-signed TLS cert for local HTTPS testing.

Lets `uvicorn backend.main:app --ssl-keyfile ... --ssl-certfile ...` serve
HTTPS so an ESP32 probe (with its "Encrypt traffic to backend" option
enabled, or any --insecure test client) gets its POST payload encrypted in
transit over WiFi, even without a real certificate authority.

    python hardware/esp32_rf_probe/generate_dev_cert.py
    python hardware/esp32_rf_probe/generate_dev_cert.py --host 192.168.1.50

Writes .local/certs/key.pem and .local/certs/cert.pem (git-ignored, same
convention as .local/postgres/). This is a self-signed cert with no CA
chain -- clients must skip verification (WiFiClientSecure::setInsecure() on
the ESP32, --insecure on read_probe.py, curl -k) to use it. That protects
against passive eavesdropping on the WiFi, not against an active
man-in-the-middle presenting a different cert -- there is no PKI here, by
design, for a local dev/lab tool.
"""
from __future__ import annotations

import argparse
import datetime
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

CERT_DIR = Path(__file__).resolve().parent.parent.parent / ".local" / "certs"


def _san_entries(host: str) -> list[x509.GeneralName]:
    try:
        return [x509.IPAddress(ipaddress.ip_address(host))]
    except ValueError:
        return [x509.DNSName(host)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="localhost",
                     help="hostname or IP the backend will be reached at (default: localhost). "
                          "Add the LAN IP an ESP32 will actually connect to, e.g. 192.168.1.50, "
                          "or re-run with it if you didn't know it yet.")
    ap.add_argument("--days", type=int, default=825, help="validity period (default: 825 days)")
    ap.add_argument("--out", type=Path, default=CERT_DIR, help=f"output directory (default: {CERT_DIR})")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    key_path = args.out / "key.pem"
    cert_path = args.out / "cert.pem"

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, args.host),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "RF-SLM local dev (not for production)"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    san = list({*_san_entries(args.host), *_san_entries("localhost"), *_san_entries("127.0.0.1")})
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=args.days))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    print(f"wrote {key_path}")
    print(f"wrote {cert_path}")
    print(f"\nRun the backend with:\n"
          f"  uvicorn backend.main:app --host 0.0.0.0 --port 8000 "
          f"--ssl-keyfile {key_path} --ssl-certfile {cert_path}")
    print("\nThis is self-signed with no CA -- clients must skip verification "
          "(setInsecure() on the ESP32, --insecure on read_probe.py, curl -k).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
