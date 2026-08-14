import os
import shutil
import xbmc
import xbmcaddon


def install():
    addon = xbmcaddon.Addon()
    addon_path = addon.getAddonInfo("path")
    profile_path = xbmc.translatePath(addon.getAddonInfo("profile"))

    src = os.path.join(addon_path, "resources", "keymaps", "keyboard.xml")
    dst_dir = os.path.join(profile_path, "..", "keymaps")
    dst = os.path.join(dst_dir, "script.twitch.center.xml")

    if not os.path.isfile(src):
        return

    if os.path.isfile(dst):
        return

    if not os.path.isdir(dst_dir):
        os.makedirs(dst_dir)

    shutil.copyfile(src, dst)
    xbmc.executebuiltin("Action(reloadkeymaps)")
