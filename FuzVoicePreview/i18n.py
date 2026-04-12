from __future__ import annotations

try:  # pragma: no cover - exercised only inside MO2 / PyQt6 runtime
    from PyQt6.QtCore import QCoreApplication
except Exception:  # pragma: no cover - local test environment does not ship PyQt6
    class QCoreApplication:  # type: ignore[no-redef]
        @staticmethod
        def translate(context: str, source_text: str, disambiguation: str | None = None, n: int = -1) -> str:
            return source_text
