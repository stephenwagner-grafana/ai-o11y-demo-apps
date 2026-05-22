#!/usr/bin/env python3
"""Generate the deterministic synthetic-user pool for the loadgen.

Produces `config/users.yaml`, the runtime source-of-truth for which synthetic
users exist, what their emails are, and what AI cohort they belong to.

USAGE:
    python tools/regenerate-users.py --seed 42
    python tools/regenerate-users.py --seed 99 --nc-count 300 --sb-count 50
    python tools/regenerate-users.py --out /tmp/users.yaml

Cohort logic (per docs/LOADGEN.md):
  NeonCart:  75% non-ai, 25% ai
             Of the 25% ai users:  60% gift-finder, 30% chatbot, 10% both
  NC email domains: 40% gmail.com / 40% aol.com / 20% yahoo.com
  SupportBot: 100% ai (no cohort field); email domain defaults to acme.com
              (loadgen overrides at runtime via SB_USER_DOMAIN env var)

Determinism: same --seed always produces the same users. Customer can hand-edit
the resulting YAML and re-runs of the loadgen will preserve those edits — only
re-running this script overwrites them.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path

try:
    from faker import Faker
except ImportError:
    sys.stderr.write(
        "Missing dependency: faker. Install with:  pip install faker\n"
    )
    sys.exit(2)


# Cohort splits — kept as constants so they're easy to find + override
NON_AI_FRACTION = 0.75
AI_GIFT_FINDER_FRACTION = 0.60   # of the AI subset
AI_CHATBOT_FRACTION = 0.30       # of the AI subset
AI_BOTH_FRACTION = 0.10          # of the AI subset

NC_EMAIL_DOMAINS = [
    ("gmail.com", 0.40),
    ("aol.com", 0.40),
    ("yahoo.com", 0.20),
]
SB_DEFAULT_DOMAIN = "acme.com"


def _slug(name: str) -> str:
    """firstname.lastname slug used in the email local-part."""
    return name.strip().lower().replace(" ", ".").replace("'", "")


def _pick_domain(rng_index: int, total: int) -> str:
    """Pick a domain by deterministic position within the NC pool.

    Position-based instead of random so the 40/40/20 split is exact rather than
    approximate. Reordered by sorted index so the YAML doesn't end up grouped.
    """
    # Cumulative cutoffs from the position fraction
    pos = rng_index / max(total, 1)
    cum = 0.0
    for domain, weight in NC_EMAIL_DOMAINS:
        cum += weight
        if pos < cum:
            return domain
    return NC_EMAIL_DOMAINS[-1][0]


def _generate_unique_names(fake: Faker, count: int) -> list[str]:
    """Generate `count` unique full names. Faker can collide at scale —
    if a name is a dup, append a numeric suffix so the email stays unique.
    """
    seen: set[str] = set()
    names: list[str] = []
    attempts = 0
    while len(names) < count:
        candidate = fake.name()
        # Strip suffixes/prefixes ("Mr.", "Jr.", "MD") that faker sometimes adds —
        # they make ugly emails.
        candidate = candidate.replace("Mr. ", "").replace("Mrs. ", "")
        candidate = candidate.replace("Ms. ", "").replace("Dr. ", "")
        for suffix in (" Jr.", " Sr.", " II", " III", " IV", " MD", " DDS", " PhD", " DVM"):
            if candidate.endswith(suffix):
                candidate = candidate[: -len(suffix)]
        candidate = candidate.strip()

        slug = _slug(candidate)
        if slug and slug not in seen:
            seen.add(slug)
            names.append(candidate)
        attempts += 1
        if attempts > count * 50:
            # Safety: faker exhausted, fall back to numeric suffix
            base_slug = _slug(candidate or f"user{len(names)}")
            i = 1
            while f"{base_slug}{i}" in seen:
                i += 1
            seen.add(f"{base_slug}{i}")
            names.append(f"{candidate} {i}")
    return names


def _assign_nc_cohorts(count: int) -> list[str]:
    """Build the cohort list for NC users.

    Uses round() on each sub-bucket so the totals land as close to the spec
    as possible. The 'non-ai' bucket absorbs any rounding remainder so the
    list length is always exactly `count`.
    """
    ai_total = round(count * (1 - NON_AI_FRACTION))
    gift_only = round(ai_total * AI_GIFT_FINDER_FRACTION)
    chatbot_only = round(ai_total * AI_CHATBOT_FRACTION)
    both = ai_total - gift_only - chatbot_only  # remainder lands in "both"
    if both < 0:
        # Rare rounding case — peel from gift_only first since it's the largest
        gift_only += both
        both = 0
    non_ai = count - (gift_only + chatbot_only + both)

    cohorts = (
        ["non-ai"] * non_ai
        + ["gift-finder"] * gift_only
        + ["chatbot"] * chatbot_only
        + ["both"] * both
    )
    # Position 0..count-1 is what determines email domain, so shuffle here.
    # But we want determinism: use a fixed pattern instead of random.shuffle.
    # Interleave by modulo so cohorts are spread evenly through the list.
    interleaved = [""] * count
    bucket_sizes = {
        "non-ai": non_ai,
        "gift-finder": gift_only,
        "chatbot": chatbot_only,
        "both": both,
    }
    cursors = {k: 0 for k in bucket_sizes}
    stride = {k: count / v if v else float("inf") for k, v in bucket_sizes.items()}
    # Round-robin fill: at each slot, place whichever bucket has the smallest
    # (cursor * stride) — produces an even spread without randomness.
    placed = 0
    slot = 0
    while placed < count:
        # Pick the bucket whose next "ideal" position is closest to current slot
        best = None
        best_score = float("inf")
        for k, v in bucket_sizes.items():
            if cursors[k] >= v:
                continue
            score = cursors[k] * stride[k]
            if score < best_score:
                best_score = score
                best = k
        if best is None:
            break
        interleaved[slot] = best
        cursors[best] += 1
        placed += 1
        slot += 1

    assert "" not in interleaved, "cohort interleave bug: empty slot"
    return interleaved


def build_nc_users(fake: Faker, count: int) -> list[dict]:
    names = _generate_unique_names(fake, count)
    cohorts = _assign_nc_cohorts(count)
    users = []
    for idx, (name, cohort) in enumerate(zip(names, cohorts)):
        domain = _pick_domain(idx, count)
        users.append({
            "id": f"nc_{idx + 1:03d}",
            "name": name,
            "email": f"{_slug(name)}@{domain}",
            "cohort": cohort,
        })
    return users


def build_sb_users(fake: Faker, count: int, domain: str = SB_DEFAULT_DOMAIN) -> list[dict]:
    names = _generate_unique_names(fake, count)
    users = []
    for idx, name in enumerate(names):
        users.append({
            "id": f"sb_{idx + 1:03d}",
            "name": name,
            "email": f"{_slug(name)}@{domain}",
        })
    return users


def render_yaml(nc_users: list[dict], sb_users: list[dict]) -> str:
    """Hand-roll the YAML so we don't depend on PyYAML.

    Schema is flat enough that this is more reliable than PyYAML's default
    flow styles, which sometimes wrap or quote in unhelpful ways.
    """
    lines = []
    lines.append("# Generated by tools/regenerate-users.py — do not auto-overwrite.")
    lines.append("# Hand-edits survive across loadgen restarts; only re-running the")
    lines.append("# regen script clobbers this file.")
    lines.append("")
    lines.append("neoncart:")
    for u in nc_users:
        lines.append(f"  - id: {u['id']}")
        lines.append(f"    name: {u['name']}")
        lines.append(f"    email: {u['email']}")
        lines.append(f"    cohort: {u['cohort']}")
    lines.append("")
    lines.append("supportbot:")
    for u in sb_users:
        lines.append(f"  - id: {u['id']}")
        lines.append(f"    name: {u['name']}")
        lines.append(f"    email: {u['email']}")
    lines.append("")
    return "\n".join(lines)


def summarize(nc_users: list[dict], sb_users: list[dict]) -> str:
    buckets = {"non-ai": 0, "gift-finder": 0, "chatbot": 0, "both": 0}
    for u in nc_users:
        buckets[u["cohort"]] = buckets.get(u["cohort"], 0) + 1
    return (
        f"Generated {len(nc_users)} NC users "
        f"({buckets['non-ai']} non-ai / "
        f"{buckets['gift-finder']} gift-finder / "
        f"{buckets['chatbot']} chatbot / "
        f"{buckets['both']} both) "
        f"+ {len(sb_users)} SB users"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate config/users.yaml — the synthetic-user pool the loadgen reads."
    )
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default 42)")
    parser.add_argument("--nc-count", type=int, default=200, help="NeonCart user count (default 200)")
    parser.add_argument("--sb-count", type=int, default=30, help="SupportBot user count (default 30)")
    parser.add_argument(
        "--out",
        type=str,
        default="config/users.yaml",
        help="Output path (default: config/users.yaml)",
    )
    parser.add_argument(
        "--sb-domain",
        type=str,
        default=SB_DEFAULT_DOMAIN,
        help=f"Email domain for SB users (default: {SB_DEFAULT_DOMAIN})",
    )
    args = parser.parse_args()

    if args.nc_count < 1 or args.sb_count < 1:
        sys.stderr.write("--nc-count and --sb-count must be >= 1\n")
        return 2

    fake = Faker()
    Faker.seed(args.seed)

    nc_users = build_nc_users(fake, args.nc_count)
    sb_users = build_sb_users(fake, args.sb_count, domain=args.sb_domain)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_yaml(nc_users, sb_users))

    print(summarize(nc_users, sb_users))
    print(f"Wrote {out_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
