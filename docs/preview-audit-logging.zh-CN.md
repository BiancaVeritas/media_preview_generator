# 排查日志详细程度（PREVIEW_AUDIT_VERBOSE）

## 默认行为

「异常缩略图排查」在全库扫描时，**只有发现问题才输出 INFO 日志**：

```
Preview check: xxx-320-10.bif is wrong (只有 5 张缩略图...); rebuilding it in this run
Preview check: 1 of 1 preview file(s) for xxx.strm were wrong and are being rebuilt
Preview check: xxx.strm has no preview yet, so this run generates one
```

通过的文件不输出，避免一次全库扫描打印几千行把有用信息埋掉。

## 打开详细日志

```yaml
environment:
  - PREVIEW_AUDIT_VERBOSE=1
```

打开后，**每个文件的判定都会输出**：

```
Preview check: 封面1.strm is sound (1 file(s) checked); left as it is
Preview check: 封面2.strm is sound (1 file(s) checked); left as it is
Preview check: 封面3-320-10.bif is wrong (...); rebuilding it in this run
```

## 任务开始时还会打印一行说明

```
Preview check enabled: every existing .bif is measured against its video;
a wrong one is rebuilt in this run. Set PREVIEW_AUDIT_VERBOSE=1 to log each
file's verdict, including the ones that pass.
```

这样你一眼能确认：**排查模式确实启用了**，以及当前是否在详细模式。

## 注意

- 全库 3302 个文件打开这个开关会产生 3300+ 行日志，建议只在排查个别媒体库时使用
- 关掉只需删除该环境变量或设为 `0`
- 接受的值：`1` / `true` / `yes` / `on`（不区分大小写）
