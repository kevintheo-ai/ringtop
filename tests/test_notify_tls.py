"""Over https a try checks the certificate of its server and the name in it: a certificate the machine does not
trust, and a trusted one for another name, end the try in its handshake, and the server sees no request. The
certificates are made here for each check, with the openssl of the system, and trusted only by the contexts of
the tries the check makes. All on 127.0.0.1."""

import contextlib
import shutil
import ssl
import subprocess
import tempfile
from pathlib import Path

from ringtop_parts.connect.notify import send
from tests.catcher import CANARY, Catcher
from tests.test_notify import TOOK, exact

OPENSSL = shutil.which("openssl") or "/usr/bin/openssl"


@contextlib.contextmanager
def certificates():
    """Two certificates of their own making, each its own authority: "here" for 127.0.0.1, "other" for a name
    that is not this machine's. Gives {name: (certificate, key)}; both are gone after the check."""
    with tempfile.TemporaryDirectory() as folder:
        made = {}
        for name, subject in (("here", "IP:127.0.0.1"), ("other", "DNS:other.invalid")):
            cert, key = Path(folder) / f"{name}.pem", Path(folder) / f"{name}.key"
            command = [OPENSSL, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert)]
            command += ["-days", "1", "-subj", f"/CN={subject.split(':')[1]}", "-addext", f"subjectAltName={subject}"]
            subprocess.run(command, check=True, capture_output=True, timeout=60)
            made[name] = (cert, key)
        yield made


def serving(cert, key) -> ssl.SSLContext:
    """The context of a catcher that answers over https with a certificate."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert), str(key))
    return context


@contextlib.contextmanager
def trusting(cert):
    """The tries made meanwhile trust `cert` beside what the system trusts; gives the context of each, as the try
    left it."""
    real, made = ssl.create_default_context, []

    def spy(*args, **more):
        context = real(*args, **more)
        context.load_verify_locations(cafile=str(cert))
        made.append(context)
        return context

    ssl.create_default_context = spy
    try:
        yield made
    finally:
        ssl.create_default_context = real


def test_a_certificate_this_machine_does_not_trust_ends_the_try_in_its_handshake():
    """A server on 127.0.0.1 with a certificate of its own making: the try fails at the handshake, nothing left
    (no byte of the request, so it does not count), and the server saw no request."""
    with certificates() as made, Catcher(tls=serving(*made["here"])) as server:
        assert send(server.address, CANARY, "away on") == ("SSLCertVerificationError", False)
        got = server.caught(1)
    assert got == [b""], got


def test_a_trusted_certificate_for_another_name_ends_the_try_in_its_handshake_as_well():
    """The certificate is trusted, but it is for another name than the server's: the name is checked too."""
    with certificates() as made, trusting(made["other"][0]) as contexts, Catcher(tls=serving(*made["other"])) as server:
        assert send(server.address, CANARY, "away on") == ("SSLCertVerificationError", False)
        got = server.caught(1)
    assert got == [b""] and len(contexts) == 1, (got, contexts)


def test_a_trusted_certificate_for_this_name_takes_the_message_and_the_context_checks_both():
    """The other way round, so that the two checks above fail for the right reason: trusted and for 127.0.0.1,
    the message goes, byte for byte as over plain http. The context of the try asks for a certificate and checks
    the name in it."""
    with certificates() as made, trusting(made["here"][0]) as contexts, Catcher(tls=serving(*made["here"])) as server:
        assert send(server.address, CANARY, "away on") == TOOK
        got = server.caught(1)
    assert got == [exact("away on", server.port)], got
    assert [(context.verify_mode, context.check_hostname) for context in contexts] == [(ssl.CERT_REQUIRED, True)]
