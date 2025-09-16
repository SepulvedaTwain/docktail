#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "docker",
#     "typer",
#     "rich",
# ]
# ///

import hashlib
import signal
import threading
import time
from typing import Dict, List, Optional, Set

import docker
import typer
from docker.models.containers import Container
from rich.console import Console
from rich.text import Text

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()

# Readable color styles; we pick one per container deterministically.
STYLES = [
    "bold cyan",
    "bold magenta",
    "bold green",
    "bold yellow",
    "bold blue",
    "bold red",
    "cyan",
    "magenta",
    "green",
    "yellow",
    "blue",
    "red",
    "bright_cyan",
    "bright_magenta",
    "bright_green",
    "bright_yellow",
    "bright_blue",
    "bright_red",
]


def hashed_index(name: str) -> int:
    return int(hashlib.sha256(name.encode("utf-8")).hexdigest(), 16) % len(STYLES)


def assign_style(name: str, used_styles: Set[str]) -> str:
    """
    Pick a style for `name`:
      1) Start from a deterministic hash index.
      2) Choose the first style not currently in use by any live worker.
      3) If all are in use, reuse the hashed style.
    """
    start = hashed_index(name)
    for off in range(len(STYLES)):
        candidate = STYLES[(start + off) % len(STYLES)]
        if candidate not in used_styles:
            return candidate
    # All styles used -> reuse hashed one
    return STYLES[start]


class LogWorker(threading.Thread):
    """
    Continuously attempts to stream logs for a single container.
    If the container is not running or disappears, it prints nothing and keeps retrying.
    Also prints lifecycle banners:
      + <name> when the container becomes running (and we attach)
      - <name> when it stops running (on next poll after it stops)
    """

    def __init__(
        self,
        client: docker.DockerClient,
        container_name: str,
        style: str,
        tail: str = "all",  # "all" or integer-as-string; parsed upstream
        since: Optional[int] = None,
        poll_sleep: float = 0.5,
        stop_event: Optional[threading.Event] = None,
    ):
        super().__init__(daemon=True)
        self.client = client
        self.container_name = container_name
        self.style = style
        self.tail = tail
        self.since = since
        self.poll_sleep = poll_sleep
        self.stop_event = stop_event or threading.Event()
        self._attached_running = False  # tracks whether we were attached to a running container

    def _banner(self, prefix: str):
        # Print a colored lifecycle banner: "+ name" or "- name"
        console.print(Text(f"{prefix} {self.container_name}", style=self.style))

    def run(self) -> None:
        while not self.stop_event.is_set():
            # Try to resolve the container
            try:
                container = self.client.containers.get(self.container_name)
            except docker.errors.NotFound:
                # If we previously were attached and container vanished, treat as stop event
                if self._attached_running:
                    self._banner("-")
                    self._attached_running = False
                time.sleep(self.poll_sleep)
                continue
            except Exception:
                time.sleep(self.poll_sleep)
                continue

            # Reload status; if not running, emit stop banner once and wait
            try:
                container.reload()
            except Exception:
                time.sleep(self.poll_sleep)
                continue

            if container.status != "running":
                if self._attached_running:
                    self._banner("-")
                    self._attached_running = False
                time.sleep(self.poll_sleep)
                continue

            # We're running here
            if not self._attached_running:
                # Transition: not running -> running
                self._banner("+")
                self._attached_running = True

            # Attach to logs stream
            try:
                stream_kwargs = dict(stream=True, follow=True, stdout=True, stderr=True)
                stream_kwargs["tail"] = self.tail  # "all" or numeric string
                if self.since is not None:
                    stream_kwargs["since"] = self.since

                for chunk in container.logs(**stream_kwargs):
                    if self.stop_event.is_set():
                        break
                    try:
                        line = chunk.decode("utf-8", errors="replace").rstrip("\n")
                    except Exception:
                        line = str(chunk)
                    if line:
                        # Color the entire line for this container
                        console.print(Text(f"[{self.container_name}] {line}", style=self.style))
                # When the stream ends (e.g., container stopped), we don't know state yet.
                # Next loop iteration will reload() and print "-" if it actually stopped.
            except docker.errors.APIError:
                time.sleep(self.poll_sleep)
            except Exception:
                time.sleep(self.poll_sleep)


def is_tty_container(c: Container) -> bool:
    try:
        c.reload()
        cfg = c.attrs.get("Config", {})
        # If TTY or OpenStdin is enabled, treat as interactive
        return bool(cfg.get("Tty") or cfg.get("OpenStdin"))
    except Exception:
        return False


def find_matching_containers(
    client: docker.DockerClient, pattern: str, exact: bool, include_tty: bool
) -> List[Container]:
    all_containers = client.containers.list(all=True)
    if exact:
        matches = [c for c in all_containers if c.name == pattern]
    else:
        p = pattern.lower()
        matches = [c for c in all_containers if p in c.name.lower()]
    if not include_tty:
        matches = [c for c in matches if not is_tty_container(c)]
    return matches


def ensure_workers_for_matches(
    client: docker.DockerClient,
    pattern: str,
    exact: bool,
    tail: str,
    since: Optional[int],
    include_tty: bool,
    active_workers: Dict[str, LogWorker],
    stop_event: threading.Event,
) -> None:
    matches = find_matching_containers(client, pattern, exact, include_tty)

    # Build the set of styles currently in use by alive workers (so we can avoid duplicates)
    used_styles: Set[str] = {w.style for w in active_workers.values() if w.is_alive()}

    for c in matches:
        name = c.name
        # Start a worker if needed
        if name not in active_workers or not active_workers[name].is_alive():
            style = assign_style(name, used_styles)
            used_styles.add(style)
            worker = LogWorker(
                client=client,
                container_name=name,
                style=style,
                tail=tail,
                since=since,
                stop_event=stop_event,
            )
            active_workers[name] = worker
            worker.start()


@app.command(help="Stream Docker logs for containers (exact or substring match).")
def logs(
    pattern: str = typer.Argument(
        ...,
        help="Container name (exact name or substring depending on flags).",
    ),
    exact: bool = typer.Option(
        False,
        "--exact/--substring",
        help="Match mode (exact name vs substring). Default: substring.",
    ),
    tail: str = typer.Option(
        "all",
        help='How many lines to show before following. Use an integer (as string) or "all". Default: all.',
    ),
    since: Optional[int] = typer.Option(
        None,
        help="Only return logs since this many seconds ago (e.g., 300 = last 5 minutes).",
    ),
    refresh: float = typer.Option(1.0, help="How often (seconds) to rescan for matching containers in substring mode."),
    include_tty: bool = typer.Option(
        False,
        "--include-tty/--exclude-tty",
        help="Include containers started with TTY (-t). Default excludes interactive shells.",
    ),
):
    """
    - If a container is DOWN / NOT FOUND → prints nothing but keeps running.
    - Substring mode tails ALL matching containers concurrently (distinct colors per container).
    - Exact mode tails only the specified container name.
    - Default tail is 'all' so you won't miss initial logs.
    - Prints '+ <name>' when a container becomes running, and '- <name>' when it stops.
    - Colors are unique until the palette is exhausted; then they may repeat.
    - By default, TTY/interactive containers are excluded to avoid shell session noise.
    """
    # Validate tail
    if tail != "all":
        if not tail.isdigit() or int(tail) < 0:
            raise typer.BadParameter('tail must be a non-negative integer (as string) or "all"')

    client = docker.from_env()
    stop_event = threading.Event()
    active_workers: Dict[str, LogWorker] = {}

    def handle_stop(signum, frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    # Initial spawn
    ensure_workers_for_matches(client, pattern, exact, tail, since, include_tty, active_workers, stop_event)

    # Warn if exact target is TTY but excluded
    if exact:
        matches = find_matching_containers(client, pattern, True, True)  # include tty to check
        if matches and is_tty_container(matches[0]) and not include_tty:
            console.print(
                f"[yellow]Container '{matches[0].name}' has TTY enabled; logs are skipped by default. "
                f"Use --include-tty to force following interactive streams.[/]"
            )

    # Main loop: rescan (substring) or retry (exact) quietly
    try:
        last_refresh = 0.0
        while not stop_event.is_set():
            now = time.time()
            if not exact and (now - last_refresh >= refresh):
                ensure_workers_for_matches(client, pattern, exact, tail, since, include_tty, active_workers, stop_event)
                last_refresh = now

            if exact and not active_workers:
                # Keep trying to attach in exact mode without printing noise
                ensure_workers_for_matches(client, pattern, exact, tail, since, include_tty, active_workers, stop_event)

            time.sleep(0.2)
    finally:
        stop_event.set()
        for w in list(active_workers.values()):
            w.join(timeout=2.0)


if __name__ == "__main__":
    app()
