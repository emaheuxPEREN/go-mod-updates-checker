# HACK: quick & dirty but OK in 99% cases

import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Self

import tyro
from semver import Version

GO_VERSION_MIN_LINE = re.compile(r"^go\s+(\d+\.\d+(?:\.\d+)?)($|\s+//.+$)")
"""Nota: full version was not required in old Go versions"""

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


@dataclass(frozen=True)
class GoMod:
    go_version_min: Version | None
    deps: list[Dep]

    @classmethod
    def new(cls, go_mod_content: str, /) -> Self:
        go_version_min: Version | None = None
        deps: list[Dep] = []
        for line in go_mod_content.splitlines():
            dep = Dep.from_line(line)
            go_version_m = GO_VERSION_MIN_LINE.match(line)
            if dep is not None:
                assert go_version_m is None, line
                deps.append(dep)
                continue
            if go_version_m is not None:
                assert go_version_min is None, (line, go_version_min)
                go_version_min = Version.parse(go_version_m.group(1), optional_minor_and_patch=True)
        return cls(go_version_min=go_version_min, deps=deps)

    def get_deps(self, to_be_included: Callable[[Dep], bool] | None = None, /) -> list[str]:
        all_deps = [d for d in self.deps if to_be_included is None or to_be_included(d)]
        return [f"{d.package}@{d.version}" for d in all_deps]


@dataclass(frozen=True)
class ParserConfig:
    """Retrieve all deps + Go min version from go.mod (stdin) and print as JSON"""

    also_indirect: Annotated[bool, tyro.conf.arg(aliases=["-i"])] = False
    only_indirect: Annotated[bool, tyro.conf.arg(aliases=["-I"])] = False

    def to_be_included(self, dep: Dep) -> bool:
        if self.only_indirect:
            return dep.indirect
        return not dep.indirect or self.also_indirect

    def parse(self) -> dict[str, Any]:
        go_mod = GoMod.new(sys.stdin.read())
        return {
            "go_version_min": str(go_mod.go_version_min or ""),
            "deps": go_mod.get_deps(self.to_be_included),
        }

    @classmethod
    def cli(cls) -> None:
        parser = tyro.cli(cls, config=[tyro.conf.FlagCreatePairsOff])
        json.dump(parser.parse(), sys.stdout, indent=2)


if __name__ == "__main__":
    ParserConfig.cli()
