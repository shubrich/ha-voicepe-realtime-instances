#!/usr/bin/env python3
"""Regenerate one Home Assistant add-on directory per speaker.

Reads the upstream add-on's config.yaml and re-emits it once per entry in
instances.yaml, overriding only slug/name/websocket_port/instance_name and
pointing every copy at the same prebuilt image.

This GENERATES rather than merges. Upstream bumps `version:` on line 2 of
config.yaml while our overrides sit on lines 1 and 3, so a merge-based fork
would conflict on nearly every release. Regenerating never conflicts.

Usage: generate.py <upstream-checkout> [--check]

--check exits 1 if the working tree would change, without writing.
"""

import filecmp
import shutil
import sys
from pathlib import Path

from ruamel.yaml import YAML

# Copied verbatim into each instance so the add-on renders properly in the UI.
# The Dockerfile, app/, build.yaml and friends are deliberately NOT copied:
# with `image:` set, Supervisor pulls instead of building, so shipping the
# source in each instance would just duplicate ~800 KB per speaker.
SUPPORT_FILES = ["icon.png", "logo.png", "DOCS.md", "CHANGELOG.md", "README.md"]
SUPPORT_DIRS = ["translations"]

# Per-instance option keys build_config() overrides. Guarded because these must
# already exist upstream for the override to mean anything.
OVERRIDDEN_OPTIONS = ("websocket_port", "instance_name")

REPO = Path(__file__).resolve().parent.parent

yaml = YAML()  # round-trip mode: preserves upstream's comments and key order
yaml.preserve_quotes = True
yaml.width = 4096  # don't rewrap long option strings such as `instructions`
yaml.indent(mapping=2, sequence=4, offset=2)  # match upstream's list indenting


def check_overridable(upstream_config):
    """Refuse to run if upstream renamed an option we override.

    Assigning into `options` CREATES a key rather than failing, so a rename
    upstream would silently leave the real setting at its default: every
    instance back on port 8080, colliding with the original add-on and with
    each other. Checked once, before anything is written.
    """
    missing = [k for k in OVERRIDDEN_OPTIONS if k not in upstream_config["options"]]
    if missing:
        sys.exit(
            f"upstream config.yaml no longer defines {', '.join(missing)} under "
            "`options` — it was probably renamed. Overriding it now would be a "
            "no-op and instances would fall back to upstream's defaults. Update "
            "OVERRIDDEN_OPTIONS and build_config() to match upstream first."
        )


def build_config(upstream_config, inst, image_base, arch):
    """Return upstream's config with this instance's four overrides applied."""
    cfg = upstream_config

    cfg["name"] = inst["name"]
    cfg["slug"] = inst["slug"]
    cfg["options"]["websocket_port"] = inst["websocket_port"]
    cfg["options"]["instance_name"] = inst["instance_name"]

    # Pull the shared image instead of building locally. Supervisor expands
    # {arch} and appends ":<version>". Inserted right after `slug` rather than
    # appended, because upstream ends the file with a comment explaining that
    # the ABSENCE of this key is what makes it build locally — an `image:`
    # sitting directly under that comment reads as a contradiction.
    cfg.insert(3, "image", f"{image_base}-{{arch}}")

    # Advertise only what we actually publish, so an unsupported host fails
    # at install time with a clear message instead of on a missing image tag.
    cfg["arch"] = list(arch)

    return cfg


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    upstream = Path(sys.argv[1])
    check_only = "--check" in sys.argv

    spec = yaml.load((REPO / "instances.yaml").read_text())
    addon_src = upstream / spec["upstream"]["addon_dir"]
    if not (addon_src / "config.yaml").is_file():
        sys.exit(f"no config.yaml under {addon_src}")

    upstream_config = yaml.load((addon_src / "config.yaml").read_text())
    version = upstream_config["version"]
    print(f"upstream version: {version}")
    check_overridable(upstream_config)

    stale = False
    for inst in spec["instances"]:
        dest = REPO / inst["slug"]
        scratch = REPO / f".gen-{inst['slug']}"
        if scratch.exists():
            shutil.rmtree(scratch)
        scratch.mkdir()

        # Re-read per instance: build_config mutates the tree it is given.
        cfg = build_config(
            yaml.load((addon_src / "config.yaml").read_text()),
            inst,
            spec["image_base"],
            spec["arch"],
        )
        with (scratch / "config.yaml").open("w") as fh:
            yaml.dump(cfg, fh)

        for name in SUPPORT_FILES:
            if (addon_src / name).is_file():
                shutil.copy2(addon_src / name, scratch / name)
        for name in SUPPORT_DIRS:
            if (addon_src / name).is_dir():
                shutil.copytree(addon_src / name, scratch / name)

        if dest.exists() and not dirs_differ(dest, scratch):
            shutil.rmtree(scratch)
            print(f"  {inst['slug']}: unchanged")
            continue

        stale = True
        print(f"  {inst['slug']}: {'would change' if check_only else 'regenerated'}")
        if check_only:
            shutil.rmtree(scratch)
            continue
        if dest.exists():
            shutil.rmtree(dest)
        scratch.rename(dest)

    # A slug removed from instances.yaml leaves an orphan add-on directory that
    # Home Assistant would keep offering, so drop it.
    keep = {i["slug"] for i in spec["instances"]}
    for path in REPO.iterdir():
        if path.is_dir() and (path / "config.yaml").is_file() and path.name not in keep:
            stale = True
            print(f"  {path.name}: {'would be removed' if check_only else 'removed'}")
            if not check_only:
                shutil.rmtree(path)

    if check_only and stale:
        sys.exit(1)


def dirs_differ(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(a, b)
    if cmp.left_only or cmp.right_only or cmp.funny_files:
        return True
    # shallow=False: stat metadata differs after every fresh copy, so compare
    # contents or nothing would ever look unchanged.
    _, mismatch, errors = filecmp.cmpfiles(a, b, cmp.common_files, shallow=False)
    if mismatch or errors:
        return True
    return any(dirs_differ(a / sub, b / sub) for sub in cmp.common_dirs)


if __name__ == "__main__":
    main()
