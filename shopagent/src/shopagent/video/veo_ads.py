"""Veo UGC ad campaign runner: briefs YAML -> clips -> stitched 9:16 ads.

The campaign file (marketing/donut-bed-briefs.yaml) is the source of truth a
human edits: per-ad creator continuity text and per-clip prompts with the
spoken dialogue inline. This module loads it, attaches the right product
photo as a Veo asset reference, generates each ad's clips, and stitches them
with ffmpeg into output/video/veo/adNN.mp4.

Clips within one ad share the creator description and the product reference,
which is what keeps a two-clip ad looking like one continuous creator video
— carry that text forward verbatim when editing briefs.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..integrations.veo_client import COST_PER_SECOND_USD, VeoError
from .render import RenderError, _run, ffmpeg_available

MAX_CLIP_SECONDS = 8  # Veo's per-generation ceiling


class ClipBrief(BaseModel):
    prompt: str
    seconds: int = MAX_CLIP_SECONDS


class AdBrief(BaseModel):
    id: int
    title: str
    color: str
    creator: str
    clips: list[ClipBrief]

    @property
    def seconds(self) -> int:
        return sum(clip.seconds for clip in self.clips)


class Campaign(BaseModel):
    product: str
    style_prefix: str
    photos: dict[str, str]  # color -> path relative to the briefs file
    ads: list[AdBrief] = Field(default_factory=list)

    def ad(self, ad_id: int) -> AdBrief:
        for ad in self.ads:
            if ad.id == ad_id:
                return ad
        raise VeoError(f"no ad #{ad_id} in campaign "
                       f"(have {[a.id for a in self.ads]})")


def load_campaign(path: Path | str) -> Campaign:
    import yaml
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    campaign = Campaign(**data)
    for ad in campaign.ads:
        if ad.color not in campaign.photos:
            raise VeoError(f"ad #{ad.id} wants color {ad.color!r} but photos "
                           f"only maps {sorted(campaign.photos)}")
        for clip in ad.clips:
            if clip.seconds > MAX_CLIP_SECONDS:
                raise VeoError(f"ad #{ad.id} has a {clip.seconds}s clip; Veo "
                               f"caps a generation at {MAX_CLIP_SECONDS}s")
    return campaign


def photo_path(campaign: Campaign, ad: AdBrief, briefs_dir: Path) -> Path:
    return (briefs_dir / campaign.photos[ad.color]).resolve()


def full_prompt(campaign: Campaign, ad: AdBrief, clip: ClipBrief) -> str:
    """One flat text prompt: house style, then who the creator is (identical
    across the ad's clips), then this clip's scene + dialogue."""
    return (f"{campaign.style_prefix.strip()}\n\n"
            f"The creator: {ad.creator.strip()}\n\n{clip.prompt.strip()}")


def estimate_usd(ads: list[AdBrief], model: str) -> float:
    rate = COST_PER_SECOND_USD.get(model)
    if rate is None:
        raise VeoError(f"no published rate for {model!r}; known: "
                       f"{sorted(COST_PER_SECOND_USD)}")
    return sum(ad.seconds for ad in ads) * rate


def run_ad(client, campaign: Campaign, ad: AdBrief, *, briefs_dir: Path,
           out_dir: Path, model: str, resolution: str = "1080p") -> Path:
    """Generate every clip of one ad, stitch, and return the final mp4 path.

    Clip files are kept next to the final ad (adNN_clipK.mp4) so a bad clip
    can be judged and re-rolled without paying for its siblings again.
    """
    photo = photo_path(campaign, ad, briefs_dir)
    if not photo.exists():
        raise VeoError(
            f"product photo missing: {photo}\n"
            f"Drop the four listing photos in as described by "
            f"{briefs_dir / 'assets' / 'donut-bed' / 'README.md'}")
    mime = "image/png" if photo.suffix.lower() == ".png" else "image/jpeg"
    reference = photo.read_bytes()

    out_dir.mkdir(parents=True, exist_ok=True)
    clip_paths: list[Path] = []
    for index, clip in enumerate(ad.clips, start=1):
        video = client.generate_clip(
            full_prompt(campaign, ad, clip), model=model,
            duration=clip.seconds, aspect_ratio="9:16",
            resolution=resolution, reference_image=reference,
            reference_mime=mime)
        clip_path = out_dir / f"ad{ad.id:02d}_clip{index}.mp4"
        clip_path.write_bytes(video)
        clip_paths.append(clip_path)

    final = out_dir / f"ad{ad.id:02d}.mp4"
    if len(clip_paths) == 1:
        final.write_bytes(clip_paths[0].read_bytes())
    else:
        stitch(clip_paths, final)
    return final


def stitch(clips: list[Path], out_path: Path) -> None:
    """Concatenate independently generated clips into one mp4.

    Re-encodes via the concat filter rather than stream-copying: separate Veo
    generations are not guaranteed bit-identical in encode parameters, and a
    mismatched -c copy concat produces a file that half the platforms reject.
    """
    if not ffmpeg_available():
        raise RenderError(
            "ffmpeg and ffprobe are required to stitch clips but were not "
            "found on PATH (single-clip ads work without them)")
    args: list[str] = ["ffmpeg", "-y", "-loglevel", "error"]
    for clip in clips:
        args += ["-i", str(clip)]
    pairs = "".join(f"[{i}:v][{i}:a]" for i in range(len(clips)))
    args += ["-filter_complex",
             f"{pairs}concat=n={len(clips)}:v=1:a=1[v][a]",
             "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-c:a", "aac", "-b:a", "192k",
             "-movflags", "+faststart", str(out_path)]
    _run(args)
