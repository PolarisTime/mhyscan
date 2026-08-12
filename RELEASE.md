# mhyscan 1.0.0 — 发布说明

米哈游直播流抢码工具 (PySide6 图形界面 + CLI)

## 功能
- 米游社 App 扫码登录 (新一代 passport 接口)
- B站扫码登录 (TV端接口, 保存拉流凭证)
- 多账号管理 (Cookie/SToken 导入, userinfo.json)
- 直播间抢码: B站/抖音直播流 → 二维码识别 → 自动 scanQRLogin + confirmQRLogin
- 游戏角色信息显示 (7 天缓存)
- 低延迟拉流 + 每 3 秒进度日志 (上海时区时间戳)

## 打包

### 目标平台打包 (在对应平台执行, PyInstaller 不支持交叉编译)

#### Windows
```powershell
pip install -r requirements.txt pyinstaller
pyinstaller mhyscan_ui.spec --noconfirm
# 产物: dist/mhyscan_ui/mhyscan_ui.exe
```

#### Linux
```bash
pip install -r requirements.txt pyinstaller
pyinstaller mhyscan_ui.spec --noconfirm
# 产物: dist/mhyscan_ui/mhyscan_ui
```

### 打包说明
- `--onedir` 模式: PyAV/opencv/PySide6 体积大 (~540MB), onedir 启动更快
- `--noconsole`: Windows 无黑窗
- 首次运行自动生成 `Config/` 目录
- 分发需带整个 `dist/mhyscan_ui/` 目录

## CLI 命令 (开发模式)
```
mhyscan login            # App 扫码登录
mhyscan bili-login       # B站扫码登录 (拉流凭证)
mhyscan add --cookie ".." # 注册用户
mhyscan accounts         # 列出账号
mhyscan scan bili <RID>  # 监视B站直播间抢码
mhyscan scan douyin <RID>
```

## 配置
- 账号: `Config/userinfo.json`
- B站凭证: `Config/bili_cookie.json` (或环境变量 `BILIBILI_COOKIE`)
- 缓存: `Config/cache.json` (角色 7 天)

## 注意事项
- 本工具仅用于个人学习研究
- 匿名 B站拉流为 720P; 配置 B站登录 cookie 后为 1080P 原画 + 抗限流
