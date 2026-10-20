"""Local record of SPC prompts: drafts being refined, and the ones submitted on BRAIN.

One JSON file per prompt under the data directory. Nothing here is a secret, so it stays out
of the sealed vault; and a file per prompt keeps a corrupt one from taking the rest with it.
The platform is the source of truth for what is actually running; this is the user's own
bookkeeping, used for limits and overlap warnings.
"""

import json
import re
import secrets
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog

if TYPE_CHECKING:
    from pathlib import Path

log = structlog.get_logger(__name__)

ID_SHAPE = re.compile(r"[0-9a-f]{32}")
Status = Literal["draft", "submitted"]


@dataclass(slots=True)
class Draft:
    id: str
    name: str
    model: str
    model_version: str
    frequency: str
    weight: float
    prompt: str
    sample_output: str
    status: Status
    created_at: str
    updated_at: str
    submitted_at: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class DraftStore:
    def __init__(self, data_dir: Path) -> None:
        self.folder = data_dir / "spc"

    def _path(self, draft_id: str) -> Path:
        # The id becomes a file name, so only the shape this store mints is accepted.
        if not ID_SHAPE.fullmatch(draft_id):
            raise KeyError(draft_id)
        return self.folder / f"{draft_id}.json"

    def _write(self, draft: Draft) -> None:
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = self._path(draft.id)
        tmp = target.with_name(f".{target.name}.{secrets.token_hex(4)}")
        try:
            tmp.write_text(json.dumps(asdict(draft), ensure_ascii=False), encoding="utf-8")
            tmp.replace(target)
        finally:
            tmp.unlink(missing_ok=True)

    def list(self) -> list[Draft]:
        if not self.folder.is_dir():
            return []
        found: list[Draft] = []
        for path in self.folder.glob("*.json"):
            if not ID_SHAPE.fullmatch(path.stem):
                continue
            try:
                body: Any = json.loads(path.read_text(encoding="utf-8"))
                found.append(Draft(**body))
            except OSError, ValueError, TypeError:
                # One unreadable file must not hide the others.
                log.warning("spc.draft_unreadable", file=path.name)
        return sorted(found, key=lambda d: d.updated_at, reverse=True)

    def get(self, draft_id: str) -> Draft:
        try:
            return Draft(**json.loads(self._path(draft_id).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError) as exc:
            raise KeyError(draft_id) from exc

    def create(self, **fields: Any) -> Draft:
        now = _now()
        draft = Draft(
            id=secrets.token_hex(16),
            status="draft",
            created_at=now,
            updated_at=now,
            **fields,
        )
        self._write(draft)
        return draft

    def update(self, draft_id: str, **fields: Any) -> Draft:
        draft = self.get(draft_id)
        for key, value in fields.items():
            setattr(draft, key, value)
        draft.updated_at = _now()
        self._write(draft)
        return draft

    def mark(self, draft_id: str, *, submitted: bool) -> Draft:
        draft = self.get(draft_id)
        draft.status = "submitted" if submitted else "draft"
        draft.submitted_at = _now() if submitted else None
        draft.updated_at = _now()
        self._write(draft)
        return draft

    def delete(self, draft_id: str) -> None:
        self._path(draft_id).unlink(missing_ok=True)
