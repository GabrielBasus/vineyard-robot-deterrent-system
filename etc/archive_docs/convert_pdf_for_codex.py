from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a PDF into plain text or Markdown so Codex can read it reliably."
    )
    parser.add_argument("pdf", type=Path, help="Input PDF path.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output file path. Defaults to the input name with .txt or .md.",
    )
    parser.add_argument(
        "--format",
        choices=("txt", "md"),
        default="txt",
        help="Output format. Default: txt.",
    )
    parser.add_argument(
        "--layout",
        action="store_true",
        help="Preserve the PDF layout more closely.",
    )
    parser.add_argument("--first-page", type=int, default=None, help="First page to extract (1-based).")
    parser.add_argument("--last-page", type=int, default=None, help="Last page to extract (1-based).")
    return parser.parse_args()


def run_pdftotext(
    pdf_path: Path,
    *,
    layout: bool,
    first_page: int | None,
    last_page: int | None,
) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise RuntimeError("`pdftotext` was not found on PATH.")

    with tempfile.TemporaryDirectory() as tmp_dir:
        raw_output = Path(tmp_dir) / "raw.txt"
        cmd = [pdftotext, "-enc", "UTF-8"]
        if layout:
            cmd.append("-layout")
        if first_page is not None:
            cmd.extend(["-f", str(first_page)])
        if last_page is not None:
            cmd.extend(["-l", str(last_page)])
        cmd.extend([str(pdf_path), str(raw_output)])
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return raw_output.read_text(encoding="utf-8", errors="ignore")


def split_pages(raw_text: str) -> list[str]:
    pages = [page.strip() for page in raw_text.split("\f")]
    return [page for page in pages if page]


def render_txt(pdf_name: str, pages: list[str]) -> str:
    parts = [f"Source PDF: {pdf_name}", ""]
    for idx, page in enumerate(pages, start=1):
        parts.append(f"===== Page {idx} =====")
        parts.append(page)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def render_md(pdf_name: str, pages: list[str]) -> str:
    parts = [f"# {pdf_name}", ""]
    for idx, page in enumerate(pages, start=1):
        parts.append(f"## Page {idx}")
        parts.append("")
        parts.append(page)
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    pdf_path = args.pdf.resolve()
    if not pdf_path.exists():
        print(f"[pdf-convert] input file not found: {pdf_path}", file=sys.stderr)
        return 2
    if pdf_path.suffix.lower() != ".pdf":
        print(f"[pdf-convert] input is not a PDF: {pdf_path}", file=sys.stderr)
        return 2

    output_path = args.output
    if output_path is None:
        output_path = pdf_path.with_suffix(f".{args.format}")
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        raw_text = run_pdftotext(
            pdf_path,
            layout=bool(args.layout),
            first_page=args.first_page,
            last_page=args.last_page,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        if "fresh TeX installation" in stderr:
            stderr = (
                "pdftotext is installed through MiKTeX but MiKTeX setup is not finished yet. "
                "Open MiKTeX Console once or complete the first-run setup, then rerun this script."
            )
        print(f"[pdf-convert] pdftotext failed: {stderr}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - simple CLI fallback
        print(f"[pdf-convert] {exc}", file=sys.stderr)
        return 1

    pages = split_pages(raw_text)
    if args.format == "md":
        rendered = render_md(pdf_path.name, pages)
    else:
        rendered = render_txt(pdf_path.name, pages)
    output_path.write_text(rendered, encoding="utf-8")
    print(f"[pdf-convert] wrote: {output_path}")
    print(f"[pdf-convert] pages: {len(pages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
