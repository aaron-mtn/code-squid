"""Low-level terminal formatting shared by Code Squid console presentation."""

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import textwrap

from wcwidth import wcwidth, wcswidth


RUN_PANEL_WIDTH = 65
RUN_PANEL_CONTENT_WIDTH = 56
PATH_LABEL_MAX = 56
DISPLAY_WRAP_WIDTH = 64
FINAL_SUMMARY_INDENT = "  "
DIM_STYLE = "\033[2m"
BOLD_STYLE = "\033[1m"
ITALIC_STYLE = "\033[3m"
STRIKETHROUGH_STYLE = "\033[9m"
RESET_STYLE = "\033[0m"
RECOVERABLE_STATUS_ICON = "🌀"
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

# Keep terminal control sequences out of every cell-width calculation. OSC 8
# links are especially important here because their URI can dwarf the label.
ANSI_ESCAPE_PATTERN = re.compile(
    r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x1b]*(?:\x1b\\|\x07))"
)


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


def display_width(value: str) -> int:
    """Return terminal cell width after removing ANSI and OSC sequences."""
    plain = ANSI_ESCAPE_PATTERN.sub("", value)
    width = wcswidth(plain)
    return len(plain) if width < 0 else width


@dataclass(frozen=True)
class _InlineRun:
    """A visible inline fragment plus presentation applied after wrapping."""

    text: str
    styles: tuple[str, ...] = ()
    link: str | None = None


_ESCAPABLE_MARKDOWN = r"\`*_{}[]()#+-.!|>~"


def _inline_runs(text: str) -> list[_InlineRun]:
    """Parse a deliberately small, streaming-safe inline Markdown subset."""
    if not sys.stdout.isatty():
        # Redirected output historically retained inline Markdown source. Keep
        # that useful transcript behavior while interactive terminals style it.
        return [_InlineRun(text)]

    runs: list[_InlineRun] = []
    plain: list[str] = []

    def flush() -> None:
        if plain:
            runs.append(_InlineRun("".join(plain)))
            plain.clear()

    index = 0
    while index < len(text):
        if (
            text[index] == "\\"
            and index + 1 < len(text)
            and text[index + 1] in _ESCAPABLE_MARKDOWN
        ):
            plain.append(text[index + 1])
            index += 2
            continue

        link_match = re.match(r"\[([^\]\n]+)\]\(([^)\s]+)\)", text[index:])
        if link_match:
            flush()
            label, uri = link_match.groups()
            runs.append(_InlineRun(label, link=uri))
            index += link_match.end()
            continue

        matched = False
        for delimiter, style in (
            ("**", BOLD_STYLE),
            ("~~", STRIKETHROUGH_STYLE),
            ("`", SOFT_CYAN_STYLE),
            ("*", ITALIC_STYLE),
            ("_", ITALIC_STYLE),
        ):
            if not text.startswith(delimiter, index):
                continue
            end = text.find(delimiter, index + len(delimiter))
            if end <= index + len(delimiter):
                continue
            if delimiter == "_" and (
                (index > 0 and text[index - 1].isalnum())
                or (end + 1 < len(text) and text[end + 1].isalnum())
            ):
                continue
            flush()
            runs.append(
                _InlineRun(text[index + len(delimiter) : end], styles=(style,))
            )
            index = end + len(delimiter)
            matched = True
            break
        if not matched:
            plain.append(text[index])
            index += 1
    flush()
    return runs


def _run_units(runs: list[_InlineRun]) -> list[tuple[str, tuple[str, ...], str | None]]:
    """Expand runs to wrap-safe visible characters and normalize whitespace."""
    units: list[tuple[str, tuple[str, ...], str | None]] = []
    pending_space: tuple[tuple[str, ...], str | None] | None = None
    for run in runs:
        for character in run.text:
            if character.isspace():
                if units:
                    pending_space = (run.styles, run.link)
                continue
            if pending_space is not None:
                units.append((" ", *pending_space))
                pending_space = None
            units.append((character, run.styles, run.link))
    return units


def _render_units(
    units: list[tuple[str, tuple[str, ...], str | None]],
    extra_styles: tuple[str, ...] = (),
) -> str:
    """Render adjacent units together so control sequences stay compact."""
    rendered: list[str] = []
    start = 0
    while start < len(units):
        _, styles, link = units[start]
        end = start + 1
        while end < len(units) and units[end][1:] == (styles, link):
            end += 1
        label = "".join(unit[0] for unit in units[start:end])
        combined_styles = tuple(dict.fromkeys((*extra_styles, *styles)))
        label = styled_text(label, *combined_styles)
        if link is not None:
            label = terminal_link(label, link)
        rendered.append(label)
        start = end
    return "".join(rendered)


def render_inline_markdown(text: str) -> str:
    """Render supported inline Markdown without interpreting partial syntax."""
    return _render_units(_run_units(_inline_runs(text)))


def _wrapped_inline_lines(
    text: str,
    *,
    initial_indent: str,
    subsequent_indent: str,
    width: int | None,
    extra_styles: tuple[str, ...] = (),
    break_long_words: bool = True,
) -> list[str]:
    """Wrap inline content by visible cells, then add ANSI/OSC decoration."""
    if width is None:
        width = min(
            DISPLAY_WRAP_WIDTH,
            shutil.get_terminal_size(fallback=(DISPLAY_WRAP_WIDTH, 24)).columns,
        )
    units = _run_units(_inline_runs(text))
    if not units:
        return [initial_indent]

    lines: list[str] = []
    current_indent = initial_indent
    while units:
        available = max(width - display_width(current_indent), 1)
        used = 0
        split_at = 0
        last_space = -1
        for unit_index, (character, _styles, _link) in enumerate(units):
            character_width = max(wcwidth(character), 0)
            if unit_index and used + character_width > available:
                break
            used += character_width
            split_at = unit_index + 1
            if character == " ":
                last_space = unit_index
        if split_at < len(units) and last_space > 0:
            split_at = last_space
        elif split_at < len(units) and not break_long_words:
            next_space = next(
                (
                    unit_index
                    for unit_index in range(split_at, len(units))
                    if units[unit_index][0] == " "
                ),
                len(units),
            )
            split_at = next_space
        line_units = units[:split_at]
        units = units[split_at:]
        while units and units[0][0] == " ":
            units.pop(0)
        lines.append(f"{current_indent}{_render_units(line_units, extra_styles)}")
        current_indent = subsequent_indent
    return lines


def _wrapped_literal_lines(text: str, *, indent: str, width: int) -> list[str]:
    """Wrap code without collapsing whitespace or interpreting Markdown."""
    available = max(width - display_width(indent), 1)
    if not text:
        return [indent]
    lines: list[str] = []
    remaining = text
    while remaining:
        chunk, remaining = _take_display_cells(remaining, available)
        lines.append(f"{indent}{chunk}")
    return lines


def _parse_table_row(line: str) -> list[str]:
    """Split one simple pipe row, accepting optional outer pipes."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table_alignments(line: str, columns: int) -> list[str] | None:
    cells = _parse_table_row(line)
    if len(cells) != columns:
        return None
    alignments: list[str] = []
    for cell in cells:
        if not re.fullmatch(r":?-{3,}:?", cell):
            return None
        alignments.append(
            "center"
            if cell.startswith(":") and cell.endswith(":")
            else "right"
            if cell.endswith(":")
            else "left"
        )
    return alignments


def _fit_inline_cell(text: str, width: int, alignment: str, *, bold: bool) -> str:
    units = _run_units(_inline_runs(text))
    visible_width = sum(max(wcwidth(unit[0]), 0) for unit in units)
    if visible_width > width:
        kept: list[tuple[str, tuple[str, ...], str | None]] = []
        used = 0
        ellipsis_width = 1 if width > 1 else 0
        for unit in units:
            unit_width = max(wcwidth(unit[0]), 0)
            if used + unit_width > width - ellipsis_width:
                break
            kept.append(unit)
            used += unit_width
        if ellipsis_width:
            kept.append(("…", (), None))
        units = kept
        visible_width = sum(max(wcwidth(unit[0]), 0) for unit in units)
    padding = max(width - visible_width, 0)
    left = (
        padding
        if alignment == "right"
        else padding // 2
        if alignment == "center"
        else 0
    )
    right = padding - left
    styles = (BOLD_STYLE,) if bold else ()
    return f"{' ' * left}{_render_units(units, styles)}{' ' * right}"


def _render_table(
    rows: list[list[str]],
    alignments: list[str],
    *,
    indent: str,
    width: int,
) -> list[str]:
    columns = len(rows[0])
    content_width = max(width - display_width(indent), 1)
    if content_width < (2 * columns) - 1:
        # Extremely narrow live viewports cannot express even one cell per
        # column plus separators. Keep every value readable as wrapped text.
        fallback: list[str] = []
        for row in rows:
            fallback.extend(
                _wrapped_inline_lines(
                    " | ".join(row),
                    initial_indent=indent,
                    subsequent_indent=indent,
                    width=width,
                )
            )
        return fallback

    separator = " │ " if content_width >= (4 * columns) - 3 else "│"
    available = max(content_width - display_width(separator) * (columns - 1), columns)
    natural = [
        max(display_width(render_inline_markdown(row[column])) for row in rows)
        for column in range(columns)
    ]
    column_widths = [max(value, 1) for value in natural]
    while sum(column_widths) > available:
        largest = max(range(columns), key=lambda item: column_widths[item])
        if column_widths[largest] <= 1:
            break
        column_widths[largest] -= 1

    rendered: list[str] = []
    for row_index, row in enumerate(rows):
        cells = [
            _fit_inline_cell(
                row[column],
                column_widths[column],
                alignments[column],
                bold=row_index == 0,
            )
            for column in range(columns)
        ]
        rendered.append(f"{indent}{separator.join(cells)}")
        if row_index == 0:
            rule_separator = "─┼─" if separator == " │ " else "┼"
            rendered.append(
                f"{indent}{rule_separator.join('─' * size for size in column_widths)}"
            )
    return rendered


def render_markdown_lines(
    content: str,
    *,
    width: int | None = None,
    indent: str = "",
    blank_between_list_items: bool = False,
) -> list[str]:
    """Render the shared lightweight Markdown block subset to physical rows."""
    break_long_words = width is not None
    if width is None:
        width = min(
            DISPLAY_WRAP_WIDTH,
            shutil.get_terminal_size(fallback=(DISPLAY_WRAP_WIDTH, 24)).columns,
        )
    source = content.splitlines()
    rendered: list[str] = []
    index = 0
    previous_list_item = False
    while index < len(source):
        line = source[index]

        if line.startswith("```"):
            closing = next(
                (
                    candidate
                    for candidate in range(index + 1, len(source))
                    if source[candidate].startswith("```")
                ),
                None,
            )
            if closing is not None:
                code_indent = f"{indent}  "
                for code_line in source[index + 1 : closing] or [""]:
                    parts = _wrapped_literal_lines(
                        code_line,
                        indent=code_indent,
                        width=width,
                    )
                    rendered.extend(
                        styled_text(part, SOFT_CYAN_STYLE) for part in parts
                    )
                index = closing + 1
                previous_list_item = False
                continue
            # A partial stream must keep its opening fence and body readable.
            rendered.extend(wrapped_display_lines(line, indent, indent, width=width))
            index += 1
            previous_list_item = False
            continue

        if index + 1 < len(source) and "|" in line:
            header = _parse_table_row(line)
            alignments = _table_alignments(source[index + 1], len(header))
            if len(header) > 1 and alignments is not None:
                rows = [header]
                index += 2
                while index < len(source) and "|" in source[index]:
                    row = _parse_table_row(source[index])
                    if len(row) != len(header):
                        break
                    rows.append(row)
                    index += 1
                rendered.extend(
                    _render_table(rows, alignments, indent=indent, width=width)
                )
                previous_list_item = False
                continue

        if not line.strip():
            rendered.append("")
            index += 1
            previous_list_item = False
            continue

        heading = re.match(r"^\s{0,3}(#{1,3})\s+(.+?)\s*#*\s*$", line)
        if heading:
            level, text = heading.groups()
            heading_indent = indent 
            rendered.extend(
                _wrapped_inline_lines(
                    text,
                    initial_indent=heading_indent,
                    subsequent_indent=heading_indent,
                    width=width,
                    extra_styles=(BOLD_STYLE,),
                    break_long_words=break_long_words,
                )
            )
            index += 1
            previous_list_item = False
            continue

        if re.fullmatch(r"\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*", line):
            rule_width = max(width - display_width(indent), 1)
            rendered.append(f"{indent}{styled_text('─' * rule_width, DIM_STYLE)}")
            index += 1
            previous_list_item = False
            continue

        quote = re.match(r"^\s{0,3}>\s?(.*)$", line)
        if quote:
            quote_prefix = f"{indent}│ "
            rendered.extend(
                _wrapped_inline_lines(
                    quote.group(1),
                    initial_indent=quote_prefix,
                    subsequent_indent=quote_prefix,
                    width=width,
                    break_long_words=break_long_words,
                )
            )
            index += 1
            previous_list_item = False
            continue

        item = re.match(
            r"^(\s*)(?:(?P<bullet>[-+*])|(?P<number>\d+\.))\s+(.+)$", line
        )
        if item:
            nested = len(item.group(1).expandtabs(2)) >= 2
            marker = "•" if item.group("bullet") else item.group("number")
            item_indent = f"{indent}{'  ' if nested else ''}"
            prefix = f"{item_indent}{marker} "
            continuation = f"{item_indent}{' ' * (display_width(marker) + 1)}"
            if blank_between_list_items and previous_list_item:
                rendered.append("")
            rendered.extend(
                _wrapped_inline_lines(
                    item.group(4),
                    initial_indent=prefix,
                    subsequent_indent=continuation,
                    width=width,
                    break_long_words=break_long_words,
                )
            )
            index += 1
            previous_list_item = True
            continue

        rendered.extend(
            _wrapped_inline_lines(
                line.strip(),
                initial_indent=indent,
                subsequent_indent=indent,
                width=width,
                break_long_words=break_long_words,
            )
        )
        index += 1
        previous_list_item = False
    return rendered


def markdown_display_lines(line: str, width: int | None = None) -> list[str]:
    """Render one Markdown source line through the shared block renderer."""
    return render_markdown_lines(line, width=width, indent=FINAL_SUMMARY_INDENT)


def format_final_summary(content: str, width: int | None = None) -> str:
    """Render final-report Markdown with its established outer indentation."""
    lines = render_markdown_lines(
        content,
        width=width,
        indent=FINAL_SUMMARY_INDENT,
        blank_between_list_items=True,
    )
    return "\n".join(lines).strip("\n")
