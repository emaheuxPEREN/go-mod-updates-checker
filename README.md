# `go-mod-updates-checker`

Parse current dependencies from `go.mod` file and try to find _minor_ or _patch_ updates,
that are compatible with an upper limit for Go version.

## Installation

```shell
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

Symlink `go-mod-updates-checker` script somewhere in your `PATH`

## Usage

Within a folder containing `go.mod`: execute `go-mod-updates-checker`

### Advanced usage

Cf. help of Python commands:

```shell
python parse_go_mod.py -h
python check_latest_mod.py -h
```
