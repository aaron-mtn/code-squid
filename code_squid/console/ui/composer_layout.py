"""Product-owned sizing policy for boxed CLI composers."""

from prompt_toolkit.layout import Dimension
from prompt_toolkit.layout.containers import Container


COMPOSER_MIN_CONTENT_ROWS = 2
COMPOSER_MAX_CONTENT_ROWS = 14
COMPOSER_FRAME_ROWS = 2


def desired_composer_content_height(
    content: Container,
    width: int,
    safe_max_rows: int = COMPOSER_MAX_CONTENT_ROWS,
) -> Dimension:
    """Return the visible content height needed within product and viewport caps.

    Asking prompt_toolkit for the content's preferred height preserves its
    cell-aware wrapping rules. ``safe_max_rows`` is derived by each caller from
    its real Application viewport; it deliberately remains separate from the
    product-owned 14-row maximum.
    """
    safe_max_rows = max(safe_max_rows, 0)
    preferred = content.preferred_height(width, COMPOSER_MAX_CONTENT_ROWS).preferred
    desired = max(
        COMPOSER_MIN_CONTENT_ROWS,
        min(preferred, COMPOSER_MAX_CONTENT_ROWS),
    )
    # The physical viewport is the final authority, even when it cannot fit
    # the normal two-row minimum. This keeps layout geometry truthful on resize.
    return Dimension.exact(min(desired, safe_max_rows))
