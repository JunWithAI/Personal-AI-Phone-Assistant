#!/usr/bin/env bash
# Update the muse-ai-phone-assistant skill to the latest version.
#
#   bash scripts/update.sh
#
# This does two things, in order:
#   1. git pull — refresh the code and assistant template in this repo.
#   2. python3 scripts/setup.py --sync — re-apply the latest assistant
#      template to your existing assistant on Telnyx (backing up its
#      current config first).
#
# A git pull alone does NOT change the assistant: its instructions, voice,
# and telephony settings live on Telnyx, not in this repo. The sync step is
# what applies them.
#
# If this directory is not a git checkout (e.g. you copied the files),
# step 1 is skipped and the script still runs the sync with whatever
# template is present. To get future updates in that case, re-download or
# re-clone the repo and copy it over this directory, then run this script.

set -e
cd "$(dirname "$0")/.."

if [ -d .git ]; then
  echo "==> git pull"
  git pull --ff-only
else
  echo "==> not a git checkout; skipping git pull (sync will use the local template)"
fi

echo "==> setup.py --sync"
python3 scripts/setup.py --sync

echo
echo "Update complete."
