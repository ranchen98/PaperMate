# Docker 日常操作指南

所有命令在项目根目录 `D:\pc-workspace\PaperMate` 下执行，需先启动 Docker Desktop。

## 前置要求

- Docker Desktop 已运行（守护进程已启动）
- `.env` 文件已按 `.env.example` 配置好 API Key
- `resources/` 目录存在（首次运行容器会自动创建子目录 `db/`、`checkpoint/`、`chroma/`、`data/`）

## 启停

```bash
docker compose up -d        # 后台启动两个服务
docker compose down         # 停止并删除容器（数据卷 resources/ 保留）
docker compose stop         # 仅停止容器（不删除，下次 start 更快）
docker compose start        # 启动已停止的容器
docker compose restart       # 重启
```

## 查看状态

```bash
docker compose ps                # 查看容器状态
docker compose logs -f           # 实时跟踪所有服务日志
docker compose logs -f backend    # 只看后端
docker compose logs -f frontend   # 只看前端
```

## 重新构建（改代码后）

```bash
docker compose build             # 重建两个镜像
docker compose build backend     # 只重建后端
docker compose build frontend    # 只重建前端
docker compose up -d --build     # 构建并立即重启（一步到位）
```

## 单独管理服务

```bash
docker compose up -d backend     # 只起后端
docker compose down backend      # 只停后端
```

## 数据与环境

改了 `.env` 后只需重启即可生效（无需重新 build）：

```bash
docker compose down
docker compose up -d
```

## 清理（慎用）

```bash
docker compose down -v            # 删除容器及其关联卷（本例无 named volume，不动 resources/）
docker rmi papermate-backend:latest papermate-frontend:latest   # 删除镜像，下次必须重新 build
```

## 访问验证

启动后打开浏览器：

- 前端：http://localhost:3000
- 后端 API：http://localhost:8000

## 日常循环速查

| 场景 | 命令 |
|---|---|
| 没改代码 | `docker compose up -d` / `docker compose down` |
| 改了代码 | `docker compose up -d --build` |
| 只改了 .env | `docker compose down` 然后 `docker compose up -d` |