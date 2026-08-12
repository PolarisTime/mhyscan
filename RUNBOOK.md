# mhyscan 拉流扫码测试环境部署

## 架构

```
[Windows 机器: OBS 推流]  --RTMP-->  [服务器: mediaMTX]  --RTMP/HTTP-->  [mhyscan 拉流扫码]
   rtmp://10.10.10.10:1935/live/<key>        :1935 接收 / :8888 HLS
```

## 服务器端 (已部署)

### mediaMTX (RTMP 服务器)
- 二进制: `~/bin/mediamtx`
- 配置: `~/.config/mediamtx/mediamtx.yml`
- 端口: RTMP `1935`, HLS(HTTP) `8888`
- 启动:
  ```bash
  nohup mediamtx ~/.config/mediamtx/mediamtx.yml > /tmp/mediamtx.log 2>&1 &
  ```
- 验证: `ss -tlnp | grep -E ":1935|:8888"`

### 完整 ffmpeg (推流测试用)
- imageio-ffmpeg 自带: `/home/sakura/mhy_analysis/venv/.../ffmpeg-linux-x86_64-v7.0.2`

## OBS 推流配置 (Windows)

1. OBS → 设置 → 直播 (Stream)
2. 服务 (Service): 自定义 (Custom)
3. 服务器 (Server): `rtmp://10.10.10.10:1935/live`
4. 推流码 (Stream Key): `test` (任意字符串)
5. 开始推流

> 注意: 服务器防火墙需放行 TCP 1935 入站。

## 拉流扫码测试 (服务器端)

### 方式1: 直接 PyAV 测试
```python
import av
container = av.open('rtmp://127.0.0.1:1935/live/test', options={'rtmp_live':'live'})
video = container.streams.video[0]
for frame in container.decode(video):
    img = frame.to_ndarray(format='bgr24')
    # 交给 zxingcpp / QRScanner 识别
```

### 方式2: mhyscan grab_once (v1.2.0+)
```python
from mhycli.api_client import MhyClient
from mhycli.stream_grab import LiveStreamGrabber
from mhycli.live_link import LivePlatform

grabber = LiveStreamGrabber(MhyClient(), 'fake', 'fake')
ok, ticket = grabber.grab_once(
    LivePlatform.BiliBili, 'test', timeout=30,
    stream_url='rtmp://127.0.0.1:1935/live/test')
```

### 方式3: CLI 验证 (v1.3.0+ 已实现 --stream)
```bash
mhyscan scan bili 0 --stream rtmp://10.10.10.10:1935/live/1 --timeout 180
# 从本地 RTMP 流拉取, 识别游戏内二维码 → panda 两阶段抢码
```

## 自测流程 (模拟推流)
```bash
FF=<ffmpeg路径>
# 生成二维码测试图
python3 -c "import qrcode; qr=qrcode.QRCode(border=2); qr.add_data('https://user.mihoyo.com/...?tk=test'); qr.make(); qr.make_image().save('/tmp/qr.png')"
# 推流 (二维码叠加在画面中央)
$FF -re -stream_loop -1 -f lavfi -i testsrc2=size=1280x720:rate=25 \
  -i /tmp/qr.png -filter_complex "[1:v]scale=400:400[qr];[0:v][qr]overlay=(W-w)/2:(H-h)/2" \
  -c:v libx264 -preset ultrafast -tune zerolatency -g 50 -f flv \
  rtmp://127.0.0.1:1935/live/test
```

## 已验证结论
- PyAV 拉 RTMP 流 ✅
- QRScanner 识别直播流二维码 ✅ (v1.2.0 修复 try_harder bug)
- 完整链路: 拉流 → 识别 → 提取 ticket → 抢码 ✅
- **Panda 两阶段抢码** (v1.3.0): 游戏内二维码 → panda_scan 换 passport_qr_url → passport scan/confirm ✅
  (实测 OBS 推流 + 游戏画面二维码, panda_scan/scanQRLogin/confirmQRLogin 全部 retcode=0)

## 版本
- mediaMTX: v1.20.0
- mhyscan: v1.3.0
