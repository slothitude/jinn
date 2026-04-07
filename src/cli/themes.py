"""Theme constants for the Rich CLI renderer."""

# Agent type -> emoji icon
AGENT_ICONS: dict[str, str] = {
    "ORCHESTRATOR": "\U0001f451",
    "SUPERVISOR": "\U0001f4cb",
    "BUDDY": "\U0001f916",
    "ULTRAPLAN": "\U0001f9e0",
    "KAIROS": "\U0001f441",
    "SYSTEM": "\u2699",
}

# Agent type -> Rich color string
AGENT_COLORS: dict[str, str] = {
    "ORCHESTRATOR": "bold magenta",
    "SUPERVISOR": "bold cyan",
    "BUDDY": "bold green",
    "ULTRAPLAN": "bold yellow",
    "KAIROS": "bold red",
    "SYSTEM": "dim",
}

# Status -> unicode symbol
STATUS_ICONS: dict[str, str] = {
    "running": "\u25cf",
    "thinking": "\u25d0",
    "streaming": "\u25cf",
    "queued": "\u25cc",
    "done": "\u2713",
    "error": "\u2717",
    "interrupted": "\u26a0",
}

# Status -> Rich color string
STATUS_COLORS: dict[str, str] = {
    "running": "cyan",
    "thinking": "yellow",
    "streaming": "green",
    "queued": "dim",
    "done": "green",
    "error": "bold red",
    "interrupted": "bold yellow",
}

# Tool name -> emoji
TOOL_ICONS: dict[str, str] = {
    "bash": "\u26a1",
    "read": "\U0001f4d6",
    "write": "\U0001f4dd",
    "web_search": "\U0001f50d",
    "web_crawl": "\U0001f310",
    "web_summarize": "\U0001f4ca",
    "web_ask": "\u2753",
    "web_see": "\U0001f441",
    "web_look": "\U0001f50d",
    "delegate_batch": "\U0001f4cb",
    "spawn_workers": "\U0001f465",
}

# ASCII art Slothitude Games: Jinn logo (pure ASCII for Windows compat)
JINN_LOGO: list[str] = [
    "  _____ _       _   _                   _     _   ",
    " / ____| |     | | | |                 | |   | |  ",
    "| (___ | |_ ___| | | | ___ _   _ _ __ | | __| |_ ",
    " \\___ \\| __/ _ \\ | | |/ _ \\ | | | '_ \\| |/ _` __|",
    " ____) | ||  __/ | | |  __/ |_| | | | | | (_| |_ ",
    "|_____/ \\__\\___|_| |_|\\___|\\__,_|_| |_|_|\\__,\\__|",
    "                                                  ",
    "      _____           _                           ",
    "     / ____|         | |                          ",
    "    | (___   ___ __ _| | ___  ___                 ",
    "     \\___ \\ / __/ _` | |/ _ \\/ __|               ",
    "     ____) | (_| (_| | |  __/\\__ \\               ",
    "    |_____/ \\___\\__,_|_|\\___||___/               ",
    "                                                  ",
]

# Characters for matrix rain effect (ASCII-safe: symbols + hex digits)
MATRIX_CHARS: str = (
    "0123456789ABCDEFabcdef@#$%&*+=~-:;!?/\\|<>{}[]()^"
)

# Max refresh rate (15fps)
REFRESH_INTERVAL: float = 0.066
