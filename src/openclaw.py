import json
import os
import pty
import select
import subprocess
import time


DEFAULT_CLI_PATH = "/Users/zhouti/.local/opt/node-v24.17.0-darwin-arm64/bin/openclaw"


class OpenClawError(Exception):
    pass


class OpenClawClient:
    def __init__(
        self,
        cli_path=None,
        channel=None,
        account_id=None,
        enabled=None,
        runner=None,
    ):
        self.cli_path = cli_path or os.getenv("OPENCLAW_CLI_PATH", DEFAULT_CLI_PATH)
        self.channel = channel if channel is not None else os.getenv("OPENCLAW_CHANNEL", "openclaw-weixin")
        self.account_id = account_id if account_id is not None else os.getenv("OPENCLAW_ACCOUNT_ID", "")
        raw_enabled = enabled if enabled is not None else os.getenv("OPENCLAW_ENABLED", "")
        self.enabled = str(raw_enabled).lower() in ("1", "true", "yes", "on")
        self.runner = runner or subprocess.run

    @property
    def configured(self):
        return bool(self.enabled and self.cli_path and self.account_id)

    def _run(self, args, timeout=30):
        command = [self.cli_path, *args]
        try:
            result = self.runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise OpenClawError("OpenClaw 命令不存在，请检查 CLI 路径") from exc
        except subprocess.TimeoutExpired as exc:
            raise OpenClawError("OpenClaw 命令执行超时") from exc

        if result.returncode != 0:
            message = (result.stderr or result.stdout or "未知错误").strip()
            raise OpenClawError(f"OpenClaw 执行失败：{message[:500]}")
        return result.stdout.strip()

    def status(self):
        return self._run(["channels", "status", "--probe"], timeout=60)

    def login_command(self, account_id=""):
        args = [self.cli_path, "channels", "login", "--channel", self.channel]
        if account_id:
            args.extend(["--account", account_id])
        return args

    def send_text(self, target, text):
        if not self.configured:
            raise OpenClawError("OpenClaw 微信入口尚未启用或缺少账号 ID")
        args = ["message", "send", "--account", self.account_id, "--target", str(target), "--message", str(text)]
        if self.channel:
            args.extend(["--channel", self.channel])
        output = self._run(args)
        try:
            return json.loads(output) if output.startswith("{") else {"ok": True, "output": output}
        except json.JSONDecodeError:
            return {"ok": True, "output": output}


class OpenClawLoginSession:
    def __init__(self, command):
        self.command = command
        self.started_at = time.time()
        self.output = ""
        self.error = ""
        self.master_fd = None
        self.process = None
        self._start()

    def _start(self):
        master_fd, slave_fd = pty.openpty()
        try:
            self.process = subprocess.Popen(
                self.command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                close_fds=True,
                text=False,
            )
            self.master_fd = master_fd
        except Exception:
            os.close(master_fd)
            raise
        finally:
            os.close(slave_fd)

    @property
    def running(self):
        return self.process is not None and self.process.poll() is None

    @property
    def returncode(self):
        return None if self.process is None else self.process.poll()

    def read_available(self):
        if self.master_fd is None:
            return self.output
        chunks = []
        while True:
            ready, _, _ = select.select([self.master_fd], [], [], 0)
            if not ready:
                break
            try:
                data = os.read(self.master_fd, 4096)
            except OSError:
                break
            if not data:
                break
            chunks.append(data.decode("utf-8", errors="replace"))
        if chunks:
            self.output += "".join(chunks)
            if len(self.output) > 20000:
                self.output = self.output[-20000:]
        return self.output

    def stop(self):
        if self.running:
            self.process.terminate()
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None
