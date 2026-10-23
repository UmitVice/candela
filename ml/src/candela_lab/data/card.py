import json
from typing import Any

import jinja2

from candela_lab.data.common import Example, read_jsonl
from candela_lab.paths import DATACARDS_DIR, MANIFESTS_DIR, PROCESSED_DIR, TEMPLATES_DIR


def environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES_DIR),
        autoescape=False,
        keep_trailing_newline=True,
        undefined=jinja2.StrictUndefined,
    )
    env.filters["tojson_pretty"] = lambda v: json.dumps(v, indent=2, ensure_ascii=False)
    return env


def _shorten(example: Example, limit: int = 600) -> Example:
    out = json.loads(json.dumps(example))
    for m in out["messages"]:
        if isinstance(m.get("content"), str) and len(m["content"]) > limit:
            m["content"] = m["content"][:limit] + " …"
    if out.get("tools"):
        out["tools"] = [f"<{len(out['tools'])} tool schemas>"]
    return out


def pick_examples(train: list[Example]) -> list[Example]:
    seen: set[str] = set()
    picked: list[Example] = []
    for ex in train:
        src = ex["meta"]["source"]
        if src in seen:
            continue
        seen.add(src)
        picked.append(_shorten(ex))
    return picked


def write(version: str, manifest: dict[str, Any] | None = None, train: list[Example] | None = None) -> None:
    if manifest is None:
        manifest = json.loads((MANIFESTS_DIR / f"{version}.json").read_text())
    if train is None:
        train = list(read_jsonl(PROCESSED_DIR / version / "train.jsonl"))
    text = environment().get_template("datacard.md.j2").render(m=manifest, examples=pick_examples(train))
    DATACARDS_DIR.mkdir(parents=True, exist_ok=True)
    (DATACARDS_DIR / f"{version}.md").write_text(text)
