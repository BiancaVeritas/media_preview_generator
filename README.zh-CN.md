<!-- PROJECT SHIELDS: reference-style (defined at the bottom), amber like the docs site. -->
> 中文版说明。English README: [README.md](README.md)

<div align="center">

[![Build][build-shield]][build-url]
[![Release][release-shield]][release-url]
[![Coverage][codecov-shield]][codecov-url]
[![Docker Pulls][docker-shield]][docker-url]
[![Image Size][size-shield]][docker-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![MIT License][license-shield]][license-url]
[![AI-Assisted][ai-shield]][ai-url]
[![Buy me a coffee][kofi-shield]][kofi-url]

</div>

<div align="center">
  <img src="docs/images/icon.svg" alt="" width="110" height="110">

  <h1 align="center">Media Preview Generator</h1>

  <p align="center">
    <strong>媒体服务器最慢的那些任务，交给你的 GPU 来做。</strong>
    <br />
    Media Preview Generator 为 Plex、Emby 和 Jellyfin 生成预览图，以及跳过片头和跳过片尾的标记。
    它会在 Sonarr 或 Radarr 导入文件的那一刻开始，并把结果同时发送到每一台服务器。
    <br />
    自托管，运行在 Docker 中。
    <br />
    <br />
    <a href="https://mediapreviewgenerator.dev/"><strong>浏览文档 »</strong></a>
    <br />
    <br />
    <a href="#quick-start">快速开始</a>
    &middot;
    <a href="https://mediapreviewgenerator.dev/comparison/">与其他方案对比</a>
    &middot;
    <a href="https://github.com/stevezau/media_preview_generator/discussions">提个问题</a>
    &middot;
    <a href="https://github.com/stevezau/media_preview_generator/issues/new?labels=bug">报告问题</a>
  </p>
</div>

![Plex、Jellyfin 和 Emby 网页播放器中的 Tears of Steel，每个播放器的进度条上都显示着预览缩略图](docs/images/players-3up.webp)

<sub>测试服务器上的 Plex、Jellyfin 和 Emby 网页播放器，同一部影片都暂停在同一处拖动位置。这些缩略图由本应用生成。Tears of Steel，(CC) Blender Foundation | mango.blender.org，[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/)。</sub>

## 功能概览

Plex、Emby 和 Jellyfin 自己也能生成预览图，但它们是在服务器内部完成的，大多靠 CPU，而且大多按计划执行。在一个大媒体库上，这可能要花上几天，而今晚才到的那一集，可能要等到下一个维护时段才有时间轴。

**Media Preview Generator 用你的 GPU，在文件到达时逐个生成。**当多台服务器持有同一个文件时，它只解码一次，再分别写出每台服务器自己的格式。

**它还会添加跳过片头和跳过片尾标记。**它为每个文件找出一次片头和片尾，再把标记发送给拥有该文件的每台服务器。拿不准时，它什么都不发；你可以在 Inspector 里添加或调整标记。

**GPU 可以放在另一台机器上。**把它添加为[工作节点](docs/remote-nodes.md)；队列和每一次写入仍由本应用负责。

## STRM 支持

本工具可以直接处理 `.strm` 文件（Emby / Jellyfin 的 strm 媒体库，常用于云盘、Alist、HTTP 直链）。程序会读取 `.strm` 文件里的第一行 URL 或本地路径，把它交给 FFmpeg / ffprobe 解码；预览图、BIF、trickplay 仍然写在 `.strm` 文件旁边，Plex 的 bundle 哈希也按 `.strm` 文件本身计算。

支持 http/https/rtsp/rtmp 等 FFmpeg 能读取的协议；如果 `.strm` 指向本地或网络挂载路径，也支持相对路径（相对 `.strm` 所在目录）和嵌套 `.strm`。

- 注意：`.strm` 指向的地址必须能被本工具容器访问。
- Plex 需要其自身支持 strm 媒体库。
- MediaInfo 的某些构建无法读取网络 URL，此时程序会自动改用 ffprobe 读取 HDR 等信息。

接受的形式和排查方法见 [STRM 指南](docs/strm.md)。

## 界面预览

| 它会找出拥有该文件的每一台服务器 |
| --- |
| ![服务器页面，Home Plex、Home Jellyfin 和 Home Emby 各有一张卡片，分别显示各自的地址和已启用的媒体库](docs/images/tour-resolve.webp) |

| 每个文件只做一次 GPU 处理 |
| --- |
| ![工作进程面板以表格呈现：忙碌的 GPU 和 CPU 工作进程显示百分比、速度和预计剩余时间，空闲的工作进程折叠成一行，gpu-box 节点上还有一个工作进程组](docs/images/tour-extract.webp) |

| 每台服务器拿到自己的格式 |
| --- |
| ![一个已完成任务的详情，打开的是文件标签页：一个文件被标记为已生成，其服务器列出 Home Plex、Home Jellyfin 和 Home Emby](docs/images/tour-publish.webp) |

| 它会等待响应慢的服务器 |
| --- |
| ![任务队列有四个条目：Tears of Steel 正在以 62% 运行，Sintel 处于等待中并显示重试 2/5、重试将在 4 分钟后开始，Big Buck Bunny 已完成，Elephants Dream 在等待中](docs/images/tour-retry.webp) |

<sub>应用截图来自一套使用虚构服务器的测试环境；任务标题都是开放版权的影片。</sub>

## 功能特性

**GPU 优先，需要时才用 CPU**
- **传入的每一块 GPU 都能用。**Linux 上支持 NVIDIA、Intel 和 AMD；Windows 上通过 WSL2 支持 NVIDIA。
- **具名工作进程组。**为每个组挑选设备、任务类型、工作进程数量和每周可用时长。[工作进程指南](docs/guides.md#worker-groups-and-availability)。
- **远程节点。**把另一台机器上的 GPU 或 CPU 用作工作节点。对于跑在另一台机器上的 Plex（包括 Windows 上的 Plex），Plex 数据库节点会在 Plex 旁边打开它的数据库。队列、令牌和每一次写入仍由本应用负责。[节点指南](docs/remote-nodes.md)。
- **内置 CPU 回退。**某块 GPU 解不了的文件，会先依次试你的其他 GPU，再交给 CPU。
- **关键帧跳过。**当文件的关键帧间距允许时，在关键帧之间直接跳转。

**自动启动**
- **Webhook。**Sonarr、Radarr、Sportarr、Tdarr、FileFlows、Plex（Plex Pass）、Emby（Premiere）和 Jellyfin，或任何带路径的 JSON。Sonarr、Radarr 和这三台服务器可以共用一个 URL。
- **计划任务。**最近添加轮询，外加 cron 和间隔两种计划任务。
- **处理单个文件或文件夹。**按标题搜索你的服务器（整部剧、一部电影或某一集），或浏览媒体文件夹，只为这些内容生成预览图。
- **Plex 不用等扫描。**文件/文件夹任务和基于路径的 Webhook 直接从媒体本身生成，即使 Plex 离线或尚未索引该文件。
- **重试与跳过。**服务器索引新文件期间，默认在 1、2、5、15 和 60 分钟后重试，并跳过预览图已是最新的文件。

**一次解码，服务所有服务器**
- **沿用每台服务器自己的格式。**Plex 数据文件夹里的 BIF、Emby 视频旁边的 BIF，以及 Jellyfin 的进度条预览图切片（放在视频旁边，或配合配套插件放进 Jellyfin 的数据文件夹）。
- **设置体检。**检查每台服务器的设置，并逐个媒体库给出修复建议。

**选择要生成的内容。**按添加日期筛选手动或计划任务的媒体库扫描，保留最近 X 个可用电视剧季，或指定电影的上映年份区间。可以组合多个筛选条件，同时保留已有的预览图。参见[媒体库扫描指南](docs/guides.md#choosing-media-for-a-library-scan)。

**准确的色彩**
- **HDR 色调映射。**对 HDR10、HLG 和 HDR10+ 做色调映射，并使用 Dolby Vision profile 7 和 8 里的 HDR10 层。Profile 5 需要一块带硬件 Vulkan 驱动的 GPU。

**跳过片头与跳过片尾**
- **只找一次，发给每台服务器。**从文件的章节、在线跳过数据库（TheIntroDB、IntroDB.app、SkipDB）、本季主题曲，或者片尾字幕本身（更快时直接在 GPU 上读取）中找出片头和片尾，然后把标记发送给每台拥有该文件的服务器。拿不准时，它不会去猜，而是一个标记都不发；你可以在 Inspector 里添加或调整标记。默认关闭，直到你为某台服务器[开启它](docs/guides.md#turning-it-on)。
- **随时可改。**Tools → Inspector 可以手动调整、添加和锁定某个文件的标记，设置体检则会检查每台服务器的片头与片尾配置。
- **Plex。**服务器端需要 Plex Pass，观看者（或其 Plex Home）也需要。应用运行在 Plex 所在机器上，或通过 [Plex 数据库节点](docs/guides.md#plex-on-another-machine-the-plex-database-node)运行在它旁边。
- **Jellyfin。**Jellyfin 10.11 或 12.0，并安装 Media Preview Bridge 插件（就是进度条预览图用的那个）。
- **Emby。**Emby 4.9 或 4.10，并安装适用于 Emby 的 Media Preview Bridge 插件。跳过片头需要 Emby Premiere；跳过片尾不需要。

**Plex 响度**
- **响度分析。**在 CPU 工作进程组上测量音轨，并把结果存入 Plex。默认关闭，直到你为 Plex 1.43.4.x 或 1.43.5.x 的服务器[开启它](docs/plex-loudness-normalization.md)；与片头与片尾功能相互独立。

## 适用场景

Plex 的[章节缩略图](https://mediapreviewgenerator.dev/guides/#plex-chapter-thumbnails)和[响度](https://mediapreviewgenerator.dev/plex-loudness-normalization/)会写入 Plex 的数据库，所以需要把本应用装在 Plex 所在机器上，或者装在它旁边的一个 [Plex 数据库节点](docs/remote-nodes.md)上。

它与 Sonarr、Radarr、Tdarr 并排运行，接管媒体服务器自己的预览任务。一旦它跑起来，服务器自身的生成就只是把同一件活干了第二遍。应用的[设置体检](docs/guides/previews-readiness.md)标签页会告诉你每台服务器上该关掉哪项设置、该保留哪项：把 Jellyfin 的进度条预览图关掉，会删掉本应用写入的切片。如果你服务器自带的生成器还跟得上，那就不需要它：参见[与其他方案对比](https://mediapreviewgenerator.dev/comparison/)。

<a id="quick-start"></a>

## 快速开始

**你需要：**Docker · 能从容器访问到的 Plex、Emby 或 Jellyfin（Jellyfin 10.10 或更新版本）· 预览图写入位置的写权限：Plex 的数据文件夹，或 Emby 和 Jellyfin 的媒体文件夹。GPU 是可选的：宿主机上装好驱动，Linux 上的 NVIDIA 还需要 NVIDIA Container Toolkit。

```bash
docker run -d \
  --name media-preview-generator \
  --restart unless-stopped \
  -p 8080:8080 \
  --device /dev/dri:/dev/dri \
  -e PUID=1000 -e PGID=1000 \
  -v /path/to/media:/media \
  -v /path/to/plex/config:/plex \
  -v /path/to/app/config:/config \
  stevezzau/media_preview_generator:latest
```

- Intel 或 AMD：像上面那样用 `--device /dev/dri`。NVIDIA：换成 `--gpus all -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=all`。没有 GPU，或者在 Windows、macOS 上？把 `--device /dev/dri` 那一行删掉。
- Plex 会把数据写进 `/plex`，所以媒体可以挂成 `:ro`。Emby 和采用默认布局的 Jellyfin 会写在各视频旁边，因此对它们来说媒体挂载必须可读写。不用 Plex？去掉 `/plex` 挂载。
- 打开 `http://YOUR_IP:8080`，用应用配置文件夹里 `auth.json` 保存的令牌登录（也可以用 `-e WEB_AUTH_TOKEN=...` 固定你自己的令牌），然后按设置向导走一遍。
- 镜像名是 `stevezzau/media_preview_generator`。两个 z 是 Docker Hub 账号的名字，不是笔误。

Docker Compose、Unraid 和 GPU 的详细说明：[快速上手](docs/getting-started.md)。

## 文档

文档同时也有网站版：**[mediapreviewgenerator.dev](https://mediapreviewgenerator.dev/)**。

| 页面 | 内容 |
| --- | --- |
| [快速上手](docs/getting-started.md) | Docker、GPU、挂载、Unraid、网络 |
| [与其他方案对比](docs/comparison.md) | Plex、Jellyfin 和 Emby 内置生成功能的并排比较 |
| [指南](docs/guides.md) | Web UI、Webhook、计划任务、故障排查 |
| [远程节点](docs/remote-nodes.md) | 另一台机器的 GPU，以及另一台机器或 Windows 上的 Plex |
| [多服务器](docs/multi-server.md) | 用同一个实例管理 Plex、Emby 和 Jellyfin |
| [参考](docs/reference.md) | 所有设置、环境变量和 API 端点 |
| [FAQ](docs/faq.md) | Windows、GPU、内存、被跳过的文件 |
| [为什么 Plex 预览图这么慢](docs/plex-preview-thumbnails-slow.md) | Plex 做了什么，以及该改什么 |
| [用 GPU 生成 Plex 预览图](docs/plex-preview-thumbnails-gpu.md) | 把 Plex 的预览任务迁到 GPU 上 |
| [更快的 Jellyfin 进度条预览图](docs/jellyfin-trickplay-gpu.md) | 先调 Jellyfin 自己的设置，再上 GPU |
| [用 GPU 生成 Emby BIF 预览图](docs/emby-bif-thumbnails-gpu.md) | 在 GPU 上生成、放在每个视频旁边的 Emby BIF |
| [在 Sonarr 或 Radarr 导入时生成预览图](docs/sonarr-radarr-preview-thumbnails.md) | Webhook、静默期、重试 |
| [HDR 和 Dolby Vision 预览图](docs/hdr-dolby-vision-thumbnails.md) | 色调映射，以及 Dolby Vision 5 的注意事项 |
| [跳过片头与跳过片尾](docs/skip-intro-credits.md) | 每台服务器需要什么、如何查找、有哪些限制 |

## 支持项目

它免费，采用 MIT 许可证。帮不帮忙，全凭自愿。

- **[在 GitHub 上加星](https://github.com/stevezau/media_preview_generator)**：不花钱，而且别的服务器主就是这样找到它的。
- **[在 Ko-fi 上请我喝杯咖啡](https://ko-fi.com/stevezau)**：不需要账号。

## 获取帮助

- **预览图不显示？**打开应用里该服务器的设置体检标签页，它会指出挡路的那项设置。
- **不确定是不是 bug？**到[讨论区](https://github.com/stevezau/media_preview_generator/discussions)问问。
- **发现 bug 了？**[提交一个 issue](https://github.com/stevezau/media_preview_generator/issues/new?labels=bug)，附上应用版本和你试过的操作。

<a id="license"></a>

## 许可证

MIT，参见 [LICENSE](LICENSE)。开发过程有 AI 辅助（Claude）；每一处改动都经过审查和测试。

<!-- Amber #a06a00, not the brand #e5a00d: shields.io always draws white text, and white on #e5a00d fails
     contrast. Value badges take `color=`; build, coverage and issues take `labelColor=` so their message
     keeps its status colour (a red build must still look red). The build badge follows pushes to `dev`,
     because CI doesn't run on pushes to `main`: a `branch=main` badge would show one old run forever. -->
[build-shield]: https://img.shields.io/github/actions/workflow/status/stevezau/media_preview_generator/ci.yml?branch=dev&event=push&style=for-the-badge&label=build&labelColor=a06a00
[build-url]: https://github.com/stevezau/media_preview_generator/actions/workflows/ci.yml?query=branch%3Adev+event%3Apush
[release-shield]: https://img.shields.io/github/v/release/stevezau/media_preview_generator?style=for-the-badge&label=release&color=a06a00
[release-url]: https://github.com/stevezau/media_preview_generator/releases
[codecov-shield]: https://img.shields.io/codecov/c/github/stevezau/media_preview_generator?style=for-the-badge&labelColor=a06a00
[codecov-url]: https://codecov.io/gh/stevezau/media_preview_generator
[docker-shield]: https://img.shields.io/docker/pulls/stevezzau/media_preview_generator?style=for-the-badge&color=a06a00
[docker-url]: https://hub.docker.com/r/stevezzau/media_preview_generator
[size-shield]: https://img.shields.io/docker/image-size/stevezzau/media_preview_generator/latest?style=for-the-badge&label=image&color=a06a00
[stars-shield]: https://img.shields.io/github/stars/stevezau/media_preview_generator.svg?style=for-the-badge&color=a06a00
[stars-url]: https://github.com/stevezau/media_preview_generator/stargazers
[issues-shield]: https://img.shields.io/github/issues/stevezau/media_preview_generator.svg?style=for-the-badge&labelColor=a06a00
[issues-url]: https://github.com/stevezau/media_preview_generator/issues
[license-shield]: https://img.shields.io/github/license/stevezau/media_preview_generator.svg?style=for-the-badge&color=a06a00
[license-url]: https://github.com/stevezau/media_preview_generator/blob/main/LICENSE
[ai-shield]: https://img.shields.io/badge/AI--Assisted-Claude-8A2BE2?style=for-the-badge&logo=anthropic&logoColor=white
[ai-url]: #license
[kofi-shield]: https://img.shields.io/badge/Buy%20me%20a%20coffee-FF5E5B?style=for-the-badge&logo=kofi&logoColor=white
[kofi-url]: https://ko-fi.com/stevezau
