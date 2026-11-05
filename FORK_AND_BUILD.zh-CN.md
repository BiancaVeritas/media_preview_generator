# 把汉化版写进自己的 GitHub 仓库，并生成 compose 可用的镜像

这份仓库已经包含：

- 中文界面（默认 `zh-CN`，右上角可切 English）
- `.strm` 支持
- `Dockerfile.zh`：在上游镜像上只替换应用代码，构建只要几十秒
- `.github/workflows/zh-image.yml`：推送到 GitHub 后自动构建并推送到 GHCR

下面以 GitHub 用户名 `YOURNAME`、仓库名 `media_preview_generator` 为例，替换成你自己的即可。

## 1. 在 GitHub 上 Fork

打开 <https://github.com/stevezau/media_preview_generator/fork>，点 **Create fork**。
得到 `https://github.com/YOURNAME/media_preview_generator`。

## 2. 把本地这份改动推上去

在 **你自己的终端**（不是聊天窗口）里执行：

```powershell
cd C:\Users\July_RuoMoli\Documents\deepseek-harness\default-workspace\media_preview_generator

# 第一次提交前设置身份（写成你自己的 GitHub 名字和邮箱）
git config user.name "YOURNAME"
git config user.email "you@example.com"

git checkout -b zh-ui-strm
git add -A
git commit -m "feat: STRM support and Chinese UI"

# 指向你的 fork；这一步可能会弹出 GitHub 登录窗口
git remote add fork https://github.com/YOURNAME/media_preview_generator.git
git push -u fork zh-ui-strm
```

## 3. 等 Actions 自动构建

推送后打开：

```
https://github.com/YOURNAME/media_preview_generator/actions
```

`Build Chinese image` 这个 workflow 会自动跑（也可以点 **Run workflow** 手动触发）。
大约 1–2 分钟完成，产物地址固定为：

```
ghcr.io/YOURNAME/media_preview_generator:zh
```

> GitHub 用户名有大写字母也没关系，workflow 会自动转成小写。
> GHCR 的包默认是 **Private**。想不登录直接 `docker compose pull`，去
> `https://github.com/users/YOURNAME/packages/container/media_preview_generator/settings`
> → **Danger Zone** → **Change visibility** → **Public**。
> 不想公开也可以保持 Private，在服务器上先 `docker login ghcr.io`（用带 `read:packages` 的 PAT）。

## 4. 填进 docker-compose.yml

```yaml
services:
  media-preview-generator:
    image: ghcr.io/YOURNAME/media_preview_generator:zh
    container_name: media-preview-generator
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - PUID=1000
      - PGID=1000
    volumes:
      - /path/to/media:/media
      - /path/to/plex/config:/plex
      - /path/to/app/config:/config
    # 下面这些按你原来的 compose 保留：
    # devices:
    #   - /dev/dri:/dev/dri
    # deploy:
    #   resources:
    #     reservations:
    #       devices:
    #         - driver: nvidia
    #           count: all
    #           capabilities: [gpu]
```

然后：

```bash
docker compose pull
docker compose up -d
```

打开页面应该直接是中文；右上角「文A」按钮可以切回 English。

## 不想用 Actions？本机构建

```bash
cd media_preview_generator
docker build -f Dockerfile.zh -t media-preview-generator:zh .
```

compose 里写：

```yaml
image: media-preview-generator:zh
```

（本机构建不需要推送仓库，也不需要 GHCR。）

## 以后上游更新了

```bash
git fetch origin
git rebase origin/main        # 或 origin/dev
git push fork zh-ui-strm      # 触发 Actions 重新构建 :zh
```

如果只想更新镜像、不改代码，也可以在 Actions 页面点 **Run workflow**。
