#!/usr/bin/env python3
"""GitOps sync: regenerate litellm.config-map.yaml from llama-swap + static models.

Environment:
  BACKEND_API_KEY    - llama-swap API key (required)
  LLAMA_SWAP_URL     - llama-swap base URL (default http://10.132.247.31:18080/v1)
  REPO_DIR           - path to homelab git repo (default /workspace)
"""

import json, os, subprocess, sys, urllib.request
from pathlib import Path

BACKEND_KEY_ENV = "BACKEND_API_KEY"
LLAMA_SWAP_URL = os.environ.get("LLAMA_SWAP_URL", "http://10.132.247.31:18080/v1")
# (running in-cluster, applying directly)
# target: cluster ConfigMap litellm-config

STATIC_MODELS = [
    {
        "model_name": "gemma-4-E4B-it-Q4_K_M",
        "model": "openai/gemma-4-E4B-it-Q4_K_M",
        "api_base": "http://10.132.247.31:18080/v1",
        "api_key_env": "LLAMACPP_API_KEY",
    },
    {
        "model_name": "gpt-5.5",
        "model": "openai/gpt-5.5",
        "api_base": "http://10.132.247.31:18080/v1",
        "api_key_env": "LLAMACPP_API_KEY",
    },
    {
        "model_name": "gemma-4-12B-it-qat-GGUF",
        "model": "openai/gemma-4-12B-it-qat-GGUF",
        "api_base": "http://10.132.247.31:18080/v1",
        "api_key_env": "LLAMACPP_API_KEY",
    },
]

def build_model_entry(model_name, model, api_base, api_key_env):
    return (
        f"    - model_name: {model_name}\n"
        f"      litellm_params:\n"
        f"        model: {model}\n"
        f"        api_base: {api_base}\n"
        f"        api_key: os.environ/{api_key_env}"
    )

def main():
    backend_key = os.environ.get(BACKEND_KEY_ENV)
    if not backend_key:
        print(f"ERROR: {BACKEND_KEY_ENV} not set", file=sys.stderr)
        sys.exit(1)

    # Fetch llama-swap models
    req = urllib.request.Request(
        f"{LLAMA_SWAP_URL}/models",
        headers={"Authorization": f"Bearer {backend_key}"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode())
        swap_models = sorted(
            {m.get("id") for m in data.get("data", []) if m.get("id")}
        )

    # Build entries
    entries = []
    for m in STATIC_MODELS:
        entries.append(build_model_entry(**m))
    for mid in swap_models:
        entries.append(
            build_model_entry(mid, f"openai/{mid}", LLAMA_SWAP_URL, "LLAMA_SWAP_B70_API_KEY")
        )

    config = (
        "litellm_settings:\n"
        "  request_timeout: 600\n"
        "  json_logs: true\n"
        "  drop_params: true\n"
        "\n"
        "router_settings:\n"
        "  routing_strategy: simple-shuffle\n"
        "\n"
        "general_settings:\n"
        "  master_key: os.environ/LITELLM_MASTER_KEY\n"
        "  disable_spend_logs: true\n"
        "  disable_spend_updates: true\n"
        "  disable_error_logs: true\n"
        "  disable_reset_budget: true\n"
        "  disable_adding_master_key_hash_to_db: true\n"
        "\n"
        "  user_header_mappings:\n"
        "    - header_name: X-OpenWebUI-User-Id\n"
        "      litellm_user_role: internal_user\n"
        "    - header_name: X-OpenWebUI-User-Email\n"
        "      litellm_user_role: customer\n"
        "\n"
        "model_list:\n"
        + "\n".join(entries)
    )

    # Build ConfigMap YAML
    cm_lines = [
        "apiVersion: v1",
        "kind: ConfigMap",
        "metadata:",
        "  name: litellm-config",
        "  namespace: litellm-system",
        "data:",
        "  config.yaml: |",
    ]
    for line in config.splitlines():
        cm_lines.append("    " + line)
    cm_yaml = "\n".join(cm_lines) + "\n"

    # Apply directly to cluster
    print(f"generated ConfigMap ({len(swap_models)} swap + {len(STATIC_MODELS)} static = {len(entries)} total)")

    # Apply ConfigMap to cluster
    tmp = Path("/tmp/litellm-cm.yaml")
    tmp.write_text(cm_yaml, encoding="utf-8")
    subprocess.run(
        ["kubectl", "apply", "-f", str(tmp)],
        check=True,
    )
    # Restart deployment to pick up new config
    subprocess.run(
        ["kubectl", "rollout", "restart", "deploy/litellm-deployment", "-n", "litellm-system"],
        check=True,
    )
    subprocess.run(
        ["kubectl", "rollout", "status", "deploy/litellm-deployment", "-n", "litellm-system", "--timeout=120s"],
        check=True,
    )
    print("applied and restarted")


if __name__ == "__main__":
    main()
