"""Build the installable addon zip under dist/ from the current repo state.

Run directly (`python tools/build_zip.py`) or import build_zip() for tests.
Deliberately free of xbmc* imports so it runs under plain Python/CI.
"""

import os
import xml.etree.ElementTree as ET
import zipfile

INCLUDES = ["addon.xml", "addon.py", "icon.png", "lib", "resources"]


def get_addon_id(source_dir):
    return ET.parse(os.path.join(source_dir, "addon.xml")).getroot().attrib["id"]


def get_addon_version(source_dir):
    return ET.parse(os.path.join(source_dir, "addon.xml")).getroot().attrib["version"]


def iter_addon_files(source_dir, includes, addon_id):
    for name in includes:
        full_path = os.path.join(source_dir, name)
        if os.path.isdir(full_path):
            for dirpath, dirnames, filenames in os.walk(full_path):
                dirnames[:] = [d for d in dirnames if d != "__pycache__"]
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    arcname = os.path.join(addon_id, os.path.relpath(file_path, source_dir))
                    yield file_path, arcname
        else:
            yield full_path, os.path.join(addon_id, name)


def build_addon_zip(source_dir, includes, addon_id, version, output_dir):
    zip_path = os.path.join(output_dir, "{}-{}.zip".format(addon_id, version))
    os.makedirs(output_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path, arcname in iter_addon_files(source_dir, includes, addon_id):
            zf.write(file_path, arcname)
    return zip_path


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(REPO_ROOT, "dist")


def build_zip(source_dir=REPO_ROOT, dist_dir=DIST_DIR):
    addon_id = get_addon_id(source_dir)
    version = get_addon_version(source_dir)
    return build_addon_zip(source_dir, INCLUDES, addon_id, version, dist_dir)


if __name__ == "__main__":
    print(build_zip())
