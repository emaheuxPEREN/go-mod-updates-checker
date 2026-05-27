import re
import subprocess
from dataclasses import dataclass
from functools import cached_property
from typing import Annotated, Literal, Self

import requests
import requests.adapters
import tyro
from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, ConfigDict, Field, PlainSerializer, computed_field
from semver import Version
from urllib3.util.retry import Retry

API_BASE_URL = "https://pkg.go.dev/v1beta"
"""Ref: <https://pkg.go.dev/v1beta/api>"""


GO_VERSION_DEFAULT = subprocess.check_output(["go", "env", "GOVERSION"], text=True).strip().removeprefix("go")


@dataclass(frozen=True, kw_only=True)
class RetryableAPI:
    retry: Retry = Retry(
        total=5,
        status_forcelist=[429],
        allowed_methods=["GET"],
        backoff_factor=1,  # exponential backoff: 1s, 2s, 4s...
        respect_retry_after_header=True,
    )

    @cached_property
    def session(self) -> requests.Session:
        s = requests.Session()
        adapter = requests.adapters.HTTPAdapter(max_retries=self.retry)
        s.mount("https://", adapter)
        return s

    def get(self, endpoint: str, /, *, params: dict[str, str | None]) -> requests.Response:
        assert endpoint.startswith("/"), endpoint
        return self.session.get(API_BASE_URL + endpoint, params=params)


REQUESTER = RetryableAPI()


class GoModListOrigin(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    URL: AnyHttpUrl
    Ref: str


class GoModListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    GoVersion: str | None = None
    Origin: GoModListOrigin | None = None

    @classmethod
    def get(cls, pkg: str, version: str) -> Self:
        cmd = ["go", "list", "-m", "-json", f"{pkg}@{version}"]
        out = subprocess.check_output(cmd, text=True)
        try:
            return cls.model_validate_json(out)
        except Exception as e:
            e.add_note(f"$ {subprocess.list2cmdline(cmd)}\n{out}")
            raise


def _as_go_pkg_url(pkg: str) -> str:
    return f"https://pkg.go.dev/{pkg}"


def _is_false(v: bool | None) -> bool:
    return not v


class VersionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    modulePath: Annotated[str, PlainSerializer(_as_go_pkg_url)]
    repoUrl: AnyHttpUrl | None = None  # lazy added from details
    version: str  # startswith 'v' prefix
    # latestVersion: str # confusing

    commitTime: AwareDatetime
    goVersionMin: str | None = None  # lazy added from details

    deprecated: Annotated[bool, Field(exclude_if=_is_false)]
    retracted: Annotated[bool, Field(exclude_if=_is_false)]

    @computed_field(exclude_if=_is_false)
    def prerelease(self) -> bool:
        return self.version_parsed.prerelease is not None

    @cached_property
    def version_parsed(self) -> Version:
        return Version.parse(self.version.removeprefix("v"), optional_minor_and_patch=False)

    @cached_property
    def go_version_min_parsed(self) -> Version:
        assert self.goVersionMin is not None, self
        return Version.parse(self.goVersionMin.removeprefix("go"), optional_minor_and_patch=True)

    def add_details(self) -> None:
        details = GoModListResponse.get(self.modulePath, self.version)
        if details.GoVersion is not None:
            self.goVersionMin = f"go{details.GoVersion}"  # less ambiguous in output
        if details.Origin is not None:
            tag = details.Origin.Ref.removeprefix("refs/tags/")
            self.repoUrl = AnyHttpUrl(f"{details.Origin.URL}/tree/{tag}")


class VersionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total: int
    nextPageToken: str | None = None
    items: list[VersionResult]


@dataclass(frozen=True, kw_only=True)
class VersionsRequest:
    package: str
    filter: str

    def _get_one(self, token: str | None = None) -> VersionsResponse:
        r = REQUESTER.get(
            f"/versions/{self.package}",
            params={"token": token, "filter": self.filter},
        )
        r.raise_for_status()
        return VersionsResponse.model_validate_json(r.content)

    def get_all(self) -> list[VersionResult]:
        versions: list[VersionResult] = []
        token: str | None = None
        while True:
            resp = self._get_one(token)
            versions += resp.items
            token = resp.nextPageToken
            if token is None:
                break
        return versions


@dataclass(frozen=True)
class LatestVersionRequest:
    """Get metadata about the latest version of a package (minor or patch)"""

    package_at_version: str
    """Package @ current version, example: 'github.com/org/name@v1.2.3'"""

    go_version_max: Annotated[str | None, tyro.conf.arg(aliases=["--go"])] = GO_VERSION_DEFAULT
    """Maximum Go version admitted for packages, use empty string to allow any Go version"""

    keep: Annotated[Literal["major", "minor"], tyro.conf.arg(aliases=["-k"])] = "minor"
    """Keep either: minor = x.y.* or major = x.*"""

    prerelease_ok: bool = False
    deprecated_ok: bool = False
    retracted_ok: bool = False

    only_outdated: bool = False
    """Only print metadata if provided version is outdated"""

    @cached_property
    def package_and_version(self) -> tuple[str, Version]:
        assert not re.search(r"\s", self.package_at_version), self.package_at_version
        package, version = self.package_at_version.rsplit("@", maxsplit=1)
        return package, Version.parse(version.removeprefix("v"), optional_minor_and_patch=True)

    @cached_property
    def go_version_max_parsed(self) -> Version:
        assert self.go_version_max is not None
        return Version.parse(self.go_version_max.removeprefix("go").removeprefix("v"), optional_minor_and_patch=True)

    @cached_property
    def filter(self) -> str:
        _, version = self.package_and_version
        version_prefix = f"v{version.major}."
        if self.keep != "major":
            version_prefix += f"{version.minor}."
        return f'hasPrefix(version,"{version_prefix}")'

    def to_be_included(self, v: VersionResult, /) -> bool:
        return (
            (not v.prerelease or self.prerelease_ok)  # type: ignore[truthy-function]
            and (not v.deprecated or self.deprecated_ok)
            and (not v.retracted or self.retracted_ok)
        )

    def __call__(self) -> VersionResult:
        pkg, _ = self.package_and_version
        all_versions = sorted(
            [v for v in VersionsRequest(package=pkg, filter=self.filter).get_all() if self.to_be_included(v)],
            key=lambda v: v.version_parsed,
            reverse=True,
        )
        if not all_versions:
            raise ValueError(f"{self.package_at_version}: no matching version, try --deprecated-ok")
        if not self.go_version_max:
            return all_versions[0]
        min_go_version: Version | None = None
        for v in all_versions:
            v.add_details()
            # we assume no constraint when go version is NOT specified in package go.mod
            if v.goVersionMin is None or v.go_version_min_parsed <= self.go_version_max_parsed:
                return v
            if min_go_version is None or v.go_version_min_parsed < min_go_version:
                min_go_version = v.go_version_min_parsed
        assert min_go_version is not None
        raise ValueError(f"{self.package_at_version}: no matching version, minimum Go version = {min_go_version}")

    @classmethod
    def cli(cls) -> None:
        req = tyro.cli(
            cls,
            config=[
                tyro.conf.PositionalRequiredArgs,
                tyro.conf.FlagCreatePairsOff,
                tyro.conf.DisallowNone,
            ],
        )
        res = req()
        if req.only_outdated and res.version_parsed == req.package_and_version[1]:
            return
        print(res.model_dump_json(indent=2, exclude_none=True))


if __name__ == "__main__":
    LatestVersionRequest.cli()
