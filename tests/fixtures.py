from __future__ import annotations

import zipfile
from email.message import EmailMessage
from pathlib import Path


COMPLETED_RECEIPT = """Thanks for riding with Zoox!

Your Zoox Receipt

Trip distance2.33 miles
Trip duration15 minutes

Pickup:
123 Example Street, San Francisco, California 94102, United States
August 5th, 2026
8:33 PM

Drop-off:
456 Sample Avenue, San Francisco, California 94110, United States
August 5th, 2026
8:48 PM

Trip Total
$0.00
"""

CANCELED_RECEIPT = """Your canceled ride receipt

Trip distance0.0 miles
Trip duration0 minutes

Pickup:
789 Canceled Street, San Francisco, California 94105, United States

Drop-off:
321 Unreached Avenue, San Francisco, California 94111, United States

Payment Details
Trip Fare$0.00
Trip Total
$0.00
"""


def email_bytes(subject: str, body: str) -> bytes:
    message = EmailMessage()
    message["From"] = "Zoox <noreply@notifications.zoox.com>"
    message["To"] = "rider@example.com"
    message["Subject"] = subject
    message["Date"] = "Wed, 5 Aug 2026 18:37:57 -0600"
    message.set_content(body)
    return message.as_bytes()


def mbox_message(message: bytes) -> bytes:
    return b"From sender@example.com Thu Aug  6 00:00:00 2026\n" + message + b"\n"


def write_mbox(path: Path, *messages: bytes) -> None:
    path.write_bytes(b"".join(mbox_message(message) for message in messages))


def write_takeout(path: Path, *messages: bytes) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Takeout/Mail/All mail.mbox",
            b"".join(mbox_message(message) for message in messages),
        )
