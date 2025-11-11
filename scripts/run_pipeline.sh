#!/usr/bin/env bash
# End-to-end data + visualizer pipeline orchestrator.
# By default this script expects to be invoked from anywhere within the
# workspace that contains both the agent_data_host repo and the users/ folder.
# It will cd into the workspace root so the same relative paths used by
# existing documentation continue to work.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"

USERS_ROOT="users"
OUTPUT_ROOT="agent_data_host/data"
TRANSCRIBE_MODEL="medium"
DEPLOY_VISUALIZER=true

usage() {
	cat <<EOF
Usage: $(basename "$0") [options]

Runs the standard dataset pipeline:
  1. python3 agent_data_host/transcribe_videos.py
  2. python3 agent_data_host/convert_all.py
  3. python3 agent_data_host/annotate_clicks_on_images.py
  4. python3 agent_data_host/make_chat_data.py
  5. node agent_data_host/scripts/build_visualizer_data.js
  6. vercel --prod agent_data_host/visualizer

Options:
  --users-root PATH        Override the users directory (default: users)
  --output-root PATH       Override the chat/asset output directory (default: agent_data_host/data)
  --model NAME             Whisper model passed to transcribe_videos.py (default: medium)
  --skip-deploy            Skip the final Vercel deployment step
  --help                   Show this help message
EOF
}

log() {
	printf '\n[%s] %s\n' "pipeline" "$*"
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--users-root)
			USERS_ROOT="$2"
			shift 2
			;;
		--output-root)
			OUTPUT_ROOT="$2"
			shift 2
			;;
		--model)
			TRANSCRIBE_MODEL="$2"
			shift 2
			;;
		--skip-deploy)
			DEPLOY_VISUALIZER=false
			shift
			;;
		--help|-h)
			usage
			exit 0
			;;
		*)
			echo "Unknown argument: $1" >&2
			usage
			exit 1
			;;
	esac
done

cd "$WORKSPACE_ROOT"

log "1/6 Transcribing videos under ${USERS_ROOT} (model=${TRANSCRIBE_MODEL})"
python3 agent_data_host/transcribe_videos.py \
	--users-root "$USERS_ROOT" \
	--model "$TRANSCRIBE_MODEL"

log "2/6 Converting raw sessions to llm_events and base chat data"
python3 agent_data_host/convert_all.py \
	--users-root "$USERS_ROOT" \
	--output-root "$OUTPUT_ROOT"

log "3/6 Annotating click overlays for chat assets"
python3 agent_data_host/annotate_clicks_on_images.py \
	--chat-root "$OUTPUT_ROOT"

log "4/6 Rebuilding chat data to include latest annotations"
python3 agent_data_host/make_chat_data.py \
	--users-root "$USERS_ROOT" \
	--output-root "$OUTPUT_ROOT"

log "5/6 Building visualizer payload and copying assets"
node agent_data_host/scripts/build_visualizer_data.js

if [[ "$DEPLOY_VISUALIZER" == true ]]; then
	log "6/6 Deploying visualizer via Vercel"
	vercel --prod agent_data_host/visualizer --yes
else
	log "Skipping Vercel deployment (requested)"
fi

log "Pipeline completed successfully."
