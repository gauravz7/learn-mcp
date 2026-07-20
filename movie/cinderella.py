"""Generate an 8-scene Ella story through the movie pipeline (deterministic director).

Ella (and the Fairy Godmother / Prince) are locked as character sheets so identity stays
consistent across scenes; wardrobe and setting change per beat. Each scene = a people-free set
plate + a keyframe composed from the plate + the relevant character sheets, validated by film
grammar before rendering.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import movie_server as m

U = "director1"
STYLE = "painterly storybook fairytale illustration, warm cinematic lighting, rich detail, 35mm"

proj = m.mv_create_project(U, "Ella", STYLE)
pid = proj["project_id"]
print("project:", pid)

print("casting (character sheets)…")
cinderella = m.mv_add_character(U, pid, "Ella",
    "a kind adult woman in her mid-20s, gentle face, strawberry-blonde hair in a braid, light freckles")["char_id"]
fairy = m.mv_add_character(U, pid, "Fairy Godmother",
    "plump kindly elderly woman, silver hair in a bun, sparkling pale-blue cloak, glowing wand")["char_id"]
prince = m.mv_add_character(U, pid, "Prince",
    "a handsome adult prince, dark hair, royal-blue uniform with gold trim")["char_id"]

print("style reference (global look anchor)…")
sref = m.mv_generate_style_ref(U, pid, "a warm fairytale storybook establishing scene")
print("   style_ref:", sref["style_ref"])

# 8 beats: (scene_id, setting, [character ids present], action+wardrobe)
BEATS = [
    ("hearth",   "a humble stone kitchen by a large hearth full of glowing cinders, soft dawn light",
     [cinderella], "Ella in a patched grey ragged dress with soot smudges kneels tending the fire, weary but hopeful"),
    ("mockery",  "an ornate cold manor parlor, morning light",
     [cinderella], "Ella in rags stands with lowered eyes as two elegantly dressed stepsisters and a stern stepmother look down on her haughtily"),
    ("letter",   "the grand front hall of the manor",
     [cinderella], "a royal footman hands over a gold-sealed invitation to the ball; Ella in rags watches with longing"),
    ("garden",   "a moonlit rose garden with a stone bench, night, silver moonlight",
     [cinderella], "Ella in rags weeps alone on the bench, face in her hands"),
    ("fairy",    "the moonlit garden filled with swirling golden magical light",
     [cinderella, fairy], "the Fairy Godmother appears in a burst of golden sparkles, wand raised, smiling at astonished Ella still in rags"),
    ("transform","the garden at night, magical glow, a golden pumpkin coach and white horses",
     [cinderella, fairy], "Ella now in a shimmering pale-blue ball gown and glass slippers twirls in delight as the Fairy Godmother gestures with her wand"),
    ("ball",     "a vast palace ballroom under sparkling crystal chandeliers, warm golden light",
     [cinderella, prince], "Ella in her blue ball gown dances gracefully with the Prince, both gazing at each other"),
    ("midnight", "the grand palace staircase at midnight, cold blue moonlight, a clock tower striking twelve",
     [cinderella, prince], "Ella flees down the steps, gown flowing, a single glass slipper left on a step, the Prince reaching after her"),
]

def render_scene(i, scene, setting, chars, action):
    m.mv_establish_scene(U, pid, scene, setting, lighting=setting, blocking={})
    anchors = [f"establish:{scene}"] + [f"char:{c}" for c in chars]
    shot = {"id": f"{scene}_a", "subject": chars[0], "side": "center",
            "camera": {"type": "wide", "lens": "35mm"}, "anchors": anchors, "intent": action}
    r = m.mv_plan_scene(U, pid, scene, [shot])
    if r["errors"]:
        raise RuntimeError(f"plan rejected: {r['violations']}")
    k = m.mv_generate_shot(U, pid, f"{scene}_a")
    return k["keyframe_uri"], k["refs_used"]


def render_with_retry(i, scene, setting, chars, action):
    err = None
    for _ in (1, 2):                                 # resilient: retry a flaky scene once
        try:
            uri, refs = render_scene(i, scene, setting, chars, action)
            return scene, uri, refs, None
        except Exception as e:
            err = e
    return scene, None, 0, err


print("\nrendering 8 scenes in PARALLEL…")
done = {}
with ThreadPoolExecutor(max_workers=4) as ex:                # fan out (store is thread-safe)
    futs = [ex.submit(render_with_retry, i, *beat) for i, beat in enumerate(BEATS, 1)]
    for fut in as_completed(futs):
        scene, uri, refs, err = fut.result()
        if uri:
            print(f"   ✓ {scene:9} -> {uri} (refs={refs})"); done[scene] = uri
        else:
            print(f"   ✗ {scene:9} SKIPPED: {err}")

print("\n=== 8-SCENE CINDERELLA (keyframes, story order) ===")
for n, beat in enumerate([b for b in BEATS if b[0] in done], 1):
    print(f"  {n}. {beat[0]:9} {done[beat[0]]}")
print(f"\nGenerated {len(done)}/8 scenes for project {pid}")
