# Temporal tự host

Docker compose chạy `temporalio/server:1.32.2`, schema bằng `temporalio/admin-tools:1.32.2` và Web UI `temporalio/ui:2.58.0`. Image server từ 1.32 không còn `auto-setup` và không còn `tctl`, nên việc tạo schema và namespace tách ra hai service chạy một lần: `temporal-schema` (script `setup-schema.sh`) và `temporal-namespace`. Server không có file config, nó tự render config từ biến môi trường `DB`, `POSTGRES_SEEDS`... như bản `auto-setup` cũ.

## Nâng từ 1.25 trên volume cũ

Không cần xóa volume `temporal-postgres-data`. `temporal-schema` gọi `update-schema` trên cả hai database `temporal` và `temporal_visibility`, nên schema 1.25 được nâng lên bản của 1.32 trước khi server khởi động. Namespace `default` đã có thì `temporal-namespace` bỏ qua. Đã thử trên một volume do `auto-setup:1.25.2` tạo, mọi thứ lên bình thường.

```
docker compose pull temporal-schema temporal temporal-namespace temporal-ui
docker compose up -d temporal-postgres temporal-schema temporal temporal-namespace temporal-ui
```

Nên sao lưu volume trước. Server đã chạy schema mới thì không quay lại 1.25 được.

## Dynamic config

`dynamicconfig/development.yaml` được mount vào container, `DYNAMIC_CONFIG_FILE_PATH` trỏ tới nó. Server đọc lại file mỗi 60 giây, không cần restart. Worker Controller (Serverless Workers) tắt vì hệ thống không dùng Lambda. Kiểm tra tên key sau khi sửa:

```
docker run --rm -v "$PWD/deploy/temporal/dynamicconfig:/dc" \
  --entrypoint temporal-server temporalio/server:1.32.2 \
  validate-dynamic-config /dc/development.yaml
```

Key sai sẽ in `warning: unregistered key`.
