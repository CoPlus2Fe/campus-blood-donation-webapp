# 热血行动

面向校园无偿献血主题活动的网页应用。参与者可以注册、参加现场项目、查看血值与能量、抽取初始血值并兑换奖励；工作人员通过独立后台核验项目和管理活动数据。

## 功能

### 参与者

- 学生或教职工注册，使用姓名及学号或工号登录；注册后获得唯一参与者编号。
- 按「获取血值」和「能量竞技场」浏览活动项目，查看项目规则与核验状态。
- 在设定的开放时间后参与一次幸运轮，抽取初始血值。
- 查看血值余额、可用能量、累计能量及活动记录。血值用于参与竞技场，能量可用于兑换奖励。
- 查看能量榜单前 100 名及自己的排名；榜单人数可通过环境变量调整。
- 批量兑换娃娃机游戏币，凭兑换码到现场领取。

### 工作人员

- 使用独立账号登录管理后台，按项目权限查看和核验参与记录。
- 按参与者编号、姓名、学号或工号搜索记录，处理任务申请及奖励领取。
- 最高级管理员可管理参与者、项目、奖品和工作人员账号，并对任务结算、幸运轮及三倍能量奖励进行留痕修正或撤回。

## 技术栈

- 前端：Vue 3、TypeScript、Vite
- 后端：FastAPI、SQLAlchemy
- 数据库：PostgreSQL
- 部署：Docker Compose、Nginx

## 快速开始

需要安装 Docker 和 Docker Compose，并确保 Docker 可以获取项目所需的基础镜像。

1. 复制环境变量示例：

   ```bash
   cp .env.example .env
   ```

2. 编辑 `.env`，替换 `POSTGRES_PASSWORD`、`APP_SECRET` 和 `SUPERADMIN_PASSWORD` 的占位值。`DRAW_OPENS_AT` 控制幸运轮开放时间，须包含时区信息。

3. 在项目根目录启动：

   ```bash
   docker compose up --build -d
   ```

启动后访问：

| 入口 | 本地地址 |
| --- | --- |
| 参与者页面 | <http://127.0.0.1:8080/> |
| 工作人员后台 | <http://127.0.0.1:8080/admin> |
| 健康检查 | <http://127.0.0.1:8080/api/health> |

首次启动会创建用户名为「管理员」的最高级管理员账号，密码由 `.env` 中的 `SUPERADMIN_PASSWORD` 指定。

## 常用配置

| 变量 | 用途 |
| --- | --- |
| `POSTGRES_PASSWORD` | PostgreSQL 数据库密码 |
| `APP_SECRET` | 参与者和工作人员会话的签名密钥 |
| `SUPERADMIN_PASSWORD` | 首次创建最高级管理员账号时使用的密码 |
| `DRAW_OPENS_AT` | 幸运轮开放时间，使用带时区的 ISO 8601 格式 |
| `LEADERBOARD_LIMIT` | 榜单展示人数，示例配置为 100 |
| `PUBLIC_BASE_URL` | 用户访问网站的地址，应与浏览器中的访问来源一致 |
| `DEMO_MODE` | 是否初始化演示参与者；公开部署时设为 `false` |
| `COOKIE_SECURE` | 使用 HTTPS 时设为 `true` |
| `HTTP_BIND` | 网页服务监听的主机地址 |
| `WECHAT_APP_ID`、`WECHAT_APP_SECRET` | 可选的微信公众号网页授权配置 |

公开部署时，应使用 HTTPS、设置 `COOKIE_SECURE=true`，并关闭演示数据初始化。

## 项目结构

```text
backend/app/         API、业务逻辑与数据模型
backend/tests/       后端用例
frontend/src/        参与者页面与工作人员后台
frontend/public/     静态资源
deploy/nginx.conf    前端服务与 API 转发配置
docker-compose.yml  本地容器编排
scripts/test.sh     项目检查脚本
```

## 项目检查

在项目根目录运行：

```bash
./scripts/test.sh
```

脚本运行后端用例并构建前端。

## 开源许可

本项目采用 [MIT License](LICENSE)。
