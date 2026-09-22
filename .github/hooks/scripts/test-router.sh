#!/usr/bin/env bash
# Do not use set -e; failed checks must still emit valid hook JSON.

INPUT=$(cat)
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$ROOT" || exit 1

changed_files() {
  {
    git diff --name-only HEAD 2>/dev/null
    git ls-files --others --exclude-standard 2>/dev/null
  } | sort -u
}

normalize_path() {
  local file="$1"
  file="${file#"$ROOT"/}"
  file="${file#"$PWD"/}"
  file="${file#./}"
  printf '%s\n' "$file"
}

stack_for_file() {
  case "$1" in
    *.py|pyproject.toml|requirements.txt|requirements-dev.txt)
      echo python
      ;;
    infra/*|azure.yaml|.github/workflows/azure-dev.yaml)
      echo infra
      ;;
  esac
}

stacks_for_changed_files() {
  local file stack stacks=""

  while IFS= read -r file; do
    stack=$(stack_for_file "$file")
    if [[ -n "$stack" && " $stacks " != *" $stack "* ]]; then
      stacks="$stacks $stack"
    fi
  done < <(changed_files)

  printf '%s\n' "$stacks"
}

run_python_checks() {
  local python ruff output status

  if [[ -x ".venv/bin/python" ]]; then
    python=".venv/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    python=$(command -v python3)
  else
    python=$(command -v python)
  fi

  if [[ -x ".venv/bin/ruff" ]]; then
    ruff=".venv/bin/ruff"
  else
    ruff=$(command -v ruff)
  fi

  if [[ -z "$python" || -z "$ruff" ]]; then
    RUN_RESULT="Stack: Python
Required tools are unavailable. Install the development dependencies and Ruff."
    return 1
  fi

  output=$(
    {
      echo "+ $ruff check ."
      "$ruff" check .
      lint_status=$?

      echo
      echo "+ $ruff format --check ."
      "$ruff" format --check .
      format_status=$?

      echo
      echo "+ $python -m pytest"
      "$python" -m pytest
      test_status=$?

      if ((lint_status != 0 || format_status != 0 || test_status != 0)); then
        exit 1
      fi
    } 2>&1
  )
  status=$?

  printf -v RUN_RESULT \
    'Stack: Python\nExit code: %s\n%s' \
    "$status" \
    "$(printf '%s\n' "$output" | tail -60)"

  return "$status"
}

run_infra_checks() {
  local output status

  output=$(
    {
      if command -v az >/dev/null 2>&1; then
        echo "+ az bicep build --file infra/main.bicep --stdout"
        az bicep build --file infra/main.bicep --stdout >/dev/null
        bicep_status=$?
      else
        echo "Azure CLI is unavailable; infra/main.bicep could not be compiled."
        bicep_status=1
      fi

      echo
      echo "+ jq empty infra/main.parameters.json"
      jq empty infra/main.parameters.json
      parameters_status=$?

      echo
      echo "+ bash -n infra/write_dot_env.sh"
      bash -n infra/write_dot_env.sh
      shell_status=$?

      echo
      if command -v pwsh >/dev/null 2>&1; then
        echo "+ PowerShell syntax check: infra/write_dot_env.ps1"
        pwsh -NoProfile -NonInteractive -Command \
          "[void][scriptblock]::Create((Get-Content -Raw 'infra/write_dot_env.ps1'))"
        powershell_status=$?
      else
        echo "PowerShell syntax check skipped because pwsh is unavailable."
        powershell_status=0
      fi

      if ((
        bicep_status != 0 ||
        parameters_status != 0 ||
        shell_status != 0 ||
        powershell_status != 0
      )); then
        exit 1
      fi
    } 2>&1
  )
  status=$?

  printf -v RUN_RESULT \
    'Stack: Azure infrastructure\nExit code: %s\n%s' \
    "$status" \
    "$(printf '%s\n' "$output" | tail -60)"

  return "$status"
}

run_stack() {
  case "$1" in
    python)
      run_python_checks
      ;;
    infra)
      run_infra_checks
      ;;
    *)
      return 0
      ;;
  esac
}

post_tool_use() {
  local file stack stacks context="" status_text

  file=$(
    printf '%s\n' "$INPUT" |
      jq -r '
        if (.toolArgs | type) == "object" then
          .toolArgs.path // .toolArgs.filePath // empty
        else
          empty
        end
      '
  )
  file=$(normalize_path "$file")
  stack=$(stack_for_file "$file")

  if [[ -n "$stack" ]]; then
    stacks="$stack"
  else
    # apply_patch may not expose one file path, so inspect the changed files.
    stacks=$(stacks_for_changed_files)
  fi

  if [[ -z "${stacks// }" ]]; then
    echo '{}'
    exit 0
  fi

  for stack in $stacks; do
    if run_stack "$stack"; then
      status_text="passed"
    else
      status_text="failed"
    fi

    context="${context}${context:+

}Hook checks for the $stack stack $status_text.
$RUN_RESULT"
  done

  jq -n --arg context "$context" '{"additionalContext":$context}'
}

agent_stop() {
  local stack stacks failures=""

  stacks=$(stacks_for_changed_files)
  if [[ -z "${stacks// }" ]]; then
    echo '{"decision":"allow"}'
    exit 0
  fi

  for stack in $stacks; do
    if ! run_stack "$stack"; then
      failures="${failures}${failures:+

}$RUN_RESULT"
    fi
  done

  if [[ -n "$failures" ]]; then
    jq -n \
      --arg reason "Repository checks are failing. Fix them before finishing this turn:

$failures" \
      '{"decision":"block","reason":$reason}'
  else
    echo '{"decision":"allow"}'
  fi
}

if printf '%s\n' "$INPUT" | jq -e 'has("toolArgs")' >/dev/null 2>&1; then
  post_tool_use
else
  agent_stop
fi