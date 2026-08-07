from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from .models import Ride
from .takeout import iter_matching_messages, local_mbox_path


ZOOX_SENDER_DOMAIN = "notifications.zoox.com"
CANCELED_SUBJECT = "Your canceled ride receipt"
RECEIPT_SUBJECT = re.compile(
    rf"^(?:Your ride on\b|{re.escape(CANCELED_SUBJECT)}$)", re.IGNORECASE
)
MONTH = (
    r"January|February|March|April|May|June|July|August|September|October|"
    r"November|December"
)
RECEIPT_DATE = rf"(?:{MONTH})\s+\d{{1,2}}(?:st|nd|rd|th),\s+\d{{4}}"
RECEIPT_TIME = r"\d{1,2}:\d{2}\s*(?:AM|PM)"


class ReceiptParseError(ValueError):
    pass


def is_zoox_ride_header(message: EmailMessage) -> bool:
    sender = parseaddr(str(message.get("From", "")))[1].lower()
    subject = str(message.get("Subject", ""))
    return (
        sender.endswith(f"@{ZOOX_SENDER_DOMAIN}")
        and RECEIPT_SUBJECT.match(subject) is not None
    )


def plain_text(message: EmailMessage) -> str:
    part = message.get_body(preferencelist=("plain",))
    if part is None:
        raise ReceiptParseError("receipt has no plain-text body")
    content = part.get_content()
    if not isinstance(content, str):
        raise ReceiptParseError("receipt plain-text body is not text")
    return content


def normalize_receipt(text: str) -> str:
    decoded = html.unescape(text)
    visible = "".join(
        character for character in decoded if unicodedata.category(character) != "Cf"
    )
    return re.sub(r"\s+", " ", visible).strip()


def parse_endpoint(text: str, label: str, next_label: str) -> tuple[str, str, str]:
    match = re.search(
        rf"\b{re.escape(label)}:\s*(?P<address>.+?)\s+"
        rf"(?P<date>{RECEIPT_DATE})\s+"
        rf"(?P<time>{RECEIPT_TIME})\s+{re.escape(next_label)}",
        text,
        re.IGNORECASE,
    )
    if match is None:
        raise ReceiptParseError(f"could not parse {label.lower()}")
    return match.group("address").strip(), match.group("date"), match.group("time")


def parse_canceled_endpoints(text: str) -> tuple[str, str]:
    match = re.search(
        r"\bPickup:\s*(?P<start>.+?)\s+Drop-off:\s*(?P<end>.+?)\s+"
        r"(?:Payment Details|Trip Total)\b",
        text,
        re.IGNORECASE,
    )
    if match is None:
        raise ReceiptParseError("could not parse canceled ride endpoints")
    return match.group("start").strip(), match.group("end").strip()


def receipt_datetime(receipt_date: str, receipt_time: str) -> str:
    without_ordinal = re.sub(r"(?<=\d)(?:st|nd|rd|th)", "", receipt_date)
    parsed = datetime.strptime(
        f"{without_ordinal} {receipt_time}", "%B %d, %Y %I:%M %p"
    )
    return parsed.isoformat()


def required_number(text: str, pattern: str, field: str) -> float:
    match = re.search(pattern, text, re.IGNORECASE)
    if match is None:
        raise ReceiptParseError(f"could not parse {field}")
    return float(match.group("value").replace(",", ""))


def parse_ride(message: EmailMessage) -> Ride:
    text = normalize_receipt(plain_text(message))
    canceled = str(message.get("Subject", "")).casefold() == CANCELED_SUBJECT.casefold()
    distance_miles = required_number(
        text,
        r"Trip\s+distance\s*(?P<value>\d+(?:\.\d+)?)\s*miles?\b",
        "trip distance",
    )
    duration_minutes = int(
        required_number(
            text,
            r"Trip\s+duration\s*(?P<value>\d+)\s*minutes?\b",
            "trip duration",
        )
    )
    price_usd = required_number(
        text,
        r"Trip\s+Total\s*\$(?P<value>\d[\d,]*(?:\.\d+)?)",
        "trip total",
    )

    if canceled:
        start, end = parse_canceled_endpoints(text)
        sent_at = parsedate_to_datetime(str(message.get("Date", "")))
        if sent_at is None:
            raise ReceiptParseError("canceled receipt has no date")
        date = sent_at.date().isoformat()
        started_at = None
        ended_at = None
    else:
        start, start_date, start_time = parse_endpoint(text, "Pickup", "Drop-off:")
        end, end_date, end_time = parse_endpoint(text, "Drop-off", "Trip Total")
        started_at = receipt_datetime(start_date, start_time)
        ended_at = receipt_datetime(end_date, end_time)
        date = started_at[:10]

    return Ride(
        date=date,
        canceled=canceled,
        start=start,
        end=end,
        started_at=started_at,
        ended_at=ended_at,
        distance_miles=distance_miles,
        duration_minutes=duration_minutes,
        price_usd=price_usd,
    )


def extract_rides(path: Path) -> list[Ride]:
    with local_mbox_path(path) as mbox_path:
        rides = [
            parse_ride(message)
            for message in iter_matching_messages(mbox_path, is_zoox_ride_header)
        ]
    return sorted(rides, key=lambda ride: (ride.date, ride.started_at or ""))
