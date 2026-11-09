#!/bin/sh
# Tạo database và tạo/nâng schema Temporal trên Postgres. Chạy lại nhiều lần vẫn an toàn.
set -eu

: "${SQL_HOST:?}" "${SQL_USER:?}" "${SQL_PASSWORD:?}"
SQL_PORT="${SQL_PORT:-5432}"
SCHEMA_DIR="${SCHEMA_DIR:-/etc/temporal/schema/postgresql/v12}"

tool() {
  temporal-sql-tool --plugin postgres12 --ep "$SQL_HOST" -p "$SQL_PORT" \
    -u "$SQL_USER" --pw "$SQL_PASSWORD" "$@"
}

setup() {
  db="$1"; dir="$2"
  tool --db "$db" create
  # setup-schema chỉ tạo bảng schema_version; chạy lại trên DB đã có thì bỏ qua.
  tool --db "$db" setup-schema -v 0.0 || echo "setup-schema $db: đã có, bỏ qua"
  tool --db "$db" update-schema -d "$SCHEMA_DIR/$dir/versioned"
}

setup temporal temporal
setup temporal_visibility visibility

# Database phụ không thuộc Temporal (ví dụ metadata của ứng dụng trên RDS), chỉ tạo nếu chưa có
for db in ${EXTRA_DATABASES:-}; do
  tool --db "$db" create
done
