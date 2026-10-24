"""Compile script text in isolated Chromium without executing any game code."""

from html.parser import HTMLParser
from typing import TypedDict


class Script(TypedDict):
    content: str
    line: int
    column: int


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.scripts: list[Script] = []
        self.current: Script | None = None

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        attributes = dict(attrs)
        script_type = (attributes.get("type") or "").strip().lower()
        if script_type not in {"", "text/javascript", "application/javascript"}:
            return
        # The packager has already inlined local files. Never fetch a source here.
        if attributes.get("src"):
            return
        line, column = self.getpos()
        opening = self.get_starttag_text() or ""
        lines = opening.split("\n")
        self.current = {
            "content": "",
            "line": line + len(lines) - 1,
            "column": len(lines[-1]) if len(lines) > 1 else column + len(opening),
        }

    def handle_data(self, data):
        if self.current is not None:
            self.current["content"] += data

    def handle_endtag(self, tag):
        if tag == "script" and self.current is not None:
            self.scripts.append(self.current)
            self.current = None


def check_javascript(browser, html):
    """Return one precise error before opening the game or running any scenario.

    Runtime.compileScript only parses/compiles text; we never call runScript or
    evaluate with model output. The disposable blank page is inside the same
    networkless, secretless sandbox as gameplay validation.
    """
    parser = Scripts()
    parser.feed(html)
    parser.close()
    context = browser.new_context(accept_downloads=False)
    context.route("**/*", lambda route: route.abort())
    try:
        page = context.new_page()
        session = context.new_cdp_session(page)
        session.send("Runtime.enable")
        for index, script in enumerate(parser.scripts, 1):
            result = session.send(
                "Runtime.compileScript",
                {
                    "expression": script["content"],
                    "sourceURL": f"game-script-{index}.js",
                    "persistScript": False,
                },
            )
            if details := result.get("exceptionDetails"):
                relative_line = details.get("lineNumber", 0)
                line = script["line"] + relative_line
                column = details.get("columnNumber", 0) + 1
                if relative_line == 0:
                    column += script["column"]
                description = details.get("exception", {}).get("description") or details.get("text")
                message = str(description or "Некорректный JavaScript").split("\n", 1)[0][:400]
                return {
                    "code": "javascript_syntax",
                    "stage": "syntax",
                    "message": (
                        f"Собранный HTML index.html:{line}:{column}, "
                        f"скрипт №{index}, строка {relative_line + 1}: {message}. "
                        "Координаты относятся к экспорту; найдите этот скрипт в исходниках игры."
                    ),
                    "location": "bundled_html",
                    "file": "index.html",
                    "line": line,
                    "column": column,
                    "script_index": index,
                    "script_line": relative_line + 1,
                    "script_column": details.get("columnNumber", 0) + 1,
                }, len(parser.scripts)
        return None, len(parser.scripts)
    finally:
        context.close()
