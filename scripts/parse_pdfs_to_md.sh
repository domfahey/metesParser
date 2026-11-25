#!/usr/bin/env bash
# Parse deed PDFs to markdown using LlamaParse via the `parse` CLI (semtools).
#
# Uses max quality settings (LlamaParse v2):
#   - tier: agentic_plus (the most accurate tier)
#   - version: latest
# The v1 options (parse_mode, model, high_res_ocr, adaptive_long_table,
# outlined_table_extraction, output_tables_as_HTML) are rejected by the v2 API.
#
# Usage:
#   ./scripts/parse_pdfs_to_md.sh                      # parse all PDFs missing .md files
#   ./scripts/parse_pdfs_to_md.sh deed1.pdf deed2.pdf  # parse specific PDFs
#   ./scripts/parse_pdfs_to_md.sh --force               # reparse ALL PDFs (overwrites existing .md)
#
# Output: .md files co-located next to each PDF in sample_deeds/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SAMPLE_DIR="$PROJECT_DIR/sample_deeds"
PARSE_CACHE="$HOME/.parse"

if ! command -v parse >/dev/null 2>&1; then
    echo "Error: 'parse' CLI (semtools) not found in PATH." >&2
    exit 1
fi

# Max quality config for LlamaParse
CONFIG_FILE=$(mktemp)
trap 'rm -f "$CONFIG_FILE"' EXIT

cat > "$CONFIG_FILE" <<'CONF'
{
  "parse": {
    "num_ongoing_requests": 10,
    "base_url": "https://api.cloud.llamaindex.ai",
    "parse_kwargs": {
      "tier": "agentic_plus",
      "version": "latest"
    },
    "check_interval": 5,
    "max_timeout": 3600,
    "max_retries": 10,
    "retry_delay_ms": 1000,
    "backoff_multiplier": 2.0
  }
}
CONF

# Inject API key from user's semtools config if not in environment
if [ -z "${LLAMA_CLOUD_API_KEY:-}" ]; then
    USER_CONFIG="$HOME/.semtools_config.json"
    if [ -f "$USER_CONFIG" ]; then
        API_KEY=$(python3 -c "import json, sys; print(json.load(open(sys.argv[1], encoding='utf-8'))['parse']['api_key'])" "$USER_CONFIG" 2>/dev/null || true)
        if [ -n "$API_KEY" ]; then
            # Patch the temp config with the API key
            _LLAMA_API_KEY="$API_KEY" python3 -c "
import json, os, sys
with open(sys.argv[1], encoding='utf-8') as f:
    cfg = json.load(f)
cfg['parse']['api_key'] = os.environ['_LLAMA_API_KEY']
with open(sys.argv[1], 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2)
" "$CONFIG_FILE"
        else
            echo "Error: No API key found. Set LLAMA_CLOUD_API_KEY or configure ~/.semtools_config.json" >&2
            exit 1
        fi
    else
        echo "Error: No API key found. Set LLAMA_CLOUD_API_KEY or configure ~/.semtools_config.json" >&2
        exit 1
    fi
fi

# Collect PDFs to process
FORCE=false
declare -a FILE_ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--force" ]; then
        FORCE=true
    else
        FILE_ARGS+=("$arg")
    fi
done

declare -a PDF_FILES=()
if [ ${#FILE_ARGS[@]} -eq 0 ]; then
    # No file args: find all PDFs in sample_deeds/ (skip existing .md unless --force)
    while IFS= read -r -d '' pdf; do
        md_file="${pdf%.pdf}.md"
        if [ "$FORCE" = true ] || [ ! -f "$md_file" ]; then
            PDF_FILES+=("$pdf")
        fi
    done < <(find "$SAMPLE_DIR" -maxdepth 1 -name "*.pdf" -print0 | sort -z)
else
    # Specific files provided
    for arg in "${FILE_ARGS[@]}"; do
        if [ -f "$arg" ]; then
            PDF_FILES+=("$(cd "$(dirname "$arg")" && pwd)/$(basename "$arg")")
        elif [ -f "$SAMPLE_DIR/$arg" ]; then
            PDF_FILES+=("$SAMPLE_DIR/$arg")
        else
            echo "Warning: File not found: $arg" >&2
        fi
    done
fi

if [ ${#PDF_FILES[@]} -eq 0 ]; then
    echo "No PDFs to process. All sample deeds already have .md files."
    echo "Use --force to reparse all PDFs."
    exit 0
fi

if [ "$FORCE" = true ]; then
    for pdf in "${PDF_FILES[@]}"; do
        rm -f "$PARSE_CACHE/$(basename "$pdf").md"
    done
fi

echo "Parsing ${#PDF_FILES[@]} PDF(s) with LlamaParse (agentic_plus tier, max settings)..."
echo "Settings: tier=agentic_plus | version=latest"
echo ""

# Run parse CLI
parse -v -c "$CONFIG_FILE" "${PDF_FILES[@]}"

# Copy results from ~/.parse/ cache to sample_deeds/
COPIED=0
FAILED=0
for pdf in "${PDF_FILES[@]}"; do
    basename="$(basename "$pdf")"
    cache_md="$PARSE_CACHE/${basename}.md"
    target_dir="$(dirname "$pdf")"
    target_md="$target_dir/${basename%.pdf}.md"

    if [ -f "$cache_md" ]; then
        cp "$cache_md" "$target_md"
        echo "  -> $(basename "$target_md")"
        COPIED=$((COPIED + 1))
    else
        echo "  !! Missing output for: $basename" >&2
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "Done: $COPIED parsed, $FAILED failed."
if [ "$FAILED" -gt 0 ]; then
    exit 1
fi
