"""Create isolated local qualification secrets; never reads or copies the real AI key."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import ipaddress
import secrets
import certifi
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

root = Path(__file__).resolve().parents[2]
target = root / ".runtime/pilot"
target.mkdir(parents=True, exist_ok=True)
if (target / "compose.env").exists():
    raise SystemExit("Local qualification configuration already exists; preserving secrets.")
tls = target / "tls"
tls.mkdir()
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "TechSpot local qualification")])
now = datetime.now(timezone.utc)
cert = (
    x509.CertificateBuilder()
    .subject_name(name)
    .issuer_name(name)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(now - timedelta(minutes=1))
    .not_valid_after(now + timedelta(days=30))
    .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    .add_extension(
        x509.SubjectAlternativeName(
            [
                x509.DNSName("localhost"),
                x509.DNSName("issuer"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
            ]
        ),
        critical=False,
    )
    .sign(key, hashes.SHA256())
)
(tls / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
(tls / "trust.pem").write_bytes(Path(certifi.where()).read_bytes() + b"\n" + (tls / "cert.pem").read_bytes())
(tls / "key.pem").write_bytes(
    key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
)
# Container users need read access inside a private parent directory.
target.chmod(0o700)
owner, runtime, oidc = secrets.token_hex(32), secrets.token_hex(32), secrets.token_hex(32)
(target / "owner-password").write_text(owner)
common = dict(
    APP_MODE="pilot",
    PILOT_QUALIFICATION="true",
    PROVIDER="scripted",
    ALLOW_EXTERNAL_AI="false",
    DIALOGUE_MODE="conversational",
    CORPUS_VERSION="synthetic-2026-10-v4",
    SESSION_SECRET=secrets.token_hex(32),
    OIDC_ISSUER="https://issuer:9443",
    OIDC_CLIENT_ID="local-qualification",
    OIDC_CLIENT_SECRET=oidc,
    WEB_ORIGIN="https://localhost:3443",
    PILOT_SUPPORT_CONTACT="Local synthetic pilot operator",
    SSL_CERT_FILE="/run/tls/trust.pem",
    EXTERNAL_CALL_LIMIT="0",
)


def write_env(name, values):
    path = target / name
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    path.chmod(0o600)


write_env(
    "runtime.env",
    dict(common, DATABASE_URL=f"postgresql://techspot_runtime:{runtime}@db:5432/techspot_pilot"),
)
write_env(
    "operator.env",
    dict(
        common,
        DATABASE_URL=f"postgresql://techspot_owner:{owner}@db:5432/techspot_pilot",
        RUNTIME_DB_PASSWORD=runtime,
    ),
)
write_env(
    "compose.env",
    dict(
        RELEASE_TAG="pilot-candidate",
        PILOT_RUNTIME_ENV=target / "runtime.env",
        PILOT_OPERATOR_ENV=target / "operator.env",
        PILOT_TLS_DIR=tls,
        PILOT_DB_PASSWORD_FILE=target / "owner-password",
    ),
)
print("Created local-only qualification configuration without external AI credentials.")
