#!/usr/bin/env bash
# Sinh toàn bộ sơ đồ C4 từ workspace.dsl cho repo marketcalls/openrag. Cần Docker.
# Cách dùng: ./docs/marketcalls/architecture/render.sh
set -euo pipefail
cd "$(dirname "$0")"

rm -rf diagrams && mkdir diagrams

# 1. Structurizr DSL → C4-PlantUML (.puml)
docker run --rm -v "$PWD":/usr/local/structurizr structurizr/structurizr export \
  -workspace /usr/local/structurizr/workspace.dsl -format plantuml/c4plantuml \
  -output /usr/local/structurizr/diagrams

cd diagrams
for f in structurizr-*.puml; do mv "$f" "${f#structurizr-}"; done

# 2. Xử lý thứ tự tag nếu có tag kép
for f in *.puml; do
  python3 - "$f" <<'PY'
import sys
p = sys.argv[1]
lines = open(p, encoding="utf-8").read().split("\n")
tags = [i for i, l in enumerate(lines) if l.startswith("AddElementTag(")]
if tags:
    block = [lines[i] for i in tags]
    combo = [l for l in block if l.startswith('AddElementTag("Container,') or l.startswith('AddElementTag("Component,')]
    rest = [l for l in block if l not in combo]
    lines[tags[0]:tags[-1] + 1] = rest + combo
open(p, "w", encoding="utf-8").write("\n".join(lines))
PY
done

# 3. PlantUML → SVG + PNG
docker run --rm -v "$PWD":/data plantuml/plantuml -charset UTF-8 -tsvg "/data/*.puml"
docker run --rm -v "$PWD":/data plantuml/plantuml -charset UTF-8 -tpng "/data/*.puml"
ls -la
