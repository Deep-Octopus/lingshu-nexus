#!/usr/bin/env bash
set -euo pipefail

REMOTE="${REMOTE:-origin}"
MAIN_BRANCH="${MAIN_BRANCH:-main}"
SOURCE_BRANCH="${SOURCE_BRANCH:-$(git branch --show-current)}"
COMMIT_MESSAGE="${1:-Update ${SOURCE_BRANCH}}"

if [[ -z "${SOURCE_BRANCH}" ]]; then
  echo "Could not determine the current git branch." >&2
  exit 1
fi

if [[ "${SOURCE_BRANCH}" == "${MAIN_BRANCH}" ]]; then
  echo "Run this script from a feature branch, not ${MAIN_BRANCH}." >&2
  exit 1
fi

echo "Source branch: ${SOURCE_BRANCH}"
echo "Main branch: ${MAIN_BRANCH}"
echo "Remote: ${REMOTE}"

git fetch "${REMOTE}"

if git show-ref --verify --quiet "refs/remotes/${REMOTE}/${SOURCE_BRANCH}"; then
  git merge-base --is-ancestor "${REMOTE}/${SOURCE_BRANCH}" "${SOURCE_BRANCH}" || {
    echo "Local ${SOURCE_BRANCH} is behind ${REMOTE}/${SOURCE_BRANCH}; pull/rebase first." >&2
    exit 1
  }
fi

git add -A

if git diff --cached --quiet; then
  echo "No local changes to commit on ${SOURCE_BRANCH}."
else
  git commit -m "${COMMIT_MESSAGE}"
fi

git push -u "${REMOTE}" "${SOURCE_BRANCH}"

git checkout "${MAIN_BRANCH}"
git pull --ff-only "${REMOTE}" "${MAIN_BRANCH}"
git merge --no-ff "${SOURCE_BRANCH}" -m "Merge ${SOURCE_BRANCH} into ${MAIN_BRANCH}"
git push "${REMOTE}" "${MAIN_BRANCH}"

git checkout "${SOURCE_BRANCH}"

echo "Published ${SOURCE_BRANCH} and merged it into ${MAIN_BRANCH}."
