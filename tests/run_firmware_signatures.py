"""Exercise the ESP32-C6 release signing format offline with disposable keys."""
import argparse
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

APP_CAPACITY = 0x1D0000


def key_pair(directory, name):
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private = directory / f"{name}.key"
    public = directory / f"{name}.pub"
    private.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    public.write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM,
                                                     serialization.PublicFormat.SubjectPublicKeyInfo))
    return private, public


def espsecure(command, *args, accept=True):
    result = subprocess.run([sys.executable, "-m", "espsecure", command, "--version", "2", *args],
                            capture_output=True, text=True)
    if (result.returncode == 0) != accept:
        raise RuntimeError(f"Unexpected {command} result ({result.returncode}): {result.stdout} {result.stderr}")


def check_image(image, directory, signing_key, trusted, foreign):
    payload = image.read_bytes()
    if len(payload) < 65536 or payload[0] != 0xE9 or int.from_bytes(payload[12:14], "little") != 13:
        raise ValueError(f"Expected an ESP32-C6 application image: {image}")
    # Budget for the MMU page boundary before the V2 signature sector.
    aligned = directory / "aligned.bin"
    aligned.write_bytes(payload + b"\xff" * (-len(payload) % 65536))
    signed = directory / "signed.bin"
    espsecure("sign-data", "--keyfile", signing_key, "--output", signed, aligned)
    size = signed.stat().st_size
    if size > APP_CAPACITY:
        raise ValueError(f"Signed image exceeds the application partition by {size - APP_CAPACITY} bytes")
    espsecure("verify-signature", "--keyfile", trusted, signed)
    espsecure("verify-signature", "--keyfile", foreign, signed, accept=False)
    espsecure("verify-signature", "--keyfile", trusted, aligned, accept=False)
    changed = bytearray(signed.read_bytes())
    changed[len(payload) // 2] ^= 1
    signed.write_bytes(changed)
    espsecure("verify-signature", "--keyfile", trusted, signed, accept=False)
    print(f"PASS {image.parent.name}/{image.name}: trusted signature, unsigned/foreign/modified rejected, "
          f"{size}/{APP_CAPACITY} bytes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", type=Path, nargs="+")
    options = parser.parse_args()
    with TemporaryDirectory() as name:
        directory = Path(name)
        signing_key, trusted = key_pair(directory, "release")
        _, foreign = key_pair(directory, "foreign")
        for image in options.images:
            check_image(image, directory, signing_key, trusted, foreign)
