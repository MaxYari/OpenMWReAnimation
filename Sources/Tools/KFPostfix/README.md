# KF post-export fixes

Some exported animations need their text keys adjusted after every Blender export. Blender pose
markers sit on whole frames, so these fixes can't be made in the .blend without changing the
animation. `kf_postfix.json` lists the files that get patched and what is done to each.

**After exporting any .kf into `Animations/`, run:**

```
python3 Sources/Tools/KFPostfix/kf_postfix.py check
python3 Sources/Tools/KFPostfix/kf_postfix.py apply
```

`check` compares each listed file's SHA-256 with the hashes stored in the manifest:

| Status | Meaning |
|---|---|
| `ok` | Patched, and the file hasn't changed since. |
| `UNPATCHED` | The same export as last time, but without the patch (e.g. restored from an older commit). Run `apply`. |
| `CHANGED` | A new export. Run `apply`, which re-patches it and records both hashes. |
| `UNLISTED` | A file that isn't in the manifest but would need an operation. Add it to `files` if it should be patched. |

`apply` records `source_sha256` (the export as it came out of Blender), `patched_sha256`, the date,
and the keys it moved.

## Operation: `separate-follow-start`

The engine plays an attack in sections. The follow-through starts at `<attack> follow start`
(`character.cpp`, the `playBlendedAnimation(... start, stop ...)` after the release section).
Starting a section fires **every** text key at the start time, not just the start key
(`Animation::play` in `animation.cpp` walks `textkeys.lowerBound(startTime)`). A `shoot release`
or `<attack> hit` key on the same frame as its follow start is therefore fired twice: once when
the release section ends, and again a frame later when the follow section starts. Anything else on
that frame fires twice too, e.g. `Sound: CrossbowShoot`. The engine's own arrow and hit are guarded
by `mReadyToHit`, but Lua text key handlers see both events (Dynamic Reticle's shot bounce, for one).

The fix moves the follow start key `epsilon` (0.001 s) later, into its own text key entry. The
release section no longer reaches it, and the follow section starts past the release key. The
pose difference is invisible. OpenMW splits multi-line entries into separate keys at the entry's
time (`extractTextKeys` in `nifloader.cpp`), so splitting an entry changes nothing else.

The durable alternative is to move the `Follow Start` marker one frame later in Blender, which
skips one 30 fps frame of motion at the transition. Vanilla's bow and thrown animations are laid
out that way (release and follow start 2 frames apart).

Melee attacks in many ReAnimation sets put `<attack> hit` on the same frame as their
`small/medium/large follow start` too. `check` lists them as `UNLISTED`. As of 2026-09-15 they
aren't patched; that's still the user's call.
