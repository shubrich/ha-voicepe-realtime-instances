# Voice PE Realtime — per-speaker instances

A Home Assistant add-on repository that publishes one add-on per speaker, all
generated from [TristanBrotherton/voicepe-realtime][upstream].

Tristan's add-on handles **one device per instance**, so a second speaker needs
a second add-on with its own slug and WebSocket port. Copying the add-on into
`/addons` by hand works, but a local add-on has no git remote for Supervisor to
pull from, so it never auto-updates. This repository is that copy, kept in sync
automatically.

[upstream]: https://github.com/TristanBrotherton/voicepe-realtime

## Adding a speaker

Append an entry to [`instances.yaml`](instances.yaml) and commit:

```yaml
  - slug: openai_realtime_kitchen
    name: OpenAI Realtime 2 Voice Agent - Kitchen
    websocket_port: 8083
    instance_name: kitchen
```

The sync workflow regenerates the add-on directory and pushes it. In Home
Assistant, refresh the add-on store and the new add-on appears. Install it, set
the OpenAI API key, and point the device firmware's `va_url` at the new port.

**Ports must be unique across every instance**, including the original add-on
installed from Tristan's repository, which uses 8080.

## How the sync works

[`.github/workflows/sync.yml`](.github/workflows/sync.yml) runs daily:

1. Checks out upstream `main` and reads its `version:`.
2. Builds and pushes a **single shared image** to GHCR, unless that version is
   already published. Nothing device-specific is baked into the image — every
   option is read at runtime by `run.sh` through `bashio::config` — so all
   instances pull the same one.
3. Regenerates every instance directory from upstream's `config.yaml`,
   overriding only `slug`, `name`, `websocket_port` and `instance_name`, and
   adding the `image:` key so Supervisor pulls instead of building.
4. Commits if anything changed.

The image is built before the configs referencing it are committed, so a failed
build never leaves Home Assistant pointing at a tag that does not exist.

If upstream ever renames `websocket_port` or `instance_name`, the generator
exits non-zero rather than writing an override that would silently do nothing
and drop every instance back to upstream's default port. GitHub emails you when
a scheduled run fails, so that shows up as a broken sync instead of two add-ons
quietly fighting over port 8080.

### Why generate instead of merging a fork

Upstream bumps `version:` on line 2 of `config.yaml`; the overrides sit on lines
1 and 3. Those hunks are adjacent, so a merge-based fork would conflict on
nearly every release. Regenerating from upstream each time cannot conflict.

## Architecture

Only `amd64` is built, matching the `qemux86-64` host. To add `aarch64`, add it
to `arch:` in `instances.yaml` and to the build in the workflow — note that the
image compiles Python dependencies, so an emulated arm64 build is slow.

## Local use

```bash
git clone https://github.com/TristanBrotherton/voicepe-realtime .upstream
pip install ruamel.yaml
python3 scripts/generate.py .upstream          # write changes
python3 scripts/generate.py .upstream --check  # exit 1 if stale
```

## Caveats

`instance_name` namespaces the Home Assistant sensor entities
(`sensor.voicepe_<instance>_*`) only. `/share/voice-prints/`,
`/share/voice-memory/` and `/share/voice-enrollment/` are shared by every
instance. Shared voiceprints and memory across the house is usually what you
want, but two speakers running voice enrollment at the same time will collide.
