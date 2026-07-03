"""Bloomberg session seam (M6 spec §4).

``SessionLike`` is what the fetch pipeline types against; tests inject a fake.
The real ``BlpSession`` (added with the CLI task) is the ONLY code in the repo
that imports ``blpapi`` — lazily, so the package is an optional dependency.
"""
from __future__ import annotations

from datetime import date
from typing import Protocol, Sequence, runtime_checkable

import pandas as pd


class BloombergError(RuntimeError):
    """Bloomberg session/API failure with an actionable message."""


@runtime_checkable
class SessionLike(Protocol):
    """The two Bloomberg operations the M6 pipeline needs."""

    def index_members(self, index_security: str, on: date) -> list[str]:
        """Index members as of ``on`` (INDX_MWEIGHT_HIST with END_DATE_OVERRIDE)."""
        ...

    def daily_bars(
        self, securities: Sequence[str], start: date, end: date
    ) -> dict[str, pd.DataFrame]:
        """Raw daily OHLCV per security; securities with no data are absent."""
        ...


_PX_FIELDS = {
    "PX_OPEN": "open",
    "PX_HIGH": "high",
    "PX_LOW": "low",
    "PX_LAST": "close",
    "PX_VOLUME": "volume",
}
_INSTALL_HINT = (
    "blpapi is not installed. Run:\n"
    "  pip install blpapi --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/"
)
_CONNECT_HINT = (
    "cannot reach the Bloomberg Desktop API on {host}:{port} — "
    "make sure the Terminal is running and you are logged in, then retry"
)


class BlpSession:
    """Real Desktop-API session (implements SessionLike). The ONLY blpapi user."""

    def __init__(self, host: str = "localhost", port: int = 8194) -> None:
        try:
            import blpapi
        except ImportError as exc:  # pragma: no cover - needs Bloomberg install
            raise BloombergError(_INSTALL_HINT) from exc
        self._blpapi = blpapi
        opts = blpapi.SessionOptions()
        opts.setServerHost(host)
        opts.setServerPort(port)
        self._session = blpapi.Session(opts)
        if not self._session.start() or not self._session.openService("//blp/refdata"):
            raise BloombergError(_CONNECT_HINT.format(host=host, port=port))
        self._svc = self._session.getService("//blp/refdata")

    def close(self) -> None:
        self._session.stop()

    # -- SessionLike -----------------------------------------------------------

    def index_members(self, index_security: str, on: date) -> list[str]:
        req = self._svc.createRequest("ReferenceDataRequest")
        req.getElement("securities").appendValue(index_security)
        req.getElement("fields").appendValue("INDX_MWEIGHT_HIST")
        override = req.getElement("overrides").appendElement()
        override.setElement("fieldId", "END_DATE_OVERRIDE")
        override.setElement("value", on.strftime("%Y%m%d"))
        members: list[str] = []
        for msg in self._responses(req):
            sdata = msg.getElement("securityData")
            for i in range(sdata.numValues()):
                fdata = sdata.getValueAsElement(i).getElement("fieldData")
                if not fdata.hasElement("INDX_MWEIGHT_HIST"):
                    continue
                hist = fdata.getElement("INDX_MWEIGHT_HIST")
                for j in range(hist.numValues()):
                    members.append(
                        hist.getValueAsElement(j).getElementAsString("Index Member")
                    )
        return members

    def daily_bars(
        self, securities: Sequence[str], start: date, end: date
    ) -> dict[str, pd.DataFrame]:
        req = self._svc.createRequest("HistoricalDataRequest")
        for sec in securities:
            req.getElement("securities").appendValue(sec)
        for f in _PX_FIELDS:
            req.getElement("fields").appendValue(f)
        req.set("startDate", start.strftime("%Y%m%d"))
        req.set("endDate", end.strftime("%Y%m%d"))
        req.set("periodicitySelection", "DAILY")
        # Split + normal-dividend adjusted, matching Phase-1 yfinance auto_adjust (D6).
        req.set("adjustmentSplit", True)
        req.set("adjustmentNormal", True)
        req.set("adjustmentAbnormal", False)
        out: dict[str, pd.DataFrame] = {}
        for msg in self._responses(req):
            sdata = msg.getElement("securityData")
            sec = sdata.getElementAsString("security")
            if sdata.hasElement("securityError"):
                continue  # recorded as a failure by the caller
            fdata = sdata.getElement("fieldData")
            rows = []
            for i in range(fdata.numValues()):
                e = fdata.getValueAsElement(i)
                if not all(e.hasElement(f) for f in _PX_FIELDS):
                    continue
                row = {name: e.getElementAsFloat(f) for f, name in _PX_FIELDS.items()}
                row["date"] = e.getElementAsDatetime("date")
                rows.append(row)
            if rows:
                out[sec] = pd.DataFrame(rows).set_index("date")
        return out

    def _responses(self, req):  # type: ignore[no-untyped-def]  # blpapi is untyped
        self._session.sendRequest(req)
        while True:
            event = self._session.nextEvent(30_000)
            if event.eventType() in (
                self._blpapi.Event.RESPONSE,
                self._blpapi.Event.PARTIAL_RESPONSE,
            ):
                for msg in event:
                    if msg.hasElement("responseError"):
                        raise BloombergError(str(msg.getElement("responseError")))
                    yield msg
            if event.eventType() == self._blpapi.Event.RESPONSE:
                return
