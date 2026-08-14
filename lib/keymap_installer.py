import os
import xbmc
import xbmcaddon


def _build_keymap(key, remote):
    keyboard_line = ""
    remote_line = ""
    if key:
        keyboard_line = "      <{}>RunScript(script.twitch.center,cycle_audio)</{}>".format(key, key)
    if remote:
        remote_line = "      <{}>RunScript(script.twitch.center,cycle_audio)</{}>".format(remote, remote)

    return """<?xml version="1.0" encoding="UTF-8"?>
<keymap>
  <global>
    <keyboard>
{}
    </keyboard>
    <remote>
{}
    </remote>
  </global>
</keymap>
""".format(keyboard_line, remote_line)


def install():
    addon = xbmcaddon.Addon()
    profile_path = xbmc.translatePath(addon.getAddonInfo("profile"))

    key = addon.getSetting("audio_cycle_key").strip()
    remote = addon.getSetting("audio_cycle_remote").strip()

    dst_dir = os.path.join(profile_path, "..", "keymaps")
    dst = os.path.join(dst_dir, "script.twitch.center.xml")

    if not os.path.isdir(dst_dir):
        os.makedirs(dst_dir)

    with open(dst, "w") as f:
        f.write(_build_keymap(key, remote))

    xbmc.executebuiltin("Action(reloadkeymaps)")
