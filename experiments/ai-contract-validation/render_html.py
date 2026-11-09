"""Explicitly rebuild this bundle's HTML article from Markdown; never runs validation."""
import argparse
import html
import re
from pathlib import Path

from validate import HERE, read_json


def inline(text):
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", text)


def article(markdown):
    lines, parts, toc = markdown.splitlines(), [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        heading = re.match(r"^(#{1,6}) (.*)", line)
        if heading:
            level, label, sid = len(heading[1]), heading[2], "section-" + str(len(parts))
            parts.append(f'<h{level} id="{sid}">{inline(label)}</h{level}>')
            if level == 2:
                toc.append((sid, label))
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [x.strip() for x in lines[i].strip().strip("|").split("|")]
                i += 1
                if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
                    continue
                rows.append(cells)
            if not rows or any(len(row) != len(rows[0]) for row in rows):
                raise ValueError("Inconsistent Markdown table columns")
            parts.append('<div class="table-wrap"><table><thead><tr>' + "".join("<th>" + inline(cell) + "</th>" for cell in rows[0]) + "</tr></thead><tbody>" + "".join("<tr>" + "".join("<td>" + inline(cell) + "</td>" for cell in row) + "</tr>" for row in rows[1:]) + "</tbody></table></div>")
            continue
        if re.match(r"^\d+\. ", line):
            items = []
            while i < len(lines) and re.match(r"^\d+\. ", lines[i]):
                items.append(re.sub(r"^\d+\. ", "", lines[i]))
                i += 1
            parts.append("<ol>" + "".join("<li>" + inline(item) + "</li>" for item in items) + "</ol>")
            continue
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "|")) and not re.match(r"^\d+\. ", lines[i]):
            para.append(lines[i])
            i += 1
        parts.append("<p>" + inline(" ".join(para)) + "</p>")
    nav = '<nav aria-label="문서 목차">' + "".join(f'<a href="#{sid}">{inline(label)}</a>' for sid, label in toc) + "</nav>"
    return "".join(parts[:4]) + nav + "".join(parts[4:])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=HERE / "artifacts")
    args = parser.parse_args(argv)
    try:
        manifest = read_json(args.bundle / "bundle.json")
        paths = [(args.bundle / manifest[key]).resolve() for key in ["markdown", "html"]]
        if not all(p.is_relative_to(args.bundle.resolve()) for p in paths):
            raise ValueError("Artifact path outside bundle")
        markdown = paths[0].read_text(encoding="utf-8-sig")
        template = paths[1].read_text(encoding="utf-8-sig")
        if len(re.findall(r"<article>.*?</article>", template, re.S)) != 1:
            raise ValueError("Expected one HTML article")
        result = re.sub(r"<article>.*?</article>", lambda _: "<article>" + article(markdown) + "</article>", template, flags=re.S)
        paths[1].write_text(result, encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError):
        print("Cannot render this bundle. Check bundle.json and the supported Markdown structure.")
        return 1
    print("Rebuilt the HTML article. Run validate.py next.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
