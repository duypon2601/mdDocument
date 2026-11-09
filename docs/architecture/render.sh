#!/usr/bin/env bash
# Sinh lại toàn bộ sơ đồ C4 từ một file DSL. Cần Docker.
# Cách dùng: ./docs/architecture/render.sh                                  (workspace.dsl → diagrams/)
set -euo pipefail
cd "$(dirname "$0")"

WS="${1:-workspace.dsl}"
OUT="${2:-diagrams}"

rm -rf "$OUT" && mkdir "$OUT"

# 1. Structurizr DSL → C4-PlantUML (.puml)
docker run --rm -v "$PWD":/usr/local/structurizr structurizr/structurizr export \
  -workspace "/usr/local/structurizr/$WS" -format plantuml/c4plantuml \
  -output "/usr/local/structurizr/$OUT"

cd "$OUT"
for f in structurizr-*.puml; do mv "$f" "${f#structurizr-}"; done

# 2. PlantUML coi tag "Container,Temporal" là hai tag riêng, nên style "Container" khai báo sau
#    sẽ đè màu tím của Temporal. Dời các style có nhiều tag xuống cuối khối AddElementTag.
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
ls
