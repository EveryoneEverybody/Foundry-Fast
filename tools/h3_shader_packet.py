#!/usr/bin/env python3
"""Batch-dump Halo 3 shader evidence for H3 -> Reach translation work.

This helper deliberately does not use ManagedBlam or Blender. It walks an H3EK
loose tag tree, selects shader contract / fixture tags, invokes H3 tool.exe's
`export-tag-to-xml` in batches, and builds a manifest so the resulting packet can
be inspected or fed into later census/translation tooling.

Fixture selection can come from either:
- a physical tag subtree such as levels/solo/040_voi, or
- a Baboon "Dump Tag References..." report for a scenario. The latter is the
  preferred mode because it follows the actual dependency graph into shared and
  object tags outside the level folder.

This is intentionally conservative: it gathers evidence without interpreting or
rewriting shader math.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Iterable


SHADER_SUFFIXES = {
    ".shader",
    ".shader_custom",
    ".shader_decal",
    ".shader_foliage",
    ".shader_fur",
    ".shader_fur_stencil",
    ".shader_glass",
    ".shader_halogram",
    ".shader_screen",
    ".shader_terrain",
    ".shader_water",
}

CONTRACT_RELATIVE_PATHS = (
    Path("shaders/shader.render_method_definition"),
)

REFERENCE_SUFFIX_MARKERS = (" (see above)", " (missing)")


def norm_rel(path: Path) -> str:
    return path.as_posix()


def iter_files(root: Path, predicate) -> Iterable[Path]:
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_file() and predicate(path):
            yield path


def rel_to_tags(tags_root: Path, path: Path) -> Path:
    return path.resolve().relative_to(tags_root.resolve())


def collect_contract(tags_root: Path) -> list[Path]:
    results: list[Path] = []
    for rel in CONTRACT_RELATIVE_PATHS:
        path = tags_root / rel
        if path.is_file():
            results.append(path)

    shader_root = tags_root / "shaders"
    results.extend(
        iter_files(
            shader_root,
            lambda p: p.suffix.lower() == ".render_method_option",
        )
        or []
    )
    return sorted(set(results), key=lambda p: str(p).lower())


def collect_shader_fixtures(tags_root: Path, subtree: Path) -> list[Path]:
    root = tags_root / subtree
    if root.is_file():
        return [root] if root.suffix.lower() in SHADER_SUFFIXES else []
    return sorted(
        set(iter_files(root, lambda p: p.suffix.lower() in SHADER_SUFFIXES) or []),
        key=lambda p: str(p).lower(),
    )


def _clean_reference_report_line(line: str) -> str:
    value = line.strip()
    for marker in REFERENCE_SUFFIX_MARKERS:
        if value.lower().endswith(marker):
            value = value[: -len(marker)].rstrip()
            break
    return value


def collect_shader_fixtures_from_reference_report(
    tags_root: Path,
    report_path: Path,
) -> tuple[list[Path], list[str]]:
    """Resolve shader paths from Baboon's recursive tag-reference text report."""
    text = report_path.read_text(encoding="utf-8", errors="replace")
    found: list[Path] = []
    missing: list[str] = []
    seen: set[str] = set()

    suffixes = tuple(sorted(SHADER_SUFFIXES, key=len, reverse=True))
    for raw_line in text.splitlines():
        value = _clean_reference_report_line(raw_line)
        lower = value.lower()
        if not lower.endswith(suffixes):
            continue

        rel_text = value.replace("\\", "/").lstrip("/")
        rel = Path(rel_text)
        candidate = tags_root / rel
        key = os.path.normcase(str(candidate.resolve()))
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            found.append(candidate)
        else:
            missing.append(rel.as_posix())

    return sorted(found, key=lambda p: str(p).lower()), sorted(missing, key=str.lower)


def tool_tag_argument(path: Path) -> str:
    """Return the absolute H3 tag-file path required by export-tag-to-xml."""
    return str(path.resolve())


def xml_output_path(output_root: Path, bucket: str, rel: Path) -> Path:
    return output_root / bucket / rel.parent / f"{rel.name}.xml"


def raw_output_path(output_root: Path, bucket: str, rel: Path) -> Path:
    return output_root / bucket / rel


def run_export(tool: Path, h3ek_root: Path, tag_arg: str, output: Path) -> tuple[bool, str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [str(tool), "export-tag-to-xml", tag_arg, str(output.resolve())]
    completed = subprocess.run(
        command,
        cwd=h3ek_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    )
    text = completed.stdout or ""
    return completed.returncode == 0 and output.exists(), text


def copy_raw(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Batch-export Halo 3 shader tags/RMOPs to XML for H3 -> Reach shader analysis."
    )
    parser.add_argument(
        "h3ek_root",
        type=Path,
        help="Halo 3 Editing Kit root containing tool.exe and tags/",
    )
    parser.add_argument(
        "--subtree",
        type=Path,
        default=Path("levels/solo/040_voi"),
        help="Fallback tag subtree whose shader-family tags should be dumped",
    )
    parser.add_argument(
        "--reference-report",
        type=Path,
        default=None,
        help="Baboon 'Dump Tag References...' text report. When supplied, referenced shaders replace --subtree fixture discovery.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("h3_shader_packet"),
        help="Output directory (default: ./h3_shader_packet)",
    )
    parser.add_argument(
        "--tool",
        type=Path,
        default=None,
        help="Explicit tool.exe path; defaults to <h3ek_root>/tool.exe",
    )
    parser.add_argument(
        "--no-contract",
        action="store_true",
        help="Do not dump shader.render_method_definition and tags/shaders/*.render_method_option",
    )
    parser.add_argument(
        "--no-fixtures",
        action="store_true",
        help="Do not dump shader-family fixture tags",
    )
    parser.add_argument(
        "--copy-raw",
        action="store_true",
        help="Also copy the original binary tags into the packet preserving relative paths",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print/manifest the selected tags without invoking tool.exe",
    )
    args = parser.parse_args()

    h3ek_root = args.h3ek_root.resolve()
    tags_root = h3ek_root / "tags"
    tool = args.tool.resolve() if args.tool else h3ek_root / "tool.exe"
    output_root = args.output.resolve()

    if not tags_root.is_dir():
        parser.error(f"H3 tags directory not found: {tags_root}")
    if not args.dry_run and not tool.is_file():
        parser.error(f"H3 tool.exe not found: {tool}")
    if args.reference_report is not None and not args.reference_report.is_file():
        parser.error(f"Reference report not found: {args.reference_report}")

    selected: list[tuple[str, Path]] = []
    missing_references: list[str] = []
    fixture_source = f"subtree:{norm_rel(args.subtree)}"

    if not args.no_contract:
        selected.extend(("contract", p) for p in collect_contract(tags_root))

    if not args.no_fixtures:
        if args.reference_report is not None:
            fixtures, missing_references = collect_shader_fixtures_from_reference_report(
                tags_root,
                args.reference_report,
            )
            fixture_source = f"reference_report:{args.reference_report.resolve()}"
        else:
            fixtures = collect_shader_fixtures(tags_root, args.subtree)
        selected.extend(("fixtures", p) for p in fixtures)

    deduped: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for bucket, path in selected:
        key = os.path.normcase(str(path.resolve()))
        if key in seen:
            continue
        seen.add(key)
        deduped.append((bucket, path))

    output_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "h3ek_root": str(h3ek_root),
        "tags_root": str(tags_root),
        "tool": str(tool),
        "fixture_source": fixture_source,
        "selected_count": len(deduped),
        "missing_shader_references": missing_references,
        "entries": [],
    }

    successes = 0
    failures = 0

    for index, (bucket, path) in enumerate(deduped, 1):
        rel = rel_to_tags(tags_root, path)
        tag_arg = tool_tag_argument(path)
        xml_path = xml_output_path(output_root, bucket, rel)
        entry = {
            "bucket": bucket,
            "tag": norm_rel(rel),
            "source": str(path.resolve()),
            "xml": str(xml_path.relative_to(output_root)).replace("\\", "/"),
            "status": "dry-run" if args.dry_run else "pending",
        }
        manifest["entries"].append(entry)

        print(f"[{index}/{len(deduped)}] {bucket}: {rel}")

        if args.copy_raw:
            raw_path = raw_output_path(output_root, f"raw_{bucket}", rel)
            copy_raw(path, raw_path)
            entry["raw"] = str(raw_path.relative_to(output_root)).replace("\\", "/")

        if args.dry_run:
            continue

        ok, log = run_export(tool, h3ek_root, tag_arg, xml_path)
        log_path = xml_path.with_suffix(xml_path.suffix + ".log.txt")
        if log.strip():
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(log, encoding="utf-8", errors="replace")
            entry["log"] = str(log_path.relative_to(output_root)).replace("\\", "/")

        if ok:
            entry["status"] = "ok"
            successes += 1
        else:
            entry["status"] = "failed"
            failures += 1
            print(f"  FAILED: {tag_arg}", file=sys.stderr)

    manifest["successes"] = successes
    manifest["failures"] = failures
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print()
    print(f"Selected: {len(deduped)}")
    if missing_references:
        print(f"Missing referenced shader files: {len(missing_references)}")
    if not args.dry_run:
        print(f"Exported: {successes}")
        print(f"Failed:   {failures}")
    print(f"Manifest: {manifest_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
