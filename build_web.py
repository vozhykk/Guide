#!/usr/bin/env python3
"""Вшивает stories.json в однофайловую веб-версию."""
import json, pathlib
root = pathlib.Path(__file__).parent
data = (root / "app/src/main/assets/stories.json").read_text(encoding="utf-8")
json.loads(data)
tpl = (root / "web/template.html").read_text(encoding="utf-8")
(root / "web/index.html").write_text(tpl.replace("/*STORIES*/", data.strip()), encoding="utf-8")
print("web/index.html собран")
