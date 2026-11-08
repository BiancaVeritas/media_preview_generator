# 网络源重试间隔（NETWORK_RETRY_DELAYS）

## 这个变量解决什么问题

`.strm` 指向的云盘链接（比如 P115StrmHelper）在**限流**时会返回错误内容或只给文件开头。工具原来的重试间隔是
**0 秒、2 秒、8 秒**，三次加起来只等了 10 秒。

问题是：**云盘限流通常持续几分钟**。0/2/8 秒的重试全部落在同一个限流窗口里，一次都不可能成功；而第一次
就立刻重试（0 秒）等于连续请求，恰恰最容易触发风控。结果是重试不但没用，还多发了 3 次请求、加重了问题。

典型日志：

```
WARNING - The stream for xxx.strm stopped answering while it was being read (1 of 3). Reopening it now ...
WARNING - The stream for xxx.strm stopped answering while it was being read (2 of 3). Reopening it in 2s ...
WARNING - The stream for xxx.strm stopped answering while it was being read (3 of 3). Reopening it in 8s ...
ERROR   - FFmpeg produced no preview frames for xxx.strm: FFmpeg exit 183 (bad_input)
          — moov atom not found / Invalid data found when processing input
```

12 秒内三次尝试全部失败，然后放弃。

## 现在的默认值

```
NETWORK_RETRY_DELAYS=15,60,180
```

| 尝试 | 等待 | 累计 |
|---|---|---|
| 第 1 次 | 15 秒 | 15s |
| 第 2 次 | 60 秒 | 75s |
| 第 3 次 | 180 秒 | 255s（约 4 分钟）|

这样能跨过一次典型的限流窗口，也显得像一个有耐心的客户端而不是在刷接口。

**代价**：一个最终失败的文件会占用一个 worker 约 4 分钟（原来是 12 秒）。这个交换是刻意的——反正不重试也会失败，
而现在能把「限流期间必然失败」变成「通常能成功」。

## 怎么配置

在 `docker-compose.yml` 里加：

```yaml
environment:
  - NETWORK_RETRY_DELAYS=15,60,180
```

想恢复原来的激进节奏：

```yaml
  - NETWORK_RETRY_DELAYS=0,2,8
```

想更保守（适合频繁被限流的网盘）：

```yaml
  - NETWORK_RETRY_DELAYS=30,120,300
```

## 注意

- 写成逗号分隔的**秒数**，允许有空格（`5, 10` 也认）
- 值为空、含非数字、或含负数时，**自动回落到默认值**并记一条 WARNING，不会让任务失败
- 只影响**网络源**（`.strm` 指向的 http/rtsp/rtmp）；本地文件不重试
- 这个等待发生在生成缩略图的流程里，所以「检查/排查」阶段不等待

## 相关

- 排查功能（异常缩略图排查）读时长时也有自己的重试，同样避免在限流时反复打链接
- 判断一个文件是不是真的坏了：先在媒体服务器里播放试试；能播就是源正常，属于限流或索引问题
