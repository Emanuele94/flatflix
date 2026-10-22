"""The two content types and everything derived from them (SEC-03, DOWN-02).

The browser sends only `type`. The plugin category, the qBittorrent category and the save
path are fixed server-side maps defined here and nowhere else, so a request can never choose
a category or a path (qBittorrent auto-creates any category it is given: research Pitfall 4).
"""

from typing import Literal, get_args

from app.config import Settings

ContentType = Literal["film", "serie"]
CONTENT_TYPES: tuple[str, ...] = get_args(ContentType)

# Search-plugin categories understood by qBittorrent's `search/start`.
PLUGIN_CATEGORY: dict[str, str] = {"film": "movies", "serie": "tv"}


def qbit_category(settings: Settings, content_type: ContentType) -> str:
    """qBittorrent category of a type (Film or SerieTV by default)."""
    if content_type == "film":
        return settings.category_film
    if content_type == "serie":
        return settings.category_tv
    raise ValueError(f"unknown content type: {content_type!r}")


def save_path(settings: Settings, content_type: ContentType) -> str:
    """Save path that belongs to the category of a type."""
    return settings.category_paths[qbit_category(settings, content_type)]
