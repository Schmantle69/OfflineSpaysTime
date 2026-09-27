#!/usr/bin/env python3
"""Generate a local CA and a server leaf for the 127.0.0.1:443 seat.

Writes ca.pem / ca.key / ca.cer (DER, for certutil) and leaf.pem / leaf.key into
--out (default ./tls). SANs: localhost, 127.0.0.1, 127.0.0.2 plus --san extras.
Nothing here touches any trust store; installing the CA is the operator's action:

    certutil -addstore -user Root tls\\ca.cer
    certutil -delstore -user Root "SC Offline Services Local CA"   (to remove)
"""
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import sys
from pathlib import Path

CA_NAME = "SC Offline Services Local CA"


def generate(out: Path, extra_sans: list[str], days: int) -> dict[str, Path]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    out.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=5)
    until = now + dt.timedelta(days=days)

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CA_NAME)])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(until)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, key_cert_sign=True, crl_sign=True,
                content_commitment=False, key_encipherment=False, data_encipherment=False,
                key_agreement=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )

    sans: list[x509.GeneralName] = [x509.DNSName("localhost"),
                                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                                    x509.IPAddress(ipaddress.ip_address("127.0.0.2"))]
    for s in extra_sans:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(s)))
        except ValueError:
            sans.append(x509.DNSName(s))

    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(until)
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    pem = serialization.Encoding.PEM
    der = serialization.Encoding.DER
    nokey = serialization.NoEncryption()
    pkcs8 = serialization.PrivateFormat.PKCS8
    paths = {
        "ca.pem": out / "ca.pem",
        "ca.cer": out / "ca.cer",
        "ca.key": out / "ca.key",
        "leaf.pem": out / "leaf.pem",
        "leaf.key": out / "leaf.key",
    }
    paths["ca.pem"].write_bytes(ca_cert.public_bytes(pem))
    paths["ca.cer"].write_bytes(ca_cert.public_bytes(der))
    paths["ca.key"].write_bytes(ca_key.private_bytes(pem, pkcs8, nokey))
    paths["leaf.pem"].write_bytes(leaf_cert.public_bytes(pem))
    paths["leaf.key"].write_bytes(leaf_key.private_bytes(pem, pkcs8, nokey))
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("tls"))
    ap.add_argument("--san", action="append", default=[], help="extra DNS name or IP")
    ap.add_argument("--days", type=int, default=3650)
    ns = ap.parse_args(argv)
    paths = generate(ns.out, ns.san, ns.days)
    for name, p in paths.items():
        print(f"{name:9} {p}")
    print(f"\ninstall the CA (operator action):  certutil -addstore -user Root {paths['ca.cer']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
