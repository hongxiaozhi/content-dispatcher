#!/usr/bin/env python3
"""Small, safe Python wrapper around the YiXiaoEr ``yxer`` CLI."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class ConfigurationError(ValueError):
    """The public TOML configuration is incomplete or inconsistent."""


@dataclass(frozen=True)
class PublicationConfig:
    executable: str
    platform: str
    content_type: str
    payload: Path
    channel: str
    client_id: str | None


def load_config(config_path: Path) -> PublicationConfig:
    """Load public configuration without opening the payload or credentials."""
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigurationError(f"找不到配置文件：{config_path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"TOML 格式错误：{error}") from error

    yxer = raw.get("yxer")
    publication = raw.get("publication")
    if not isinstance(yxer, dict) or not isinstance(publication, dict):
        raise ConfigurationError("配置必须包含 [yxer] 和 [publication] 两个区段。")

    def required(section: dict[str, object], name: str) -> str:
        value = section.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"缺少字符串配置：{name}")
        return value.strip()

    channel = required(publication, "channel")
    if channel not in {"cloud", "local"}:
        raise ConfigurationError("publication.channel 只能是 cloud 或 local。")
    client_id = publication.get("client_id")
    if client_id is not None and (not isinstance(client_id, str) or not client_id.strip()):
        raise ConfigurationError("client_id 如填写，必须是非空字符串。")
    if channel == "local" and not client_id:
        raise ConfigurationError("local 通道需要 publication.client_id。")
    if channel == "cloud" and client_id:
        raise ConfigurationError("cloud 通道不能设置 publication.client_id。")

    payload = Path(required(publication, "payload"))
    if not payload.is_absolute():
        payload = config_path.parent / payload
    return PublicationConfig(
        executable=required(yxer, "executable"),
        platform=required(publication, "platform"),
        content_type=required(publication, "content_type"),
        payload=payload.resolve(),
        channel=channel,
        client_id=client_id.strip() if isinstance(client_id, str) else None,
    )


def channel_args(config: PublicationConfig) -> list[str]:
    args = ["--publish-channel", config.channel]
    if config.client_id:
        args.extend(["--client-id", config.client_id])
    return args


def command_for(action: str, config: PublicationConfig) -> list[str]:
    base = [config.executable]
    if action == "doctor":
        return [*base, "doctor", "--json"]
    if action == "accounts":
        return [*base, "accounts", "list", config.platform, "--status", "1", "--json"]
    if action == "prepare":
        return [*base, "prepare", config.platform, config.content_type, "--json"]
    if action == "schema":
        return [*base, "schema", "get", config.platform, config.content_type, "--json"]
    if not config.payload.is_file():
        raise ConfigurationError(f"找不到 payload 文件：{config.payload}")
    if action == "validate":
        return [*base, "validate", config.platform, config.content_type, str(config.payload), *channel_args(config), "--json"]
    if action in {"dry-run", "publish"}:
        args = [*base, "publish", config.content_type, config.platform, str(config.payload), *channel_args(config)]
        if action == "dry-run":
            args.append("--dry-run")
        return [*args, "--json"]
    raise ConfigurationError(f"不支持的动作：{action}")


def run_yxer(command: Sequence[str], stage: str) -> bool:
    """Run argv without a shell and deliberately suppress raw CLI output."""
    print(f"[{stage}] 正在调用蚁小二…")
    try:
        result = subprocess.run(list(command), check=False, shell=False, capture_output=True,
                                text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        print("未找到 yxer。请先安装蚁小二 CLI，并检查配置中的 yxer.executable。", file=sys.stderr)
        return False
    if result.returncode == 0:
        print(f"[{stage}] 完成。")
        return True
    print(f"[{stage}] 失败（yxer 退出码 {result.returncode}）。为保护 payload 和登录信息，原始输出未显示；"
          "请由账号持有人在本地直接运行相同的 yxer 命令排查。", file=sys.stderr)
    return False


def require_publish_confirmation() -> bool:
    if not sys.stdin.isatty():
        print("拒绝非交互式正式发布。请在本地终端审核后运行。", file=sys.stderr)
        return False
    phrase = input("将创建真实平台内容。确认已审核 dry-run 后，输入 PUBLISH 继续： ").strip()
    if phrase != "PUBLISH":
        print("未收到确认词，未发布。")
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="通过 yxer 安全执行内容发布流程。")
    parser.add_argument("--config", type=Path, default=Path("config.toml"), help="TOML 配置文件路径")
    parser.add_argument("action", choices=("doctor", "accounts", "prepare", "schema", "validate", "dry-run", "release", "publish"))
    parser.add_argument("--confirm-publish", action="store_true", help="正式 publish 必填；仍会要求交互式输入 PUBLISH。")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config.resolve())
        if args.action == "release":
            if not run_yxer(command_for("validate", config), "validate"):
                return 1
            if not run_yxer(command_for("dry-run", config), "dry-run"):
                return 1
            if not require_publish_confirmation():
                return 2
            return 0 if run_yxer(command_for("publish", config), "publish") else 1
        if args.action == "publish":
            if not args.confirm_publish:
                raise ConfigurationError("正式发布必须明确传入 --confirm-publish。")
            if not require_publish_confirmation():
                return 2
        return 0 if run_yxer(command_for(args.action, config), args.action) else 1
    except ConfigurationError as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
