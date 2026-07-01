#!/usr/bin/env python3
import os
from pathlib import Path


MARKER_START = "/* english-agent-openclaw-bridge:start */"
MARKER_END = "/* english-agent-openclaw-bridge:end */"

BRIDGE_BLOCK = f"""
    {MARKER_START}
    const englishAgentBridgeUrl = process.env.ENGLISH_AGENT_OPENCLAW_CALLBACK_URL;
    const englishAgentText = (finalized.Body ?? "").trim();
    if (englishAgentBridgeUrl && englishAgentText) {{
        try {{
            const bridgeResponse = await fetch(englishAgentBridgeUrl, {{
                method: "POST",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify({{
                    account_id: deps.accountId,
                    sender: finalized.From,
                    text: englishAgentText,
                    name: "微信用户",
                    message_id: finalized.MessageSid ?? full.message_id ?? undefined,
                }}),
            }});
            if (bridgeResponse.ok) {{
                logger.info(`english-agent bridge delivered sender=${{finalized.From}} message=${{finalized.MessageSid}}`);
                return;
            }}
            logger.error(`english-agent bridge failed status=${{bridgeResponse.status}} body=${{(await bridgeResponse.text()).slice(0, 300)}}`);
        }} catch (err) {{
            logger.error(`english-agent bridge error: ${{String(err)}}`);
        }}
    }}
    {MARKER_END}
"""


def main():
    plugin_root = Path(
        os.environ.get(
            "OPENCLAW_WEIXIN_PLUGIN_ROOT",
            str(Path.home() / ".openclaw/npm/projects"),
        )
    )
    candidates = sorted(
        plugin_root.glob(
            "*/node_modules/@tencent-weixin/openclaw-weixin/dist/src/messaging/process-message.js"
        )
    )
    if not candidates:
        raise SystemExit("OpenClaw Weixin process-message.js not found")
    target = candidates[-1]
    text = target.read_text(encoding="utf-8")
    if MARKER_START in text:
        marker_start = text.index(MARKER_START)
        start = text.rfind("\n", 0, marker_start) + 1
        marker_end = text.index(MARKER_END, marker_start) + len(MARKER_END)
        end = text.find("\n", marker_end)
        end = len(text) if end == -1 else end + 1
        target.write_text(text[:start] + BRIDGE_BLOCK.strip("\n") + text[end:], encoding="utf-8")
        print(f"Updated English Agent bridge in {target}")
        return

    needle = '    logger.debug(`inbound context: ${redactBody(JSON.stringify(finalized))}`);\n'
    if needle not in text:
        raise SystemExit("Patch anchor not found in OpenClaw Weixin plugin")
    target.write_text(text.replace(needle, needle + BRIDGE_BLOCK, 1), encoding="utf-8")
    print(f"Patched English Agent bridge into {target}")


if __name__ == "__main__":
    main()
