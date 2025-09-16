# Docktail

Vibe Coding Alert!

---

Color-coded, multi-container `docker logs -f` with substring/exact matching, instant backlog (`--tail all`), and lifecycle banners (`+ name`/`- name`). Skips TTY/interactive containers by default to avoid shell noise—opt in with `--include-tty`.

## Features

* Tail **one** container (`--exact`) or **many** (substring match by default)
* Per-container **distinct colors**
* **Instant** first output (`--tail all` default)
* **Lifecycle banners**: `+ container` when it starts, `- container` when it stops
* **Silent** when down/not found (keeps running)
* Optionally exclude/include **TTY** containers

---

## Make it a CLI on your PATH

```bash
chmod +x docktail.py

# Put it somewhere on your PATH, e.g. ~/.bin
mkdir -p ~/.bin
cp docktail.py ~/.bin/docktail

# Ensure ~/.bin is on PATH (add this to your shell profile if needed)
export PATH="$HOME/.bin:$PATH"

# Now just:
docktail <conainter-name/container-name-substring>
```

> The shebang runs `uv` directly, which reads the `# /// script` block and sets up deps automatically.

## Usage

```bash
docktail --help
Reading inline script metadata from `~/.bin/docktail`

 Usage: docktail [OPTIONS] PATTERN

 Stream Docker logs for containers (exact or substring match).

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    pattern      TEXT  Container name (exact name or substring depending on flags). [required]                                                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --exact          --substring               Match mode (exact name vs substring). Default: substring. [default: substring]                                                            │
│ --tail                            TEXT     How many lines to show before following. Use an integer (as string) or "all". Default: all. [default: all]                                │
│ --since                           INTEGER  Only return logs since this many seconds ago (e.g., 300 = last 5 minutes).                                                                │
│ --refresh                         FLOAT    How often (seconds) to rescan for matching containers in substring mode. [default: 1.0]                                                   │
│ --include-tty    --exclude-tty             Include containers started with TTY (-t). Default excludes interactive shells. [default: exclude-tty]                                     │
│ --help                                     Show this message and exit.                                                                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯


```

Notes:

* Substring mode rescans every `--refresh` seconds to pick up newly started containers.
* If a container stops or isn’t found, Docktail remains running and prints nothing for it until it’s back.
* Colors are unique among **currently tailed** containers; if the palette is exhausted, colors will be reused.

---
