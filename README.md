# `go-mod-updates-checker`

Parse current dependencies from `go.mod` file and try to find _minor_ or _patch_ updates,
that are compatible with an upper limit for Go version.

## Installation

```shell
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

## Usage

```shell
python parse_go_mod.py < go.mod | xargs -P 8 -I{} python check_latest_mod.py --only-outdated --go 1.24 "{}"
```

Additional flags for commands:

```shell
python parse_go_mod.py -h
python check_latest_mod.py -h
```
