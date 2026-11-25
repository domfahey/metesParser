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

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_DIR="$(dirname -- "$SCRIPT_DIR")"
SAMPLE_DIR="$PROJECT_DIR/sample_deeds"
PARSE_CACHE="$HOME/.parse"

# Parse options first so unknown flags fail fast before checking tools or creating temp files
FORCE=false
PARSE_OPTS=true
declare -a FILE_ARGS=()
for arg in "$@"; do
    if [ "$PARSE_OPTS" = true ] && [ "$arg" = "--" ]; then
        PARSE_OPTS=false
        continue
    fi
    if [ "$PARSE_OPTS" = true ] && [ "$arg" = "--force" ]; then
        FORCE=true
    elif [ "$PARSE_OPTS" = true ] && [[ "$arg" == -* ]]; then
        echo "Error: Unknown option: $arg" >&2
        exit 1
    else
        FILE_ARGS+=("$arg")
    fi
done

if ! command -v parse >/dev/null 2>&1; then
    echo "Error: 'parse' CLI (semtools) not found in PATH." >&2
    exit 1
fi

# Max quality config for LlamaParse
CONFIG_FILE=$(mktemp)
cleanup() {
    rm -f -- "$CONFIG_FILE"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

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
        API_KEY=$(python3 -c "
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    data = json.load(f)
parse_cfg = data.get('parse') if isinstance(data, dict) else None
key = parse_cfg.get('api_key') if isinstance(parse_cfg, dict) else None
if not isinstance(key, str) or not key.strip():
    sys.exit(1)
print(key.strip())
" "$USER_CONFIG" 2>/dev/null || true)
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
MISSING_ARGS=0
declare -a PDF_FILES=()
if [ ${#FILE_ARGS[@]} -eq 0 ]; then
    # No file args: find all PDFs in sample_deeds/ (skip existing .md unless --force)
    while IFS= read -r -d '' pdf; do
        base="$(basename -- "$pdf")"
        dir="$(dirname -- "$pdf")"
        md_file="$dir/${base%.[pP][dD][fF]}.md"
        if [ "$FORCE" = true ] || [ ! -f "$md_file" ]; then
            PDF_FILES+=("$pdf")
        fi
    done < <(find "$SAMPLE_DIR" -maxdepth 1 -iname "*.pdf" -print0 | sort -z)
else
    # Specific files provided
    for arg in "${FILE_ARGS[@]}"; do
        if [ -f "$arg" ]; then
            PDF_FILES+=("$(cd -- "$(dirname -- "$arg")" && pwd)/$(basename -- "$arg")")
        elif [ -f "$SAMPLE_DIR/$arg" ]; then
            PDF_FILES+=("$(cd -- "$(dirname -- "$SAMPLE_DIR/$arg")" && pwd)/$(basename -- "$SAMPLE_DIR/$arg")")
        else
            echo "Error: File not found: $arg" >&2
            MISSING_ARGS=$((MISSING_ARGS + 1))
        fi
    done
fi

if [ "$MISSING_ARGS" -gt 0 ]; then
    exit 1
fi

if [ ${#PDF_FILES[@]} -eq 0 ]; then
    echo "No PDFs to process. All sample deeds already have .md files."
    echo "Use --force to reparse all PDFs."
    exit 0
fi

to_lower() {
    if command -v tr >/dev/null 2>&1; then
        printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
    else
        python3 -c 'import sys; print(sys.argv[1].lower(), end="")' "$1"
    fi
}

# Reject duplicate basenames (case-insensitive for macOS APFS/cache safety) and
# duplicate resolved output paths before invoking `parse`.
declare -a SEEN_BASENAMES=()
declare -a SEEN_TARGETS=()
for pdf in "${PDF_FILES[@]}"; do
    base="$(basename -- "$pdf")"
    base_lower="$(to_lower "$base")"
    for seen in ${SEEN_BASENAMES[@]+"${SEEN_BASENAMES[@]}"}; do
        if [ "$seen" = "$base_lower" ]; then
            echo "Error: Duplicate PDF basename '$base' would collide in $PARSE_CACHE." >&2
            exit 1
        fi
    done
    SEEN_BASENAMES+=("$base_lower")

    target_dir="$(cd -- "$(dirname -- "$pdf")" && pwd -P)"
    target_md="$target_dir/${base%.[pP][dD][fF]}.md"
    target_md_lower="$(to_lower "$target_md")"
    for seen_target in ${SEEN_TARGETS[@]+"${SEEN_TARGETS[@]}"}; do
        if [ "$seen_target" = "$target_md_lower" ]; then
            echo "Error: Duplicate output path '$target_md' would collide." >&2
            exit 1
        fi
    done
    SEEN_TARGETS+=("$target_md_lower")
done

# Clear any pre-existing cache entries for queued PDFs so a failed parse never
# copies stale markdown from a prior run.
for pdf in "${PDF_FILES[@]}"; do
    base="$(basename -- "$pdf")"
    rm -f -- "$PARSE_CACHE/${base}.md"
done

echo "Parsing ${#PDF_FILES[@]} PDF(s) with LlamaParse (agentic_plus tier, max settings)..."
echo "Settings: tier=agentic_plus | version=latest"
echo ""

# Run parse CLI (capture status so partial successes are still copied and accounted)
parse_rc=0
parse -v -c "$CONFIG_FILE" "${PDF_FILES[@]}" || parse_rc=$?

# Copy results from ~/.parse/ cache to each PDF's directory
COPIED=0
FAILED=0
for pdf in "${PDF_FILES[@]}"; do
    base="$(basename -- "$pdf")"
    cache_md="$PARSE_CACHE/${base}.md"
    target_dir="$(dirname -- "$pdf")"
    target_md="$target_dir/${base%.[pP][dD][fF]}.md"

    if [ -f "$cache_md" ]; then
        cp -- "$cache_md" "$target_md"
        echo "  -> $(basename -- "$target_md")"
        COPIED=$((COPIED + 1))
    else
        echo "  !! Missing output for: $base" >&2
        FAILED=$((FAILED + 1))
    fi
done

echo ""
echo "Done: $COPIED parsed, $FAILED failed."
if [ "$parse_rc" -ne 0 ]; then
    echo "Error: 'parse' exited with status $parse_rc." >&2
fi
if [ "$parse_rc" -ne 0 ] || [ "$FAILED" -gt 0 ]; then
    exit 1
fi
