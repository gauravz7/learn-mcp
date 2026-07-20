"""A 10-frame original witch-and-friends broomstick story through the movie pipeline.

(A witch, her cat, and helpful animals share a crowded broom, lose it to a dragon, and win a
grand new one — an original telling; no IP names reach the image model, only descriptions.)

Same pipeline as before: cast character sheets → global style reference → per-scene set plate +
keyframe composed from the anchors, film-grammar validated, rendered in parallel, resilient.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import movie_server as m

U = "director1"
STYLE = "whimsical children's picture-book illustration, bright playful colours, soft painterly texture, storybook"

proj = m.mv_create_project(U, "The Crowded Broom", STYLE)
pid = proj["project_id"]
print("project:", pid)

print("casting (character sheets — generic descriptions, no IP names)…")
witch  = m.mv_add_character(U, pid, "Witch",  "a cheerful witch, tall pointed black hat, red hair in two braids, flowing purple cloak, kind smile")["char_id"]
cat    = m.mv_add_character(U, pid, "Cat",    "a sleek black cat with bright green eyes")["char_id"]
dog    = m.mv_add_character(U, pid, "Dog",    "a friendly scruffy brown dog with floppy ears")["char_id"]
bird   = m.mv_add_character(U, pid, "Bird",   "a small bright green bird with cheerful feathers")["char_id"]
frog   = m.mv_add_character(U, pid, "Frog",   "a plump grinning green frog")["char_id"]
dragon = m.mv_add_character(U, pid, "Dragon", "a big fierce red dragon with smoking nostrils")["char_id"]

print("style reference (global look anchor)…")
sref = m.mv_generate_style_ref(U, pid, "a whimsical storybook scene of a witch flying a broom over green hills")
print("   style_ref:", sref["style_ref"])

# 10 beats: (scene_id, setting, [character ids present], action)
BEATS = [
    ("flight", "a sunny sky over green rolling hills with fluffy clouds",
     [witch, cat], "the witch and her black cat fly happily together on a wooden broomstick"),
    ("hat",    "a windy sky above a dark pine forest",
     [witch, cat], "a strong gust blows the witch's tall pointed hat off the broom, tumbling toward the trees"),
    ("dog",    "a sunny forest clearing",
     [witch, cat, dog], "a friendly scruffy dog holds the found black hat in its mouth; the smiling witch welcomes it onto the broom"),
    ("bow",    "a breezy sky over a blue pond",
     [witch, cat, dog], "the wind snatches the witch's hair bow, which flutters down toward the pond"),
    ("bird",   "green reeds beside a sparkling pond",
     [witch, cat, dog, bird], "a bright green bird returns the bow; the crowded broom now carries the witch, cat, dog and bird"),
    ("wand",   "a misty green bog at dusk",
     [witch, cat, dog, bird], "the witch's sparkling wand slips from her hand down into the muddy bog"),
    ("frog",   "a bog full of lily pads",
     [witch, cat, dog, bird, frog], "a plump green frog holds up the found wand and hops onto the very crowded broom"),
    ("snap",   "a stormy dusk sky over a dark swamp",
     [witch, cat, dog, bird, frog], "the overloaded broomstick SNAPS in two and everyone tumbles down toward the swamp"),
    ("dragon", "a gloomy moonlit swamp with drifting smoke",
     [witch, dragon], "a fierce red dragon looms hungrily over the frightened witch lying in the mud"),
    ("rescue", "the swamp at night under a glowing magical sky",
     [witch, cat, dog, bird, frog, dragon], "the muddy animals rise up together and roar to frighten the red dragon away, while a magnificent new broom with cosy seats for everyone appears"),
]


def render_scene(scene, setting, chars, action):
    m.mv_establish_scene(U, pid, scene, setting, lighting=setting, blocking={})
    anchors = [f"establish:{scene}"] + [f"char:{c}" for c in chars]
    shot = {"id": f"{scene}_a", "subject": chars[0], "side": "center",
            "camera": {"type": "wide", "lens": "35mm"}, "anchors": anchors, "intent": action}
    r = m.mv_plan_scene(U, pid, scene, [shot])
    if r["errors"]:
        raise RuntimeError(f"plan rejected: {r['violations']}")
    k = m.mv_generate_shot(U, pid, f"{scene}_a")
    return k["keyframe_uri"], k["refs_used"]


def render_with_retry(beat):
    scene, setting, chars, action = beat
    err = None
    for _ in (1, 2):
        try:
            uri, refs = render_scene(scene, setting, chars, action)
            return scene, uri, refs, None
        except Exception as e:
            err = e
    return scene, None, 0, err


print("\nrendering 10 scenes in PARALLEL…")
done = {}
with ThreadPoolExecutor(max_workers=4) as ex:
    for scene, uri, refs, err in ex.map(render_with_retry, BEATS):
        if uri:
            print(f"   ✓ {scene:8} -> {uri} (refs={refs})"); done[scene] = uri
        else:
            print(f"   ✗ {scene:8} SKIPPED: {err}")

print("\n=== 10-FRAME STORY (story order) ===")
for n, beat in enumerate([b for b in BEATS if b[0] in done], 1):
    print(f"  {n:2}. {beat[0]:8} {done[beat[0]]}")
print(f"\nGenerated {len(done)}/10 frames for project {pid}")
