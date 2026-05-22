# HACK: quick & dirty but OK in 99% cases

import re
import sys
from dataclasses import dataclass
from typing import Annotated, Self

import tyro

DEP_LINE = re.compile(r"^(?:require)?\s+(\S+)\s+(v\d+\.\d+\.\d+(?:-dev)?)($|\s+//.+$)", flags=re.M)
"""Nota: we do NOT included unpublished versions"""


@dataclass(frozen=True)
class Dep:
    package: str
    version: str
    indirect: bool

    @classmethod
    def from_line(cls, line: str) -> Self | None:
        m = DEP_LINE.match(line.rstrip())
        if m is None:
            return None
        return cls(m.group(1), m.group(2), indirect=m.group(3).lstrip() == "// indirect")


def parse_deps(go_mod_content: str) -> list[Dep]:
    return [dep for line in go_mod_content.splitlines() if (dep := Dep.from_line(line)) is not None]


@dataclass(frozen=True)
class ReaderConfig:
    """Retrieve all deps from go.mod (stdin)"""

    also_indirect: Annotated[bool, tyro.conf.arg(aliases=["-i"])] = False
    only_indirect: Annotated[bool, tyro.conf.arg(aliases=["-I"])] = False

    def to_be_included(self, dep: Dep) -> bool:
        if self.only_indirect:
            return dep.indirect
        return not dep.indirect or self.also_indirect

    def get_all(self) -> list[str]:
        all_deps = [d for d in parse_deps(sys.stdin.read()) if self.to_be_included(d)]
        return [f"{d.package}@{d.version}" for d in all_deps]


def cli() -> None:
    reader = tyro.cli(ReaderConfig, config=[tyro.conf.FlagCreatePairsOff])
    print("\n".join(reader.get_all()))


if __name__ == "__main__":
    cli()
