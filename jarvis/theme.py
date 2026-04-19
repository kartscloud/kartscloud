from rich.theme import Theme


ACCENT = "bold #d4aa00"
DIM = "#6b6b6b"


THEME = Theme(
    {
        "accent": ACCENT,
        "dim": DIM,
        "user": ACCENT,
        "assistant": "white",
        "status": DIM,
        "header": ACCENT,
        "warn": "bold red",
        "ok": "bold green",
    }
)
