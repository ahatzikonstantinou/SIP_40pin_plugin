#!/bin/bash

# === Default values ===
DEFAULT_PI_USERNAME="antonis"
DEFAULT_PI_HOST="192.168.3.23"
DEFAULT_DESTINATION="/opt/SIP2"

# === Usage info ===
usage() {
    echo "Usage: $0 <project_folder> [username] [host] [manifest_file] [destination_folder] [--dry-run]"
    echo "Note: manifest_file must end with .manifest"
    echo "Example: $0 ./ antonis 192.168.3.23 40pin.manifest /opt/SIP --dry-run"
    exit 1
}


# === Initialize flags ===
DRYRUN=false
QUIET=false
MANIFEST_FILE=""
POSITIONAL_ARGS=()

# === Parse arguments ===
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRYRUN=true ;;
    --quiet) QUIET=true ;;
    *.manifest) MANIFEST_FILE="$arg" ;;
    *) POSITIONAL_ARGS+=("$arg") ;;
  esac
done

# === Assign positional arguments ===
PROJECT_FOLDER="${POSITIONAL_ARGS[0]}"
PI_USERNAME="${POSITIONAL_ARGS[1]:-$DEFAULT_PI_USERNAME}"
PI_HOST="${POSITIONAL_ARGS[2]:-$DEFAULT_PI_HOST}"
PROJECT_FOLDER="${POSITIONAL_ARGS[0]}"
PI_USERNAME="${POSITIONAL_ARGS[1]:-$DEFAULT_PI_USERNAME}"
PI_HOST="${POSITIONAL_ARGS[2]:-$DEFAULT_PI_HOST}"

# Detect manifest file from POSITIONAL_ARGS if not already set
for arg in "${POSITIONAL_ARGS[@]:3}"; do
  if [[ "$arg" == *.manifest ]]; then
    MANIFEST_FILE="$arg"
    break
  fi
done

# Set destination folder to the next argument after manifest (if any)
DESTINATION_FOLDER="$DEFAULT_DESTINATION"
for ((i=3; i<${#POSITIONAL_ARGS[@]}; i++)); do
  if [[ "${POSITIONAL_ARGS[$i]}" != *.manifest ]]; then
    DESTINATION_FOLDER="${POSITIONAL_ARGS[$i]}"
  fi
done

RSYNC_DEST="$PI_USERNAME@$PI_HOST:$DESTINATION_FOLDER/"
[ "$QUIET" = false ] && echo "📁 Destination folder on remote: $DESTINATION_FOLDER"
[ "$QUIET" = false ] && echo "📄 Using manifest: ${MANIFEST_FILE:-(auto-detecting)}"

# === Validate project folder ===
if [ -z "$PROJECT_FOLDER" ] || [ ! -d "$PROJECT_FOLDER" ]; then
    echo "❌ Project folder '$PROJECT_FOLDER' is missing or invalid."
    usage
fi

# === Auto-detect manifest file if not provided ===
if [ -z "$MANIFEST_FILE" ]; then
    mapfile -t matches < <(find . -maxdepth 1 -type f -name "*.manifest")
    if [ ${#matches[@]} -eq 0 ]; then
        echo "❌ No .manifest file found in current directory."
        exit 1
    elif [ ${#matches[@]} -gt 1 ]; then
        echo "❌ Multiple .manifest files found. Please specify one explicitly."
        printf ' - %s\n' "${matches[@]}"
        exit 1
    else
        MANIFEST_FILE="${matches[0]}"
        [ "$QUIET" = false ] && echo "📄 Using manifest: $MANIFEST_FILE"
    fi
else
    [ "$QUIET" = false ] && echo "📄 Using specified manifest: $MANIFEST_FILE"
fi

# === Locate start of plugin file list ===
START_LINE=$(grep -n "^##### List all plugin files" "$MANIFEST_FILE" | cut -d: -f1)
if [ -z "$START_LINE" ]; then
    echo "❌ Manifest header not found in '$MANIFEST_FILE'."
    exit 1
fi

[ "$QUIET" = false ] && echo "📦 Reading file list from manifest..."
DESTINATION_PREFIX="$DESTINATION_FOLDER"
RSYNC_FLAGS="-avz --progress --relative"
FILE_LIST=()

# === Build rsync file list ===
STAGING_DIR=$(mktemp -d)

while read -r raw_line; do
    line=$(echo "$raw_line" | tr -d '\r' | xargs)
    if [[ -z "$line" || "$line" != *" "* ]]; then
        continue
    fi

    FILE_NAME=$(echo "$line" | awk '{print $1}')
    REL_PATH=$(echo "$line" | awk '{print $2}')
    LOCAL_PATH="$PROJECT_FOLDER/$FILE_NAME"
    RSYNC_PATH="$STAGING_DIR/$REL_PATH/$FILE_NAME"

    if [ ! -f "$LOCAL_PATH" ]; then
        echo "⚠️ File not found: $LOCAL_PATH — skipping"
        continue
    fi

    cp "$LOCAL_PATH" "$RSYNC_PATH" 2>/dev/null || mkdir -p "$(dirname "$RSYNC_PATH")" && cp "$LOCAL_PATH" "$RSYNC_PATH"

    FILE_LIST+=("./$REL_PATH/$FILE_NAME")
    [ "$QUIET" = false ] && echo "✔️ Staged: $LOCAL_PATH → $REL_PATH/$FILE_NAME"
done < <(tail -n +$((START_LINE + 1)) "$MANIFEST_FILE")


echo "🧪 Final file list: ${FILE_LIST[*]}"

# === Final rsync command ===
if [ ${#FILE_LIST[@]} -eq 0 ]; then
    echo "⚠️ No valid files to transfer."
    exit 1
fi

if [ "$DRYRUN" = true ]; then
    RSYNC_FLAGS="$RSYNC_FLAGS --dry-run"
    echo "🧪 Dry-run mode enabled. The following command would be executed:"
    echo "rsync $RSYNC_FLAGS ${FILE_LIST[*]} \"$RSYNC_DEST\""
else
    echo "🚀 Copying files to $RSYNC_DEST ..."
    cd "$STAGING_DIR"
    rsync $RSYNC_FLAGS "${FILE_LIST[@]}" "$RSYNC_DEST"
    rm -rf "$STAGING_DIR"
    if [ $? -eq 0 ]; then
        echo "✅ Files copied successfully."
    else
        echo "❌ Failed to copy files."
        exit 1
    fi
fi



exit 0
