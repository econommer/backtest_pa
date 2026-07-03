"""Persistent Bloomberg usage accounting — the cap-safety bookkeeping (M6 spec D4).

Bloomberg's Desktop API meters (opaquely) daily hits and *monthly unique
securities*; unique securities never un-count. The ledger therefore records
every security we have EVER requested (so re-requests are free) plus per-day
new-security counts, and the fetch pipeline refuses any request that would
push a day past its budget. Failed requests still count — assume Bloomberg
metered the attempt.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Sequence


class LedgerError(RuntimeError):
    """The usage ledger is unreadable — refuse to fetch rather than guess."""


@dataclass
class UsageLedger:
    """Unique-security + per-day request accounting, persisted as JSON."""

    path: Path
    #: security string -> ISO date first requested
    securities: dict[str, str] = field(default_factory=dict)
    #: ISO date -> number of requests sent that day
    requests: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> UsageLedger:
        p = Path(path)
        if not p.exists():
            return cls(path=p)
        try:
            raw = json.loads(p.read_text())
            return cls(
                path=p,
                securities=dict(raw["securities"]),
                requests={k: int(v) for k, v in raw["requests"].items()},
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise LedgerError(f"corrupt usage ledger {p}: {exc}") from exc

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"securities": self.securities, "requests": self.requests},
                indent=2,
                sort_keys=True,
            )
        )

    @property
    def known_count(self) -> int:
        return len(self.securities)

    def new_securities(self, secs: Sequence[str]) -> list[str]:
        return [s for s in secs if s not in self.securities]

    def new_on(self, on: date) -> int:
        iso = on.isoformat()
        return sum(1 for d in self.securities.values() if d == iso)

    def allowance(self, on: date, max_new_per_day: int) -> int:
        return max(0, max_new_per_day - self.new_on(on))

    def record(self, secs: Sequence[str], on: date) -> None:
        iso = on.isoformat()
        for s in secs:
            self.securities.setdefault(s, iso)
        self.requests[iso] = self.requests.get(iso, 0) + 1
        self.save()
