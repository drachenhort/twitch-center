"""Shared context-menu helper for toggling a Kick channel's favorite status.
Lives here (not lib/providers.py) because it needs xbmcgui, which providers.py
may never import directly - see providers.py's module docstring."""
import xbmcgui

from lib import providers


def show_kick_favorite_context_menu(addon, slug):
    """Show an Add/Remove Kick Favorite context menu for `slug` and apply the
    chosen action. Returns True if the favorite set changed, False if the
    menu was cancelled."""
    is_favorite = slug in providers.get_kick_favorites(addon)
    label = "Remove from Kick Favorites" if is_favorite else "Add to Kick Favorites"
    choice = xbmcgui.Dialog().contextmenu([label])
    if choice != 0:
        return False
    if is_favorite:
        providers.remove_kick_favorite(addon, slug)
        xbmcgui.Dialog().notification("Kick", "Removed from Kick Favorites")
    else:
        providers.add_kick_favorite(addon, slug)
        xbmcgui.Dialog().notification("Kick", "Added to Kick Favorites")
    return True
