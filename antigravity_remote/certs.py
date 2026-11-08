"""Yerel ağda HTTPS için kendinden imzalı (self-signed) sertifika üretir.

Telefon tarayıcıları (özellikle iOS Safari) mikrofon / ses tanıma gibi
özellikleri yalnızca güvenli (HTTPS) bağlantılarda açar. Bu modül, PC'nin
yerel IP adresini içeren bir sertifikayı bir kez oluşturur ve tekrar kullanır.
"""

import datetime
import ipaddress
import ssl
from pathlib import Path
from typing import Optional, Tuple


def get_cert_dir() -> Path:
    return Path.home() / ".gemini" / "antigravity_remote_certs"


def ensure_self_signed_cert(local_ip: str) -> Optional[Tuple[Path, Path]]:
    """Sertifika yoksa (veya IP değiştiyse) yeni bir tane üretir. (cert, key) yolunu döndürür."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        return None

    cert_dir = get_cert_dir()
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"
    ip_marker = cert_dir / "ip.txt"

    if cert_path.exists() and key_path.exists() and ip_marker.exists():
        if ip_marker.read_text(encoding="utf-8").strip() == local_ip:
            return cert_path, key_path

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Antigravity Remote")])

    san_entries = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    try:
        san_entries.append(x509.IPAddress(ipaddress.ip_address(local_ip)))
    except ValueError:
        pass

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    ip_marker.write_text(local_ip, encoding="utf-8")
    return cert_path, key_path


def build_ssl_context(local_ip: str) -> Optional[ssl.SSLContext]:
    paths = ensure_self_signed_cert(local_ip)
    if not paths:
        return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(paths[0]), str(paths[1]))
    return ctx
