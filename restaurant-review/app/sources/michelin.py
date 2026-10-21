"""Michelin Guide status, from CSVs you maintain (Michelin has no public API).

One file per market: data/michelin_us.csv and data/michelin_tw.csv. Update them after each
guide release. Columns:
    name, name_zh, city, distinction, year
name_zh is optional (mainly for Taiwan). city may list aliases separated by "|",
e.g. "Taipei|台北|臺北" or "New York|Brooklyn".
distinction is one of: 3 Stars, 2 Stars, 1 Star, Bib Gourmand, Selected
"""
import csv
import logging
from dataclasses import dataclass
from pathlib import Path

from app.matching import normalize, similarity

log = logging.getLogger(__name__)


@dataclass
class MichelinEntry:
    name: str
    name_zh: str
    city: str
    distinction: str
    year: str


class Michelin:
    name = "michelin"

    def __init__(self, csv_path: str):
        self.entries: list[MichelinEntry] = []
        path = Path(csv_path)
        if not path.is_absolute():
            # Relative paths are relative to the project folder, not wherever the server was started.
            path = Path(__file__).resolve().parents[2] / path
        if path.exists():
            with path.open(encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if (row.get("name") or row.get("name_zh")) and row.get("distinction"):
                        self.entries.append(MichelinEntry(**{k: (row.get(k) or "").strip() for k in MichelinEntry.__annotations__}))
        log.info("michelin list loaded", extra={"entries": len(self.entries), "path": str(path)})

    @property
    def enabled(self) -> bool:
        return bool(self.entries)

    def lookup(self, name: str, address: str = "") -> MichelinEntry | None:
        best, best_score = None, 0.0
        addr = normalize(address)
        for e in self.entries:
            score = max(similarity(name, e.name) if e.name else 0, similarity(name, e.name_zh) if e.name_zh else 0)
            if score < 0.85:
                continue
            # The city must appear in the address, so a starred "Joe's" in Chicago doesn't
            # label every "Joe's" in the country. City can list aliases: "Taipei|台北|臺北".
            if e.city and addr:
                aliases = [normalize(c) for c in e.city.split("|") if c.strip()]
                if not any(a and a in addr for a in aliases):
                    continue
            if score > best_score:
                best, best_score = e, score
        return best
