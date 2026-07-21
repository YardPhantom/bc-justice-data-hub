from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.search_controls: list[tuple[str, str]] = []
        self.scripts: list[str] = []
        self.inline_scripts: list[str] = []
        self._in_script = False
        self._script_buffer: list[str] = []
        self.form_depth = 0
        self.form_actions: list[str] = []
        self.current_form_action = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "form":
            self.form_depth += 1
            self.current_form_action = values.get("action") or ""
        elif tag == "script":
            if values.get("src"):
                self.scripts.append(values["src"] or "")
            else:
                self._in_script = True
                self._script_buffer = []
        elif tag == "input":
            control_id = values.get("id") or ""
            control_type = (values.get("type") or "").lower()
            is_search = control_type == "search" or "search" in control_id.lower() or control_id == "q"
            if is_search and control_id:
                self.search_controls.append((control_id, self.current_form_action if self.form_depth else ""))

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._script_buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._in_script:
            self.inline_scripts.append("".join(self._script_buffer))
            self._in_script = False
            self._script_buffer = []
        if tag == "form" and self.form_depth:
            self.form_depth -= 1
            if not self.form_depth:
                self.current_form_action = ""


def main() -> None:
    app_js = (ROOT / 'js' / 'app.js').read_text(encoding='utf-8', errors='ignore')
    service_js = (ROOT / 'js' / 'search-service.js').read_text(encoding='utf-8', errors='ignore')
    if "types:'case,person'" not in app_js:
        raise SystemExit('Homepage case/person search does not request paged case and person records.')
    if "data/search-people.json" not in service_js or "data/search-cases.json" not in service_js:
        raise SystemExit('Case/person search does not retain static index fallback coverage.')
    if "person-profile.html?id=" not in app_js:
        raise SystemExit('Homepage person results do not link to Person Profiles.')
    checked = 0
    failures: list[str] = []
    for page in sorted(ROOT.rglob("*.html")):
        parser = PageParser()
        parser.feed(page.read_text(encoding="utf-8", errors="ignore"))
        script_text = "\n".join(parser.inline_scripts)
        for src in parser.scripts:
            script_path = (page.parent / src).resolve()
            if not script_path.exists():
                failures.append(f"{page.relative_to(ROOT)}: missing script {src}")
                continue
            script_text += "\n" + script_path.read_text(encoding="utf-8", errors="ignore")
        for control_id, form_action in parser.search_controls:
            checked += 1
            if form_action:
                target = (page.parent / form_action.split("?", 1)[0]).resolve()
                if not target.exists():
                    failures.append(f"{page.relative_to(ROOT)}#{control_id}: form target missing: {form_action}")
                continue
            if not re.search(rf"(?<![A-Za-z0-9_-]){re.escape(control_id)}(?![A-Za-z0-9_-])", script_text):
                failures.append(f"{page.relative_to(ROOT)}#{control_id}: no page-script binding found")
    if failures:
        raise SystemExit("Search-control audit failed:\n- " + "\n- ".join(failures))
    print(f"Search-control audit passed: {checked} controls across all HTML pages.")


if __name__ == "__main__":
    main()
