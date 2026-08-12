#!/usr/bin/env python3
"""mhyscan — 米哈游直播流抢码 CLI (基于 FufuLauncher 接口封装)

用法:
  mhyscan login                     # App 扫码登录, 添加账号 (保存 stoken/mid)
  mhyscan add --cookie "..."        # 粘贴含 SToken 的 Cookie 注册账号
  mhyscan add --stoken S --uid U --mid M   # 直接指定 SToken/uid/mid 注册账号
  mhyscan accounts                  # 列出账号
  mhyscan scan bili <RID> [--acc 账号名|--uid UID]   # 监视 B站直播间抢码
  mhyscan scan douyin <RID> [...]   # 监视抖音直播间抢码
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .api_client import MhyClient
from .config import AccountStore, CacheStore
from .cookie_import import CookieParseError, extract_account_from_cookie
from .game_record import (
    GameRecordClient,
    format_roles,
)
from .live_link import LivePlatform
from .qr_login import app_qr_login
from .stream_grab import LiveStreamGrabber

# 上海时区
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def log(msg: str = "", newline: bool = True):
    """带上海时区时间戳的日志输出

    格式: [2026年8月12日 10:27:56] 消息
    """
    now = datetime.now(_SHANGHAI_TZ)
    ts = f"{now.year}年{now.month}月{now.day}日 {now:%H:%M:%S}"
    line = f"[{ts}] {msg}"
    print(line, end="\n" if newline else "")


def build_cookie(client: MhyClient, acc: dict) -> str:
    """从账号的 stoken/mid/uid 构造完整 cookie (ltoken+cookie_token+ltuid+account_id)"""
    stoken = acc.get("access_key", "")
    uid = acc.get("uid", "")
    mid = acc.get("mid", "")
    ct = client.get_cookie_account_info_by_stoken(stoken, mid, uid)
    lt = client.get_ltoken_by_stoken(stoken, mid, uid)
    return f"ltoken={lt}; ltuid={uid}; cookie_token={ct}; account_id={uid}"


def print_game_record(acc: dict, log_cb=log, force_refresh: bool = False):
    """获取并输出账号的游戏角色信息 (带 7 天缓存)

    对应: getUserGameRolesByCookie → 角色列表
    注: 深渊/剧诗查询已移除 (受 device_fp 风控影响不稳定)
    """
    try:
        client = MhyClient()
        cookie = build_cookie(client, acc)
        cache = CacheStore()
        gr = GameRecordClient(cookie, cache=cache, log_cb=log_cb)

        log_cb(f"[游戏记录] 账号 uid={acc.get('uid')} ({acc.get('name')})")

        # 角色列表 (7 天缓存)
        roles = gr.get_roles(force_refresh=force_refresh)
        log_cb(f"  [角色] {format_roles(roles)}")
        if not roles:
            log_cb("  ⚠ 未获取到角色")
    except Exception as e:
        log_cb(f"[游戏记录] 获取异常: {e}")


def cmd_login(args):
    """App 扫码登录并保存账号"""
    store = AccountStore(args.config)
    client = MhyClient()

    def on_qr(url, ticket):
        """创建成功后在轮询前展示二维码"""
        from .qrcode_display import print_qr_terminal, save_qr_png

        log("\n" + "=" * 46)
        print_qr_terminal(url)
        log("=" * 46)
        # 同时保存 PNG, 方便手机截图或放大
        png_path = "login_qrcode.png"
        try:
            save_qr_png(url, png_path)
            log(f"二维码图片已保存: {png_path}")
        except Exception:
            pass
        log("(若终端二维码变形, 请打开图片文件扫码)")
        log()

    def on_status(status):
        msg = {"Created": "等待扫码...", "Scanned": "已扫码, 请在手机确认...",
               "Confirmed": "登录成功!", "Expired": "二维码过期"}.get(status, status)
        log(f"  [{status}] {msg}")

    log("正在创建登录二维码...")
    session = app_qr_login(client, on_status=on_status, on_qr=on_qr)
    if not session.stoken:
        log("登录失败或超时")
        sys.exit(1)

    # 获取昵称
    name = ""
    try:
        from .api_client import EP_GET_COOKIE_BY_STOKEN  # noqa
        # 简单尝试: 用 get_cookie 确认 stoken 有效
        cookie = client.get_cookie_account_info_by_stoken(session.stoken, session.mid, session.uid)
        log(f"cookie_token: {cookie[:12]}..." if cookie else "(cookie_token 获取失败, 但 stoken 有效)")
    except Exception as e:
        log(f"提示: {e}")

    ok = store.add_account(name or f"账号{session.uid}", session.stoken, session.uid, session.mid, "官服")
    if ok:
        log(f"已保存账号 uid={session.uid} (stoken {session.stoken[:8]}...)")
    else:
        log(f"账号 uid={session.uid} 已存在")


def cmd_bili_login(args):
    """B站 TV 端扫码登录, 保存凭证到 Config/bili_cookie.json

    复用 biliup credential.rs 逻辑:
      auth_code → 二维码 → 手机B站APP扫码 → poll → cookie_info
    """
    from . import bili_login
    from .qrcode_display import print_qr_terminal, save_qr_png

    log("正在获取 B站登录二维码 (TV端接口)...")
    session = requests.Session()
    qrcode_url, auth_code = bili_login.get_qrcode(session)

    # 展示二维码
    print("\n" + "=" * 46)
    print_qr_terminal(qrcode_url, label="请用B站APP扫描上方二维码登录")
    print("=" * 46)
    try:
        save_qr_png(qrcode_url, "bili_login_qrcode.png")
        log("二维码图片已保存: bili_login_qrcode.png")
    except Exception:
        pass
    print()

    def on_status(code):
        msg = {-4: "等待扫码...", -5: "已扫码, 请在手机上确认...",
               0: "登录成功!", 86039: "等待确认..."}.get(code, f"状态码 {code}")
        if isinstance(code, int) and code == -5:
            log(f"  [已扫码] 请在手机上确认登录")
        elif isinstance(code, int) and code == 0:
            log("  [成功] 登录成功!")
        elif isinstance(code, int) and code == 86039:
            pass  # 静默轮询
        elif isinstance(code, str):
            log(f"  [网络] {msg}")

    try:
        resp = bili_login.poll_login(session, auth_code, on_status=on_status, timeout=args.timeout)
    except TimeoutError:
        log("✘ 扫码登录超时")
        sys.exit(1)
    except Exception as e:
        log(f"✘ 扫码登录失败: {e}")
        sys.exit(1)

    cookies = bili_login.extract_cookies(resp)
    if not cookies:
        log("✘ 登录成功但未获取到 cookie")
        sys.exit(1)

    bili_login.save_cookies_to_file(cookies)
    log(f"✔ B站登录成功, 已保存 {len(cookies)} 个 cookie: {bili_login.cookie_summary(cookies)}")
    log(f"  文件: {bili_login.COOKIE_FILE}")
    log("  后续拉流将使用该凭证 (1080P 原画 + 抗限流)")


def cmd_add(args):
    """注册用户: 粘贴 Cookie 或直接指定 SToken"""
    store = AccountStore(args.config)
    client = MhyClient()
    if args.cookie:
        try:
            acc = extract_account_from_cookie(args.cookie)
        except CookieParseError as e:
            log(f"✘ Cookie 解析失败: {e}")
            sys.exit(1)
        stoken, uid, mid = acc["stoken"], acc["uid"], acc["mid"]
    elif args.stoken and args.uid and args.mid:
        stoken, uid, mid = args.stoken, args.uid, args.mid
    else:
        log("用法: mhyscan add --cookie \"stoken=..;mid=..;stuid=..\" | mhyscan add --stoken S --uid U --mid M")
        sys.exit(1)

    # 校验 SToken 有效性并获取昵称
    name = f"账号{uid}"
    cookie_token = ""
    try:
        cookie_token = client.get_cookie_account_info_by_stoken(stoken, mid, uid)
    except Exception:
        pass
    if cookie_token:
        log(f"✔ SToken 有效 (cookie_token {cookie_token[:10]}...)")
    else:
        log("⚠ 未能换取 cookie_token — SToken 可能无效或已过期, 仍将尝试保存")

    ok = store.add_account(name, stoken, uid, mid, "官服")
    if ok:
        log(f"已注册账号 uid={uid} (stoken {stoken[:8]}...)")
    else:
        log(f"账号 uid={uid} 已存在")


def cmd_accounts(args):
    store = AccountStore(args.config)
    accs = store.list_accounts()
    if not accs:
        log("暂无账号。运行 `mhyscan login` 添加。")
        return
    for i, a in enumerate(accs):
        log(f"  [{i}] {a.get('name') or '?'}  uid={a.get('uid')}  type={a.get('type')}  stoken={str(a.get('access_key'))[:8]}...")
    # 显示游戏记录 (角色/深渊/剧诗)
    if args.roles and accs:
        log()
        for a in accs:
            print_game_record(a, force_refresh=args.refresh)


def cmd_grab(args):
    """监视直播间抢码"""
    store = AccountStore(args.config)
    acc = None
    if args.uid:
        acc = store.get_account(args.uid)
    elif args.acc:
        for a in store.list_accounts():
            if a.get("name") == args.acc:
                acc = a
                break
    if acc is None:
        acc = store.get_last_account()
    if acc is None:
        log("没有可用账号。先运行 `mhyscan login` 添加账号。")
        sys.exit(1)

    stoken = acc.get("access_key", "")
    mid = acc.get("mid", "")
    if not stoken or not mid:
        log(f"账号 {acc.get('uid')} 缺少 stoken/mid")
        sys.exit(1)

    platform = LivePlatform.BiliBili if args.platform == "bili" else LivePlatform.Douyin
    client = MhyClient()
    grabber = LiveStreamGrabber(client, stoken, mid, frame_skip=args.frame_skip)

    log(f"使用账号 {acc.get('name')} (uid={acc.get('uid')}) 监视直播间 RID={args.rid}")
    log(f"平台: {'B站' if platform == LivePlatform.BiliBili else '抖音'}  超时: {args.timeout}s")

    # 在账号行下方默认显示游戏角色信息, --refresh 强制刷新缓存
    log()
    print_game_record(acc, force_refresh=args.refresh)
    log()

    log("开始监视直播流, 识别到登录二维码将自动抢码...")
    log("按 Ctrl+C 停止")
    log()

    def progress_cb(elapsed, bytes_read, rss_kb, frame_count):
        mb = bytes_read / 1024 / 1024
        log(f"  [已等待 {elapsed:6.1f}s] 流量 {mb:7.2f} MB | 已处理 {frame_count:5d} 帧 | 内存 {rss_kb/1024:.1f} MB")

    try:
        ok, ticket = grabber.grab_once(platform, args.rid, timeout=args.timeout,
                                       progress_cb=progress_cb, log_cb=log)
    except KeyboardInterrupt:
        log("\n已停止")
        sys.exit(0)
    if ok:
        log(f"\n✔ 抢码成功! ticket={ticket}")
        log("登录完成, 自动退出")
    else:
        log(f"\n✘ 抢码失败: {ticket}")


HELP_DOC = """\
mhyscan — 米哈游直播流抢码 CLI（基于 FufuLauncher 接口封装）
================================================================

一、快速开始
----------------------------------------------------------------
  1. 注册账号（二选一）：
       mhyscan login                          # 手机 App 扫码登录
       mhyscan add --cookie "stuid=..;stoken=..;mid=.."   # 粘贴 Cookie
       mhyscan add --stoken <S> --uid <U> --mid <M>       # 指定凭证

  2. 列出账号：
       mhyscan accounts

  3. 监视直播间抢码：
       mhyscan scan bili <RID> [--uid <uid>]
       mhyscan scan douyin <RID> [--uid <uid>]


二、命令详解
----------------------------------------------------------------

  login —— App 扫码登录
    生成登录二维码并在终端显示（同时保存 login_qrcode.png），
    用手机米游社 APP 扫码确认后，自动保存账号凭证。
      用法:  mhyscan login

  bili-login —— B站扫码登录 (保存拉流凭证)
    复用 biliup TV 端接口, 终端显示二维码, 用手机 B站 APP 扫码。
    登录成功后自动保存 cookie 到 Config/bili_cookie.json,
    后续 B站拉流将使用该凭证 (1080P 原画 + 抗限流)。
      用法:  mhyscan bili-login [--timeout <秒>]

  add —— 注册用户（粘贴 Cookie / 指定凭证）
    方式一（粘贴完整 Cookie，自动解析 uid/mid/stoken）：
      用法:  mhyscan add --cookie "stuid=100000001; stoken=xxx; mid=yyy"
    方式二（直接指定三个字段）：
      用法:  mhyscan add --stoken <SToken> --uid <uid> --mid <mid>
    说明: 会调用 getCookieAccountInfoBySToken 校验凭证有效性，
          若无效则警告但仍保存（避免误删）。

  accounts —— 列出账号
      用法:  mhyscan accounts
      用法:  mhyscan accounts --roles (显示游戏角色信息)
    输出账号索引、昵称、uid、类型、stoken 前8位。

  scan —— 监视直播间抢码
    从直播间直播流中识别登录二维码，识别到后用指定账号
    自动执行 scanQRLogin + confirmQRLogin 完成抢码。
      用法:  mhyscan scan <bili|douyin> <RID> [选项]
    参数:
      <RID>          直播间房间号（纯数字，从直播间链接中获取）
      --acc <名字>   指定抢码账号（按昵称匹配）
      --uid <uid>    指定抢码账号（按 uid 匹配）
      --timeout <秒> 监视超时时间，默认 180
      --frame-skip N 抽帧间隔，默认 2（每 N+1 帧识别一次）
      --refresh      强制刷新角色信息缓存
    运行时:
      启动时默认在账号行下方输出游戏角色信息
      每 3 秒输出进度日志: 已等待时间 / 已使用流量 / 已处理帧数 / 内存 RSS
      抢码登录每一步输出日志: 获取流→打开流→识别→scanQRLogin→confirmQRLogin
      低延迟拉流 (fflags=nobuffer / probesize / low_delay), 缩短直播延迟
      抢码成功后自动退出（无需手动停止）
    B站 cookie (可选, 复用 biliup 逻辑):
      匿名拉流为 720P; 配置登录 cookie 后可拿 1080P 原画 + 抗限流
      方式1: 环境变量  export BILIBILI_COOKIE="SESSDATA=..;buvid3=.."
      方式2: 文件 Config/bili_cookie.json
             {"cookie_info":{"cookies":[{"name":"SESSDATA","value":".."}]}}
    说明:
      B站 RID 示例: https://live.bilibili.com/123456  → RID=123456
      抖音 RID 示例: https://live.douyin.com/123456   → RID=123456
      按 Ctrl+C 可随时停止。

  通用参数:
      --config <路径>  账号配置文件路径（默认 ./Config/userinfo.json）


三、抢码原理
----------------------------------------------------------------
  直播间画面中会出现米哈游登录二维码，其 URL 形如：
      https://user.mihoyo.com/login-platform/mobile.html?tk=<uuid>...
  抢码流程:
      直播流抽帧 → ZXing 识别二维码 → 提取 tk 参数 →
      用已登录账号身份 scanQRLogin + confirmQRLogin → 抢码成功
  说明: 抢码需要账号库中已有至少一个账号（含有效 stoken/mid）。


四、常见问题
----------------------------------------------------------------
  Q: scan 提示"没有可用账号"？
  A: 先运行 mhyscan login 或 mhyscan add 注册账号。

  Q: login 终端二维码变形？
  A: 打开生成的 login_qrcode.png 扫码，或用手机扫终端二维码。

  Q: 抢码失败/未识别到二维码？
  A: 确认 RID 正确、直播间正在直播、画面中确实有登录二维码。
     可调小 --frame-skip 提高识别频率，或调大 --timeout。

  Q: 账号凭证存储在哪？
  A: 默认 ./Config/userinfo.json（可用 --config 指定路径）。
"""


def cmd_help(args):
    """显示详细帮助文档"""
    if args.cmd:
        target = args.cmd
        for line in HELP_DOC.splitlines():
            if line.strip().startswith(f"{target} ——") or line.strip() == target:
                # 打印该命令所在小节
                section = _extract_section(HELP_DOC, target)
                if section:
                    print(section)
                    return
        print(f"未知命令: {target}")
        print("可用命令: login / bili-login / add / accounts / scan / help")
        return
    print(HELP_DOC)


def _extract_section(doc: str, cmd: str) -> str | None:
    """从帮助文档中提取某个命令的说明小节

    命令小节以 "  <cmd> ——" 开头, 到下一个 "  <其他> ——" 前结束
    """
    import re

    lines = doc.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{cmd} ——"):
            start = i
            break
    if start is None:
        return None

    out = [lines[start]]
    for line in lines[start + 1:]:
        # 下一个命令小节: 行形如 "  <word> —— ..." (两空格开头 + 非空单词 + 空格 + ——)
        if re.match(r"^  \S+ ——", line):
            break
        # 章节标题 (如 "三、抢码原理") 也停止
        if re.match(r"^[一二三四五六七八九十]、", line.strip()):
            break
        out.append(line)
    return "\n".join(out)


def main():
    # 无缓冲输出: 进度日志需要实时可见 (管道/后台运行时 print 默认缓冲)
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        prog="mhyscan",
        description="米哈游直播流抢码 CLI（基于 FufuLauncher 接口封装）\n"
                    "运行 `mhyscan help` 查看详细使用说明",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", default=None, help="账号配置文件路径 (默认 Config/userinfo.json)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="App 扫码登录添加账号")
    p_login.set_defaults(fn=cmd_login)

    p_bili = sub.add_parser("bili-login", help="B站扫码登录, 保存拉流凭证到 Config/bili_cookie.json")
    p_bili.add_argument("--timeout", type=float, default=180.0, help="扫码超时秒数 (默认180)")
    p_bili.set_defaults(fn=cmd_bili_login)

    p_add = sub.add_parser("add", help="注册用户 (粘贴 Cookie 或指定 SToken)")
    p_add.add_argument("--cookie", help="含 SToken 的完整 Cookie 串")
    p_add.add_argument("--stoken", help="SToken")
    p_add.add_argument("--uid", help="账号 uid (account_id/stuid)")
    p_add.add_argument("--mid", help="账号 mid")
    p_add.set_defaults(fn=cmd_add)

    p_acc = sub.add_parser("accounts", help="列出账号 (加 --roles 显示游戏角色)")
    p_acc.add_argument("--roles", action="store_true", help="显示游戏角色信息")
    p_acc.add_argument("--refresh", action="store_true", help="强制刷新缓存")
    p_acc.set_defaults(fn=cmd_accounts)

    p_grab = sub.add_parser("scan", help="监视直播间抢码")
    p_grab.add_argument("platform", choices=["bili", "douyin"], help="直播平台")
    p_grab.add_argument("rid", help="直播间 RID (纯数字)")
    p_grab.add_argument("--acc", help="账号名")
    p_grab.add_argument("--uid", help="账号 uid")
    p_grab.add_argument("--timeout", type=float, default=180.0, help="监视超时秒数 (默认180)")
    p_grab.add_argument("--frame-skip", type=int, default=2, help="抽帧间隔 (默认2)")
    p_grab.add_argument("--roles", action="store_true", help="[已默认] 已默认显示角色/深渊/剧诗")
    p_grab.add_argument("--refresh", action="store_true", help="强制刷新角色信息缓存")
    p_grab.set_defaults(fn=cmd_grab)

    p_help = sub.add_parser("help", help="显示详细帮助文档")
    p_help.add_argument("cmd", nargs="?", default=None, help="查看指定命令的帮助")
    p_help.set_defaults(fn=cmd_help)

    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
