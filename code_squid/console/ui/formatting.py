"""Low-level terminal formatting shared by Code Squid console presentation."""

from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import textwrap

from wcwidth import wcwidth, wcswidth


PATH_LABEL_MAX = 56
DISPLAY_WRAP_WIDTH = 64
FINAL_SUMMARY_INDENT = "  "
DIM_STYLE = "\033[2m"
BOLD_STYLE = "\033[1m"
RESET_STYLE = "\033[0m"
# Force text presentation so terminal foreground color applies to the squid.
# Color-emoji fonts commonly ignore ANSI foreground styles on the default glyph.
SQUID_GLYPH = "\U0001f991\ufe0e"
SOFT_CYAN_HEX = "#7dd3fc"
SOFT_GREEN_HEX = "#86efac"
SOFT_YELLOW_HEX = "#ffea80"
SOFT_RED_HEX = "#f77998"

# Mods own only a semantic accent name. The exact product palette stays here
# in Code Squid's presentation layer rather than leaking into reusable Core.
MOD_ACCENT_HEX = {
    "cyan": "#3edcff",
    "blue": "#5d9cff",
    "green": "#55e6a5",
    "yellow": "#ffe06a",
    "orange": "#ff9b55",
    "red": "#ff6475",
    "pink": "#ff75c8",
    "purple": "#bd88ff",
    "white": "#f4fbff",
    "gray": "#a8b7c5",
}
DEFAULT_MOD_ACCENT_HEX = MOD_ACCENT_HEX["cyan"]


def ansi_fg(hex_color: str) -> str:
    """Return a true-color ANSI foreground escape for a hex color."""
    value = hex_color.removeprefix("#")
    r = int(value[0:2], 16)
    g = int(value[2:4], 16)
    b = int(value[4:6], 16)
    return f"\033[38;2;{r};{g};{b}m"


def mod_accent_hex(accent_name: str | None) -> str:
    """Resolve a Mod's semantic accent name through the product palette."""
    return MOD_ACCENT_HEX.get(accent_name or "", DEFAULT_MOD_ACCENT_HEX)


SOFT_CYAN_STYLE = ansi_fg(SOFT_CYAN_HEX)
SOFT_GREEN_STYLE = ansi_fg(SOFT_GREEN_HEX)
SOFT_YELLOW_STYLE = ansi_fg(SOFT_YELLOW_HEX)
SOFT_RED_STYLE = ansi_fg(SOFT_RED_HEX)


def terminal_link(label: str, uri: str) -> str:
    """Wrap a label in an OSC 8 terminal hyperlink."""
    return f"\033]8;;{uri}\033\\{label}\033]8;;\033\\"


def file_link(path: str, label: str | None = None) -> str:
    """Return a clickable local-file label when stdout is interactive."""
    label = path if label is None else label
    if not sys.stdout.isatty():
        return label

    try:
        uri = Path(path).expanduser().resolve().as_uri()
    except (OSError, RuntimeError, ValueError):
        return label

    return terminal_link(label, uri)


def styled_text(text: str, *styles: str) -> str:
    """Apply ANSI styles only for interactive terminal output."""
    styles = tuple(style for style in styles if style)
    if not styles or not sys.stdout.isatty():
        return text
    return f"{''.join(styles)}{text}{RESET_STYLE}"


def structural_text(text: str) -> str:
    """Style terminal structure such as rails and borders."""
    return styled_text(text, SOFT_CYAN_STYLE)


def structural_prefix(prefix: str, text: str) -> str:
    """Style only the structural prefix of a line."""
    if not sys.stdout.isatty():
        return f"{prefix}{text}"
    return f"{SOFT_CYAN_STYLE}{prefix}{RESET_STYLE}{text}"


def structural_bordered_line(left: str, content: str, right: str) -> str:
    """Style the borders of a content line without styling its contents."""
    if not sys.stdout.isatty():
        return f"{left}{content}{right}"
    return (
        f"{SOFT_CYAN_STYLE}{left}{RESET_STYLE}"
        f"{content}"
        f"{SOFT_CYAN_STYLE}{right}{RESET_STYLE}"
    )


def single_line(value: object) -> str:
    """Collapse a value to one display line without changing the source value."""
    return " ".join(str(value).splitlines())


def truncate_middle(value: str, max_length: int) -> str:
    """Fit a value by replacing its middle with one ellipsis."""
    if len(value) <= max_length:
        return value
    if max_length <= 1:
        return "…"[:max_length]

    keep = max_length - 1
    left = keep // 2
    right = keep - left
    return f"{value[:left]}…{value[-right:]}"


def parent_file_label(path: Path | PurePosixPath) -> str:
    """Return a compact parent/file label for an absolute external path."""
    parent = path.parent.name
    if not parent:
        return path.name
    return PurePosixPath(parent, path.name).as_posix()


def short_path(path: str, display_root: Path) -> str:
    """Shorten a path relative to the displayed workspace when possible."""
    if not path:
        return ""

    raw_path = str(path)
    try:
        path_obj = Path(raw_path).expanduser()
        if path_obj.is_absolute():
            resolved_path = path_obj.resolve()
            try:
                display_path = resolved_path.relative_to(display_root).as_posix()
            except ValueError:
                display_path = parent_file_label(resolved_path)
        elif PurePosixPath(raw_path).is_absolute():
            display_path = parent_file_label(PurePosixPath(raw_path))
        else:
            display_path = path_obj.as_posix()
    except (OSError, ValueError):
        display_path = raw_path

    if len(display_path) <= PATH_LABEL_MAX:
        return display_path

    parts = PurePosixPath(display_path).parts
    if PurePosixPath(display_path).is_absolute() and len(parts) >= 3:
        return truncate_middle("/".join(("…", *parts[-2:])), PATH_LABEL_MAX)
    return truncate_middle(display_path, PATH_LABEL_MAX)


def wrapped_display_lines(
    text: str,
    initial_indent: str,
    subsequent_indent: str,
    width: int | None = None,
) -> list[str]:
    """Wrap display text to the configured or current terminal width."""
    if not text:
        return [""]

    wrap_width = width
    if wrap_width is None:
        wrap_width = min(
            DISPLAY_WRAP_WIDTH,
            shutil.get_terminal_size(fallback=(DISPLAY_WRAP_WIDTH, 24)).columns,
        )
    lines = textwrap.wrap(
        text,
        width=max(wrap_width, 1),
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        # Fixed-width panels must also contain paths and other unspaced text.
        # Keep the historical terminal-width behavior for non-panel callers.
        break_long_words=width is not None,
        break_on_hyphens=False,
    )
    if width is None:
        return lines

    cell_wrapped: list[str] = []
    for line_index, line in enumerate(lines):
        indent = initial_indent if line_index == 0 else subsequent_indent
        payload = line.removeprefix(indent)
        chunk_indent = indent
        while payload:
            available_cells = max(width - wcswidth(chunk_indent), 1)
            chunk, payload = _take_display_cells(payload, available_cells)
            cell_wrapped.append(f"{chunk_indent}{chunk}")
            chunk_indent = subsequent_indent
    return cell_wrapped


def _take_display_cells(text: str, width: int) -> tuple[str, str]:
    """Take a prefix that fits within a terminal-cell width."""
    current_width = 0
    for index, character in enumerate(text):
        character_width = max(wcwidth(character), 0)
        if index and current_width + character_width > width:
            return text[:index], text[index:]
        current_width += character_width
    return text, ""


def render_inline_markdown(text: str) -> str:
    """Render the small inline Markdown subset supported by final reports."""
    if "**" not in text or not sys.stdout.isatty():
        return text

    parts = re.split(r"(\*\*[^*\n]+\*\*)", text)
    rendered_parts: list[str] = []
    for part in parts:
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            rendered_parts.append(styled_text(part[2:-2], BOLD_STYLE))
            continue
        rendered_parts.append(part)
    return "".join(rendered_parts)


def markdown_display_lines(line: str, width: int | None = None) -> list[str]:
    """Render and wrap one final-report Markdown line."""
    heading_match = re.match(r"^\s{0,3}(#{2,3})\s+(.+?)\s*#*\s*$", line)
    if heading_match:
        level, heading = heading_match.groups()
        indent = FINAL_SUMMARY_INDENT if level == "##" else f"{FINAL_SUMMARY_INDENT}  "
        if width is None:
            return [f"{indent}{styled_text(heading, BOLD_STYLE)}"]
        return [
            f"{indent}{styled_text(part.removeprefix(indent), BOLD_STYLE)}"
            for part in wrapped_display_lines(
                heading,
                initial_indent=indent,
                subsequent_indent=indent,
                width=width,
            )
        ]

    stripped = line.lstrip()
    unordered_bullet_match = re.match(r"^([-*+])\s+(.+)$", stripped)
    if unordered_bullet_match:
        return [
            render_inline_markdown(part)
            for part in wrapped_display_lines(
                unordered_bullet_match.group(2),
                initial_indent=f"{FINAL_SUMMARY_INDENT}• ",
                subsequent_indent=f"{FINAL_SUMMARY_INDENT}  ",
                width=width,
            )
        ]

    numbered_bullet_match = re.match(r"^(\d+\.\s+)(.+)$", stripped)
    if numbered_bullet_match:
        marker = numbered_bullet_match.group(1)
        rendered = f"{marker}{numbered_bullet_match.group(2)}"
        return [
            render_inline_markdown(part)
            for part in wrapped_display_lines(
                rendered,
                initial_indent=FINAL_SUMMARY_INDENT,
                subsequent_indent=f"{FINAL_SUMMARY_INDENT}{' ' * len(marker)}",
                width=width,
            )
        ]

    return [
        render_inline_markdown(part)
        for part in wrapped_display_lines(
            stripped,
            initial_indent=FINAL_SUMMARY_INDENT,
            subsequent_indent=FINAL_SUMMARY_INDENT,
            width=width,
        )
    ]


def format_final_summary(content: str, width: int | None = None) -> str:
    """Render the supported final-report Markdown while preserving its layout."""
    formatted_lines: list[str] = []
    previous_rendered_bullet = False
    for line in content.splitlines():
        rendered_lines = markdown_display_lines(line, width=width)
        is_rendered_bullet = bool(rendered_lines) and rendered_lines[0].startswith(
            f"{FINAL_SUMMARY_INDENT}• "
        )
        if is_rendered_bullet and previous_rendered_bullet:
            formatted_lines.append("")
        formatted_lines.extend(rendered_lines)
        previous_rendered_bullet = is_rendered_bullet

    return "\n".join(formatted_lines).strip("\n")
