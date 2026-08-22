import xbmcaddon
import xbmcgui

from lib.views.kick_favorites_menu import show_kick_favorite_context_menu


def test_shows_add_option_and_adds_when_not_a_favorite():
    addon = xbmcaddon.Addon()
    xbmcgui.Dialog.next_contextmenu_choice = 0
    xbmcgui.Dialog.notifications = []

    changed = show_kick_favorite_context_menu(addon, "somechannel")

    assert changed is True
    from lib import providers

    assert providers.get_kick_favorites(addon) == ["somechannel"]
    assert xbmcgui.Dialog.notifications == [("Kick", "Added to Kick Favorites")]


def test_shows_remove_option_and_removes_when_already_a_favorite():
    addon = xbmcaddon.Addon()
    from lib import providers

    providers.add_kick_favorite(addon, "somechannel")
    xbmcgui.Dialog.next_contextmenu_choice = 0
    xbmcgui.Dialog.notifications = []

    changed = show_kick_favorite_context_menu(addon, "somechannel")

    assert changed is True
    assert providers.get_kick_favorites(addon) == []
    assert xbmcgui.Dialog.notifications == [("Kick", "Removed from Kick Favorites")]


def test_does_nothing_when_menu_is_cancelled():
    addon = xbmcaddon.Addon()
    xbmcgui.Dialog.next_contextmenu_choice = -1
    xbmcgui.Dialog.notifications = []

    changed = show_kick_favorite_context_menu(addon, "somechannel")

    assert changed is False
    from lib import providers

    assert providers.get_kick_favorites(addon) == []
    assert xbmcgui.Dialog.notifications == []
