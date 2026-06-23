#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

SEEDS="${SEEDS:-100,101,102,103}"
JOBS="${JOBS:-4}"
CPU_SETS="${CPU_SETS:-0-3,16-19;4-7,20-23;8-11,24-27;12-15,28-31}"
OUTPUT_ROOT="${OUTPUT_ROOT:-outputs/production_9950x3d_isaac_queue}"
PYTHON_BIN="${PYTHON_BIN:-${PYTHON:-python}}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-14400}"
EXPORT_TIMEOUT_SECONDS="${EXPORT_TIMEOUT_SECONDS:-7200}"
EXPORT_AFTER_GENERATE="${EXPORT_AFTER_GENERATE:-1}"
EXPORT_FORMAT="${EXPORT_FORMAT:-usdc}"
EXPORT_RESOLUTION="${EXPORT_RESOLUTION:-512}"
ENABLE_WHEAT_REUSE="${ENABLE_WHEAT_REUSE:-0}"
RESUME="${RESUME:-1}"
CLEAN="${CLEAN:-0}"
DRY_RUN="${DRY_RUN:-0}"
KEEP_GOING="${KEEP_GOING:-1}"

SEED_LIST=()
CPU_SET_LIST=()
STOP_FILE="${OUTPUT_ROOT}/.stop_requested"
RUN_STARTED_AT=""

PROFILE_ENV_VARS=(
  INFINIGEN_PROFILE_TIMING
  INFINIGEN_PROFILE_GC
  INFINIGEN_PROFILE_ASSET_FACTORY
  INFINIGEN_PROFILE_BBOX
  INFINIGEN_PROFILE_SHELF_NODEGROUPS
  INFINIGEN_PROFILE_NATURE_SHELF_TRINKETS
  INFINIGEN_PROFILE_DATABLOCK_GROWTH
  INFINIGEN_PROFILE_PLANT_ASSETS
  INFINIGEN_PROFILE_BOOKSTACK
  INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY
)

quote_command() {
  printf "%q " "$@"
  printf "\n"
}

timestamp() {
  date -Iseconds
}

join_by_comma() {
  local IFS=,
  echo "$*"
}

trim_spaces() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf "%s" "$value"
}

parse_seeds() {
  local raw_tokens=()
  local raw_token token start end step seed
  IFS=',' read -r -a raw_tokens <<< "$SEEDS"
  for raw_token in "${raw_tokens[@]}"; do
    token="$(trim_spaces "$raw_token")"
    if [[ -z "$token" ]]; then
      continue
    fi
    if [[ "$token" =~ ^[0-9]+$ ]]; then
      SEED_LIST+=("$token")
    elif [[ "$token" =~ ^([0-9]+)-([0-9]+)$ ]]; then
      start="${BASH_REMATCH[1]}"
      end="${BASH_REMATCH[2]}"
      if (( start <= end )); then
        step=1
      else
        step=-1
      fi
      seed="$start"
      while true; do
        SEED_LIST+=("$seed")
        if (( seed == end )); then
          break
        fi
        seed=$(( seed + step ))
      done
    else
      echo "Invalid seed token '${token}'. Use comma seeds or ranges like SEEDS=100-139." >&2
      exit 2
    fi
  done

  if (( ${#SEED_LIST[@]} == 0 )); then
    echo "No seeds provided. Use SEEDS=100,101,102,103 or SEEDS=100-139." >&2
    exit 2
  fi
}

validate_jobs() {
  if ! [[ "$JOBS" =~ ^[0-9]+$ ]] || (( JOBS < 1 )); then
    echo "Invalid JOBS value: ${JOBS}" >&2
    exit 2
  fi
  if (( JOBS != 4 )); then
    echo "Warning: current 9950X3D clean candidate is JOBS=4; requested JOBS=${JOBS}." >&2
  fi
}

parse_cpu_sets() {
  local raw_cpu_sets=()
  local raw item
  IFS=';' read -r -a raw_cpu_sets <<< "$CPU_SETS"
  for raw in "${raw_cpu_sets[@]}"; do
    item="$(trim_spaces "$raw")"
    if [[ -n "$item" ]]; then
      CPU_SET_LIST+=("$item")
    fi
  done
  if (( ${#CPU_SET_LIST[@]} < JOBS )); then
    echo "CPU_SETS has ${#CPU_SET_LIST[@]} entries, but JOBS=${JOBS}." >&2
    echo "Provide one semicolon-separated CPU set per worker." >&2
    exit 2
  fi
}

require_tools() {
  if [[ ! -x /usr/bin/time ]]; then
    echo "Missing required /usr/bin/time for -v timing output." >&2
    exit 2
  fi
  if ! command -v timeout >/dev/null 2>&1; then
    echo "Missing required timeout command." >&2
    exit 2
  fi
  if ! command -v taskset >/dev/null 2>&1; then
    echo "Missing required taskset command for CPU binding." >&2
    exit 2
  fi
  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "PYTHON_BIN is not executable: ${PYTHON_BIN}" >&2
    exit 2
  fi
}

validate_output_root() {
  case "$OUTPUT_ROOT" in
    ""|"/"|".")
      echo "Refusing unsafe OUTPUT_ROOT: '${OUTPUT_ROOT}'." >&2
      exit 2
      ;;
  esac
}

assigned_seeds_for_worker() {
  local worker_id="$1"
  local assigned=()
  local idx
  for idx in "${!SEED_LIST[@]}"; do
    if (( idx % JOBS == worker_id )); then
      assigned+=("${SEED_LIST[$idx]}")
    fi
  done
  join_by_comma "${assigned[@]}"
}

seed_worker_id() {
  local seed_index="$1"
  echo $(( seed_index % JOBS ))
}

seed_coarse_dir() {
  local seed="$1"
  echo "${OUTPUT_ROOT}/seed_${seed}/coarse"
}

seed_usd_dir() {
  local seed="$1"
  echo "${OUTPUT_ROOT}/seed_${seed}/usd"
}

seed_log_dir() {
  local seed="$1"
  echo "${OUTPUT_ROOT}/logs/seed_${seed}"
}

usd_file_exists() {
  local folder="$1"
  [[ -d "$folder" ]] || return 1
  find "$folder" -type f \
    \( -name "*.${EXPORT_FORMAT}" -o -name "*.usd" -o -name "*.usdc" -o -name "*.usda" \) \
    -print -quit 2>/dev/null | grep -q .
}

build_generate_cmd() {
  local seed="$1"
  local cpu_set="$2"
  local output_folder="$3"
  CMD=(taskset -c "$cpu_set" env)
  local var
  for var in "${PROFILE_ENV_VARS[@]}"; do
    CMD+=(-u "$var")
  done
  CMD+=(
    INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1
    INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1
    INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1
    OMP_NUM_THREADS=1
    OPENBLAS_NUM_THREADS=1
    MKL_NUM_THREADS=1
    NUMEXPR_NUM_THREADS=1
    BLIS_NUM_THREADS=1
  )
  if [[ "$ENABLE_WHEAT_REUSE" == "1" ]]; then
    CMD+=(INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1)
  fi
  CMD+=(
    "$PYTHON_BIN"
    -m infinigen_examples.generate_indoors
    --seed "$seed"
    --task coarse
    --output_folder "$output_folder"
    -g fast_solve.gin
    -p
    compose_indoors.terrain_enabled=False
    home_room_constraints.has_fewer_rooms=False
    restrict_solving.solve_max_rooms=10
    populate_doors.door_chance=0
  )
}

build_export_cmd() {
  local cpu_set="$1"
  local input_folder="$2"
  local output_folder="$3"
  CMD=(taskset -c "$cpu_set" env)
  local var
  for var in "${PROFILE_ENV_VARS[@]}"; do
    CMD+=(-u "$var")
  done
  CMD+=(
    OMP_NUM_THREADS=1
    OPENBLAS_NUM_THREADS=1
    MKL_NUM_THREADS=1
    NUMEXPR_NUM_THREADS=1
    BLIS_NUM_THREADS=1
    "$PYTHON_BIN"
    -m infinigen.tools.export
    --input_folder "$input_folder"
    --output_folder "$output_folder"
    -f "$EXPORT_FORMAT"
    -r "$EXPORT_RESOLUTION"
    --omniverse
  )
}

write_seed_env() {
  local seed="$1"
  local worker_id="$2"
  local cpu_set="$3"
  local coarse_dir="$4"
  local usd_dir="$5"
  local env_file="$6"
  local generate_command="$7"
  local export_command="${8:-}"

  {
    echo "seed=${seed}"
    echo "worker_id=${worker_id}"
    echo "cpu_set=${cpu_set}"
    echo "coarse_output=${coarse_dir}"
    echo "usd_output=${usd_dir}"
    echo "python_bin=${PYTHON_BIN}"
    echo "jobs=${JOBS}"
    echo "seeds=${SEEDS}"
    echo "timeout_seconds=${TIMEOUT_SECONDS}"
    echo "export_after_generate=${EXPORT_AFTER_GENERATE}"
    echo "export_timeout_seconds=${EXPORT_TIMEOUT_SECONDS}"
    echo "export_format=${EXPORT_FORMAT}"
    echo "export_resolution=${EXPORT_RESOLUTION}"
    echo "enable_wheat_reuse=${ENABLE_WHEAT_REUSE}"
    echo "resume=${RESUME}"
    echo "clean=${CLEAN}"
    echo "dry_run=${DRY_RUN}"
    echo "keep_going=${KEEP_GOING}"
    echo "INFINIGEN_GC_BATCH_REMOVE_NODE_GROUPS=1"
    echo "INFINIGEN_REUSE_LARGESHELF_CHILD_NODEGROUPS=1"
    echo "INFINIGEN_FAST_NATURE_TRINKET_STABLE_POSE=1"
    if [[ "$ENABLE_WHEAT_REUSE" == "1" ]]; then
      echo "INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=1"
    else
      echo "INFINIGEN_REUSE_PLANT_TEMPLATE_GEOMETRY=unset"
    fi
    echo "OMP_NUM_THREADS=1"
    echo "OPENBLAS_NUM_THREADS=1"
    echo "MKL_NUM_THREADS=1"
    echo "NUMEXPR_NUM_THREADS=1"
    echo "BLIS_NUM_THREADS=1"
    echo "generate_command=${generate_command}"
    if [[ -n "$export_command" ]]; then
      echo "export_command=${export_command}"
    fi
  } > "$env_file"
}

write_status_file() {
  local status_file="$1"
  {
    echo "seed=${STATUS_SEED:-}"
    echo "worker_id=${STATUS_WORKER_ID:-}"
    echo "cpu_set=${STATUS_CPU_SET:-}"
    echo "generate_status=${GENERATE_STATUS:-}"
    echo "generate_exit_code=${GENERATE_EXIT_CODE:-}"
    echo "generate_started_at=${GENERATE_STARTED_AT:-}"
    echo "generate_ended_at=${GENERATE_ENDED_AT:-}"
    echo "export_status=${EXPORT_STATUS:-}"
    echo "export_exit_code=${EXPORT_EXIT_CODE:-}"
    echo "export_started_at=${EXPORT_STARTED_AT:-}"
    echo "export_ended_at=${EXPORT_ENDED_AT:-}"
    echo "output_folder=${STATUS_OUTPUT_FOLDER:-}"
    echo "usd_folder=${STATUS_USD_FOLDER:-}"
  } > "$status_file"
}

mark_seed_stopped() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local log_dir coarse_dir usd_dir now
  log_dir="$(seed_log_dir "$seed")"
  coarse_dir="$(seed_coarse_dir "$seed")"
  usd_dir="$(seed_usd_dir "$seed")"
  mkdir -p "$log_dir"
  now="$(timestamp)"
  STATUS_SEED="$seed"
  STATUS_WORKER_ID="$worker_id"
  STATUS_CPU_SET="$cpu_set"
  STATUS_OUTPUT_FOLDER="$coarse_dir"
  STATUS_USD_FOLDER="$usd_dir"
  GENERATE_STATUS="skipped"
  GENERATE_EXIT_CODE=""
  GENERATE_STARTED_AT="$now"
  GENERATE_ENDED_AT="$now"
  EXPORT_STATUS="not_requested"
  EXPORT_EXIT_CODE=""
  EXPORT_STARTED_AT=""
  EXPORT_ENDED_AT=""
  echo "KEEP_GOING=0: skipped because another worker requested stop." > "${log_dir}/status.txt"
  write_status_file "${log_dir}/status.txt"
}

run_generate_seed() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local coarse_dir="$4"
  local log_dir="$5"
  local generate_log="${log_dir}/generate.log"
  local generate_time="${log_dir}/generate_time.txt"
  local exit_code

  build_generate_cmd "$seed" "$cpu_set" "$coarse_dir"
  local generate_command
  generate_command="$(quote_command "${CMD[@]}")"

  {
    echo "worker_id=${worker_id}"
    echo "cpu_set=${cpu_set}"
    echo "seed=${seed}"
    echo "output_folder=${coarse_dir}"
    echo "started_at=$(timestamp)"
    echo "generate command:"
    echo "$generate_command"
    echo
  } > "$generate_log"

  if [[ "$RESUME" == "1" && -f "${coarse_dir}/scene.blend" ]]; then
    GENERATE_STARTED_AT="$(timestamp)"
    GENERATE_ENDED_AT="$GENERATE_STARTED_AT"
    GENERATE_EXIT_CODE="0"
    GENERATE_STATUS="skipped"
    echo "RESUME=1: skipping existing ${coarse_dir}/scene.blend" >> "$generate_log"
    return 0
  fi

  if [[ "$DRY_RUN" == "1" ]]; then
    GENERATE_STARTED_AT="$(timestamp)"
    GENERATE_ENDED_AT="$GENERATE_STARTED_AT"
    GENERATE_EXIT_CODE="0"
    GENERATE_STATUS="skipped"
    echo "DRY_RUN=1: generation skipped." >> "$generate_log"
    return 0
  fi

  mkdir -p "$coarse_dir"
  GENERATE_STARTED_AT="$(timestamp)"
  set +e
  /usr/bin/time -v -o "$generate_time" \
    timeout "$TIMEOUT_SECONDS" "${CMD[@]}" >> "$generate_log" 2>&1
  exit_code=$?
  set -e
  GENERATE_ENDED_AT="$(timestamp)"
  GENERATE_EXIT_CODE="$exit_code"

  if [[ "$exit_code" == "124" ]]; then
    GENERATE_STATUS="timeout"
  elif [[ "$exit_code" == "0" && -f "${coarse_dir}/scene.blend" ]]; then
    GENERATE_STATUS="complete"
  else
    GENERATE_STATUS="failed"
  fi

  {
    echo
    echo "ended_at=${GENERATE_ENDED_AT}"
    echo "exit_code=${GENERATE_EXIT_CODE}"
    echo "status=${GENERATE_STATUS}"
  } >> "$generate_log"
}

run_export_seed() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local coarse_dir="$4"
  local usd_dir="$5"
  local log_dir="$6"
  local export_log="${log_dir}/export.log"
  local export_time="${log_dir}/export_time.txt"
  local exit_code

  EXPORT_STATUS="not_requested"
  EXPORT_EXIT_CODE=""
  EXPORT_STARTED_AT=""
  EXPORT_ENDED_AT=""

  if [[ "$EXPORT_AFTER_GENERATE" != "1" ]]; then
    echo "EXPORT_AFTER_GENERATE=${EXPORT_AFTER_GENERATE}: export not requested." > "$export_log"
    return 0
  fi

  build_export_cmd "$cpu_set" "$coarse_dir" "$usd_dir"
  local export_command
  export_command="$(quote_command "${CMD[@]}")"

  {
    echo "worker_id=${worker_id}"
    echo "cpu_set=${cpu_set}"
    echo "seed=${seed}"
    echo "input_folder=${coarse_dir}"
    echo "output_folder=${usd_dir}"
    echo "started_at=$(timestamp)"
    echo "export command:"
    echo "$export_command"
    echo
  } > "$export_log"

  if [[ "$DRY_RUN" == "1" ]]; then
    EXPORT_STARTED_AT="$(timestamp)"
    EXPORT_ENDED_AT="$EXPORT_STARTED_AT"
    EXPORT_EXIT_CODE="0"
    EXPORT_STATUS="skipped"
    echo "DRY_RUN=1: export skipped." >> "$export_log"
    return 0
  fi

  if [[ "$GENERATE_STATUS" != "complete" && "$GENERATE_STATUS" != "skipped" ]]; then
    EXPORT_STARTED_AT="$(timestamp)"
    EXPORT_ENDED_AT="$EXPORT_STARTED_AT"
    EXPORT_EXIT_CODE=""
    EXPORT_STATUS="skipped"
    echo "Skipping export because coarse generation status is ${GENERATE_STATUS}." >> "$export_log"
    return 0
  fi

  if [[ ! -f "${coarse_dir}/scene.blend" ]]; then
    EXPORT_STARTED_AT="$(timestamp)"
    EXPORT_ENDED_AT="$EXPORT_STARTED_AT"
    EXPORT_EXIT_CODE=""
    EXPORT_STATUS="skipped"
    echo "Skipping export because scene.blend is missing: ${coarse_dir}" >> "$export_log"
    return 0
  fi

  if [[ "$RESUME" == "1" ]] && usd_file_exists "$usd_dir"; then
    EXPORT_STARTED_AT="$(timestamp)"
    EXPORT_ENDED_AT="$EXPORT_STARTED_AT"
    EXPORT_EXIT_CODE="0"
    EXPORT_STATUS="skipped"
    echo "RESUME=1: skipping existing USD export in ${usd_dir}" >> "$export_log"
    return 0
  fi

  mkdir -p "$usd_dir"
  EXPORT_STARTED_AT="$(timestamp)"
  set +e
  /usr/bin/time -v -o "$export_time" \
    timeout "$EXPORT_TIMEOUT_SECONDS" "${CMD[@]}" >> "$export_log" 2>&1
  exit_code=$?
  set -e
  EXPORT_ENDED_AT="$(timestamp)"
  EXPORT_EXIT_CODE="$exit_code"

  if [[ "$exit_code" == "124" ]]; then
    EXPORT_STATUS="timeout"
  elif [[ "$exit_code" == "0" ]] && usd_file_exists "$usd_dir"; then
    EXPORT_STATUS="complete"
  else
    EXPORT_STATUS="failed"
  fi

  {
    echo
    echo "ended_at=${EXPORT_ENDED_AT}"
    echo "exit_code=${EXPORT_EXIT_CODE}"
    echo "status=${EXPORT_STATUS}"
  } >> "$export_log"
}

run_seed() {
  local worker_id="$1"
  local cpu_set="$2"
  local seed="$3"
  local coarse_dir usd_dir log_dir env_file status_file
  coarse_dir="$(seed_coarse_dir "$seed")"
  usd_dir="$(seed_usd_dir "$seed")"
  log_dir="$(seed_log_dir "$seed")"
  env_file="${log_dir}/env.txt"
  status_file="${log_dir}/status.txt"
  mkdir -p "$log_dir" "$coarse_dir" "$usd_dir"

  STATUS_SEED="$seed"
  STATUS_WORKER_ID="$worker_id"
  STATUS_CPU_SET="$cpu_set"
  STATUS_OUTPUT_FOLDER="$coarse_dir"
  STATUS_USD_FOLDER="$usd_dir"
  GENERATE_STATUS=""
  GENERATE_EXIT_CODE=""
  GENERATE_STARTED_AT=""
  GENERATE_ENDED_AT=""
  EXPORT_STATUS="not_requested"
  EXPORT_EXIT_CODE=""
  EXPORT_STARTED_AT=""
  EXPORT_ENDED_AT=""

  local generate_cmd_text export_cmd_text
  build_generate_cmd "$seed" "$cpu_set" "$coarse_dir"
  generate_cmd_text="$(quote_command "${CMD[@]}")"
  build_export_cmd "$cpu_set" "$coarse_dir" "$usd_dir"
  export_cmd_text="$(quote_command "${CMD[@]}")"
  write_seed_env "$seed" "$worker_id" "$cpu_set" "$coarse_dir" "$usd_dir" \
    "$env_file" "$generate_cmd_text" "$export_cmd_text"

  run_generate_seed "$worker_id" "$cpu_set" "$seed" "$coarse_dir" "$log_dir"
  run_export_seed "$worker_id" "$cpu_set" "$seed" "$coarse_dir" "$usd_dir" "$log_dir"
  write_status_file "$status_file"

  if [[ "$KEEP_GOING" != "1" ]]; then
    if [[ "$GENERATE_STATUS" == "failed" || "$GENERATE_STATUS" == "timeout" \
       || "$EXPORT_STATUS" == "failed" || "$EXPORT_STATUS" == "timeout" ]]; then
      echo "seed=${seed} worker=${worker_id} requested stop at $(timestamp)" > "$STOP_FILE"
    fi
  fi
}

worker_main() {
  local worker_id="$1"
  local cpu_set="${CPU_SET_LIST[$worker_id]}"
  local worker_log="${OUTPUT_ROOT}/worker_${worker_id}.log"
  local assigned
  assigned="$(assigned_seeds_for_worker "$worker_id")"
  {
    echo "worker${worker_id} CPU_SET=${cpu_set} seeds=${assigned}"
    echo "started_at=$(timestamp)"
  } > "$worker_log"

  local idx seed
  for idx in "${!SEED_LIST[@]}"; do
    if (( idx % JOBS != worker_id )); then
      continue
    fi
    seed="${SEED_LIST[$idx]}"
    if [[ "$KEEP_GOING" != "1" && -f "$STOP_FILE" ]]; then
      echo "worker${worker_id}: stop requested before seed ${seed}" >> "$worker_log"
      mark_seed_stopped "$worker_id" "$cpu_set" "$seed"
      continue
    fi
    echo "worker${worker_id}: seed ${seed} coarse -> export -> next" >> "$worker_log"
    run_seed "$worker_id" "$cpu_set" "$seed" >> "$worker_log" 2>&1
  done
  echo "ended_at=$(timestamp)" >> "$worker_log"
}

safe_clean_involved_seeds() {
  if [[ "$CLEAN" != "1" ]]; then
    return
  fi
  local seed
  echo "CLEAN=1: removing only output/log directories for requested seeds."
  for seed in "${SEED_LIST[@]}"; do
    rm -rf "${OUTPUT_ROOT}/seed_${seed}" "${OUTPUT_ROOT}/logs/seed_${seed}"
  done
  rm -f "${OUTPUT_ROOT}/summary.csv" "${OUTPUT_ROOT}/summary.md" \
    "${OUTPUT_ROOT}/run_info.txt" "${OUTPUT_ROOT}/worker_"*.log "$STOP_FILE"
}

write_run_info() {
  local run_info="${OUTPUT_ROOT}/run_info.txt"
  {
    echo "date=$(timestamp)"
    echo "pwd=$(pwd)"
    echo
    echo "== git rev-parse --short HEAD =="
    git rev-parse --short HEAD || true
    echo
    echo "== git status --short =="
    git status --short || true
    echo
    echo "== uname -a =="
    uname -a || true
    echo
    echo "== nproc =="
    nproc || true
    echo
    echo "== lscpu =="
    lscpu || true
    echo
    echo "== lscpu -e=CPU,CORE,SOCKET,NODE,CACHE =="
    lscpu -e=CPU,CORE,SOCKET,NODE,CACHE || true
    echo
    echo "== lscpu -C =="
    lscpu -C || true
    echo
    echo "== free -h =="
    free -h || true
    echo
    echo "== swapon --show =="
    swapon --show || true
    echo
    echo "== df -h . =="
    df -h . || true
    echo
    echo "== lsblk =="
    lsblk -o NAME,MODEL,ROTA,SIZE,MOUNTPOINT || true
    echo
    echo "== which ${PYTHON_BIN} =="
    command -v "$PYTHON_BIN" || true
    echo
    echo "== ${PYTHON_BIN} -V =="
    "$PYTHON_BIN" -V || true
    echo
    echo "== queue settings =="
    echo "SEEDS=${SEEDS}"
    echo "JOBS=${JOBS}"
    echo "CPU_SETS=${CPU_SETS}"
    echo "OUTPUT_ROOT=${OUTPUT_ROOT}"
    echo "TIMEOUT_SECONDS=${TIMEOUT_SECONDS}"
    echo "EXPORT_AFTER_GENERATE=${EXPORT_AFTER_GENERATE}"
    echo "EXPORT_TIMEOUT_SECONDS=${EXPORT_TIMEOUT_SECONDS}"
    echo "EXPORT_FORMAT=${EXPORT_FORMAT}"
    echo "EXPORT_RESOLUTION=${EXPORT_RESOLUTION}"
    echo "ENABLE_WHEAT_REUSE=${ENABLE_WHEAT_REUSE}"
    echo "RESUME=${RESUME}"
    echo "CLEAN=${CLEAN}"
    echo "DRY_RUN=${DRY_RUN}"
    echo "KEEP_GOING=${KEEP_GOING}"
  } > "$run_info" 2>&1
}

print_worker_assignments() {
  local worker_id
  echo "Output root: ${OUTPUT_ROOT}"
  echo "JOBS=${JOBS}"
  echo "CPU_SETS=${CPU_SETS}"
  echo "Seeds: $(join_by_comma "${SEED_LIST[@]}")"
  echo
  for (( worker_id = 0; worker_id < JOBS; worker_id++ )); do
    echo "worker${worker_id} CPU_SET=${CPU_SET_LIST[$worker_id]} seeds=$(assigned_seeds_for_worker "$worker_id")"
  done
}

print_dry_run_plan() {
  local worker_id idx seed cpu_set coarse_dir usd_dir
  echo
  echo "DRY_RUN=1: commands printed; generation/export skipped."
  echo
  for (( worker_id = 0; worker_id < JOBS; worker_id++ )); do
    cpu_set="${CPU_SET_LIST[$worker_id]}"
    echo "== worker${worker_id} CPU_SET=${cpu_set} seeds=$(assigned_seeds_for_worker "$worker_id") =="
    for idx in "${!SEED_LIST[@]}"; do
      if (( idx % JOBS != worker_id )); then
        continue
      fi
      seed="${SEED_LIST[$idx]}"
      coarse_dir="$(seed_coarse_dir "$seed")"
      usd_dir="$(seed_usd_dir "$seed")"
      build_generate_cmd "$seed" "$cpu_set" "$coarse_dir"
      echo "seed${seed} coarse:"
      quote_command "${CMD[@]}"
      if [[ "$EXPORT_AFTER_GENERATE" == "1" ]]; then
        build_export_cmd "$cpu_set" "$coarse_dir" "$usd_dir"
        echo "seed${seed} export:"
        quote_command "${CMD[@]}"
      else
        echo "seed${seed} export: not requested"
      fi
      echo
    done
  done
}

write_summary() {
  "$PYTHON_BIN" scripts/analyze_9950x3d_production_queue.py \
    "$OUTPUT_ROOT" --write-summaries
}

main() {
  parse_seeds
  validate_jobs
  parse_cpu_sets
  require_tools
  validate_output_root

  RUN_STARTED_AT="$(timestamp)"
  mkdir -p "$OUTPUT_ROOT"
  safe_clean_involved_seeds
  rm -f "$STOP_FILE"
  mkdir -p "${OUTPUT_ROOT}/logs"
  write_run_info
  print_worker_assignments
  if [[ "$DRY_RUN" == "1" ]]; then
    print_dry_run_plan
  fi

  local worker_id
  for (( worker_id = 0; worker_id < JOBS; worker_id++ )); do
    worker_main "$worker_id" &
  done

  local status=0
  while (( $(jobs -pr | wc -l) > 0 )); do
    wait -n || status=$?
  done

  echo
  echo "Workers finished. Writing summary."
  write_summary

  if [[ -f "$STOP_FILE" && "$KEEP_GOING" != "1" ]]; then
    echo "KEEP_GOING=0 stop was requested: $(cat "$STOP_FILE")" >&2
    exit 1
  fi

  exit "$status"
}

main "$@"
