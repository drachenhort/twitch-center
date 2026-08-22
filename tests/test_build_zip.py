import os
import zipfile

from tools.build_zip import build_addon_zip, get_addon_id, get_addon_version, iter_addon_files


def _write_addon_xml(dir_path, addon_id, version):
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / "addon.xml").write_text(
        '<?xml version="1.0"?>\n'
        '<addon id="{}" name="Test" version="{}" provider-name="test">'
        "</addon>\n".format(addon_id, version)
    )


def test_get_addon_id(tmp_path):
    _write_addon_xml(tmp_path, "script.twitch.center", "1.2.3")
    assert get_addon_id(str(tmp_path)) == "script.twitch.center"


def test_get_addon_version(tmp_path):
    _write_addon_xml(tmp_path, "script.twitch.center", "1.2.3")
    assert get_addon_version(str(tmp_path)) == "1.2.3"


def test_iter_addon_files_with_explicit_includes(tmp_path):
    _write_addon_xml(tmp_path, "script.twitch.center", "1.0.0")
    (tmp_path / "addon.py").write_text("print('hi')\n")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "helper.py").write_text("x = 1\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("# dev only\n")

    pairs = sorted(
        iter_addon_files(
            str(tmp_path),
            includes=["addon.xml", "addon.py", "lib"],
            addon_id="script.twitch.center",
        )
    )
    arcnames = sorted(arcname for _, arcname in pairs)

    assert arcnames == [
        os.path.join("script.twitch.center", "addon.py"),
        os.path.join("script.twitch.center", "addon.xml"),
        os.path.join("script.twitch.center", "lib", "helper.py"),
    ]
    for full_path, _ in pairs:
        assert os.path.isfile(full_path)


def test_iter_addon_files_excludes_pycache(tmp_path):
    _write_addon_xml(tmp_path, "script.twitch.center", "1.0.0")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "helper.py").write_text("x = 1\n")
    pycache_dir = tmp_path / "lib" / "__pycache__"
    pycache_dir.mkdir()
    (pycache_dir / "helper.cpython-314.pyc").write_bytes(b"fake-bytecode")

    arcnames = sorted(
        arcname
        for _, arcname in iter_addon_files(
            str(tmp_path), includes=["addon.xml", "lib"], addon_id="script.twitch.center"
        )
    )

    assert arcnames == [
        os.path.join("script.twitch.center", "addon.xml"),
        os.path.join("script.twitch.center", "lib", "helper.py"),
    ]


def test_build_addon_zip_creates_zip_with_expected_arcnames(tmp_path):
    source_dir = tmp_path / "src"
    _write_addon_xml(source_dir, "script.twitch.center", "1.0.0")
    (source_dir / "addon.py").write_text("print('hi')\n")
    output_dir = tmp_path / "dist"

    zip_path = build_addon_zip(
        str(source_dir),
        includes=["addon.xml", "addon.py"],
        addon_id="script.twitch.center",
        version="1.0.0",
        output_dir=str(output_dir),
    )

    assert zip_path == str(output_dir / "script.twitch.center-1.0.0.zip")
    with zipfile.ZipFile(zip_path) as zf:
        assert sorted(zf.namelist()) == [
            "script.twitch.center/addon.py",
            "script.twitch.center/addon.xml",
        ]


def test_build_addon_zip_overwrites_an_existing_zip(tmp_path):
    # Unlike jellyfin-kodi-plex's build_repo (which keeps historical zips
    # around forever and skips rebuilding an existing version), this repo's
    # release workflow builds exactly one zip per CI run for whatever
    # version addon.xml currently declares - always fresh, never stale.
    source_dir = tmp_path / "src"
    _write_addon_xml(source_dir, "script.twitch.center", "1.0.0")
    output_dir = tmp_path / "dist"
    output_dir.mkdir()
    stale_zip = output_dir / "script.twitch.center-1.0.0.zip"
    stale_zip.write_bytes(b"stale-not-a-real-zip")

    zip_path = build_addon_zip(
        str(source_dir),
        includes=["addon.xml"],
        addon_id="script.twitch.center",
        version="1.0.0",
        output_dir=str(output_dir),
    )

    assert zip_path == str(stale_zip)
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.namelist() == ["script.twitch.center/addon.xml"]
