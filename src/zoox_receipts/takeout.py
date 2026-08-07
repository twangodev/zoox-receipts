from __future__ import annotations

import mailbox
import shutil
import tempfile
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from email import policy
from email.message import EmailMessage
from email.parser import BytesHeaderParser, BytesParser
from pathlib import Path
from typing import cast


MessagePredicate = Callable[[EmailMessage], bool]


@contextmanager
def local_mbox_path(path: Path) -> Iterator[Path]:
    """Yield an MBOX path, temporarily extracting one from Takeout ZIP input."""
    if not zipfile.is_zipfile(path):
        yield path
        return

    with zipfile.ZipFile(path) as archive:
        mbox_names = [name for name in archive.namelist() if name.lower().endswith(".mbox")]
        if len(mbox_names) != 1:
            raise ValueError(
                f"expected exactly one MBOX in {path}, found {len(mbox_names)}"
            )

        with tempfile.TemporaryDirectory(prefix="zooxr-") as directory:
            extracted_mbox = Path(directory) / Path(mbox_names[0]).name
            with archive.open(mbox_names[0]) as source, extracted_mbox.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            yield extracted_mbox


def iter_matching_messages(
    path: Path, predicate: MessagePredicate
) -> Iterator[EmailMessage]:
    """Use mailbox boundaries, parsing full MIME bodies only for matching headers."""
    messages = mailbox.mbox(path, create=False)
    try:
        for key in messages.iterkeys():
            with messages.get_file(key) as message_file:
                header = cast(
                    EmailMessage,
                    BytesHeaderParser(policy=policy.default).parse(message_file),
                )
                if not predicate(header):
                    continue
                message_file.seek(0)
                yield cast(
                    EmailMessage,
                    BytesParser(policy=policy.default).parse(message_file),
                )
    finally:
        messages.close()
