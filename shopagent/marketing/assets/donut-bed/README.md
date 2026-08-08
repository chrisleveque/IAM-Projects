# Donut bed product photos

Drop the four CJ listing photos (pid 2036693145205379073 — one per color,
white background, the round-bed shots) into this directory with exactly
these names:

    pink.jpg
    light-grey.jpg
    brown.jpg
    dark-grey.jpg

PNG works too — update the `photos:` map in
`marketing/donut-bed-briefs.yaml` to match the extension you use.

These are attached to every Veo generation as the product reference image,
which is what keeps the bed's real shape, fur texture, and color consistent
across clips. `shopagent veo doctor` verifies they're all present.
