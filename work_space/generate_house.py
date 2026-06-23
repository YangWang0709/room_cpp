#!/usr/bin/env python3
"""
Generate a 10-room house with furniture using Infinigen, then convert to USD.

Usage:
    conda activate infinigen
    python generate_house.py [--seed SEED] [--output OUTPUT_DIR] [--skip-generate] [--skip-convert]

This script:
1. Generates a multi-room house (coarse stage) with ~10 rooms
2. Runs the fine/render stage to apply full materials
3. Converts the .blend file to USD with baked textures
"""

import argparse
import os
import subprocess
import sys
import time


def get_python():
    """Get the infinigen conda environment python path"""
    conda_prefix = os.environ.get("CONDA_PREFIX", "")
    if conda_prefix:
        return os.path.join(conda_prefix, "bin", "python")
    return sys.executable


def setup_env():
    """Setup required environment variables"""
    conda_prefix = os.environ.get("CONDA_PREFIX", "")
    if conda_prefix:
        lib_path = os.path.join(conda_prefix, "lib")
        current_ld = os.environ.get("LD_LIBRARY_PATH", "")
        if lib_path not in current_ld:
            os.environ["LD_LIBRARY_PATH"] = f"{lib_path}:{current_ld}"
        os.environ["QT_PLUGIN_PATH"] = os.path.join(conda_prefix, "lib", "qt6", "plugins")


def run_cmd(cmd, desc=None):
    """Run a command and stream output"""
    if desc:
        print(f"\n{'='*60}")
        print(f"  {desc}")
        print(f"{'='*60}")
    print(f"[CMD] {' '.join(cmd)}")
    start = time.time()
    result = subprocess.run(cmd, env=os.environ.copy())
    elapsed = time.time() - start
    if result.returncode != 0:
        print(f"[ERROR] Command failed with return code {result.returncode} ({elapsed:.0f}s)")
        sys.exit(1)
    print(f"[OK] Completed in {elapsed:.0f}s")
    return result


def generate_house(seed: int, output_dir: str):
    """Generate a multi-room house using Infinigen"""

    python = get_python()
    coarse_dir = os.path.join(output_dir, "coarse")

    # Step 1: Generate the house (coarse stage)
    # Key: Do NOT use singleroom.gin or fast_solve.gin
    # Use base_indoors.gin + multistory.gin for more rooms
    run_cmd(
        [
            python, "-m", "infinigen_examples.generate_indoors",
            "--seed", str(seed),
            "--task", "coarse",
            "--output_folder", coarse_dir,
            "-g", "base_indoors.gin", "multistory.gin",
            "-p",
            "compose_indoors.terrain_enabled=False",
            "home_room_constraints.has_fewer_rooms=False",
        ],
        desc="Step 1/3: Generating house layout + furniture (coarse stage)"
    )

    blend_file = os.path.join(coarse_dir, "scene.blend")
    if not os.path.isfile(blend_file):
        print(f"[ERROR] scene.blend not found at {blend_file}")
        sys.exit(1)

    print(f"\n[INFO] House generated: {blend_file}")
    print(f"[INFO] File size: {os.path.getsize(blend_file) / (1024*1024):.1f} MB")

    return blend_file


def convert_to_usd(blend_file: str, output_dir: str):
    """Convert .blend to USD with baked textures"""

    python = get_python()
    script_dir = os.path.dirname(os.path.abspath(__file__))
    blend2usd = os.path.join(script_dir, "blend2usd.py")
    usd_output = os.path.join(output_dir, "house.usdc")

    run_cmd(
        [
            python, blend2usd,
            blend_file,
            "-o", usd_output,
            "--overwrite",
            "--bake-textures",
            "--export-textures",
            "--bake-resolution", "1024",
        ],
        desc="Step 2/3: Converting to USD with baked textures"
    )

    if os.path.isfile(usd_output):
        print(f"\n[INFO] USD file: {usd_output}")
        print(f"[INFO] File size: {os.path.getsize(usd_output) / (1024*1024):.1f} MB")

    return usd_output


def main():
    parser = argparse.ArgumentParser(
        description="Generate a 10-room house and convert to USD",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate with default seed
  python generate_house.py

  # Generate with specific seed
  python generate_house.py --seed 42

  # Skip generation, only convert existing .blend
  python generate_house.py --skip-generate

  # Skip USD conversion
  python generate_house.py --skip-convert
        """,
    )
    parser.add_argument("--seed", type=int, default=0, help="Random seed for generation")
    parser.add_argument("--output", type=str, default="outputs/house_10rooms", help="Output directory")
    parser.add_argument("--skip-generate", action="store_true", help="Skip house generation step")
    parser.add_argument("--skip-convert", action="store_true", help="Skip USD conversion step")

    args = parser.parse_args()

    setup_env()

    output_dir = os.path.abspath(args.output)
    os.makedirs(output_dir, exist_ok=True)

    print(f"Output directory: {output_dir}")
    print(f"Random seed: {args.seed}")

    blend_file = None

    if not args.skip_generate:
        blend_file = generate_house(args.seed, output_dir)
    else:
        # Find existing blend file
        coarse_dir = os.path.join(output_dir, "coarse")
        blend_file = os.path.join(coarse_dir, "scene.blend")
        if not os.path.isfile(blend_file):
            print(f"[ERROR] No existing scene.blend found at {blend_file}")
            sys.exit(1)
        print(f"[INFO] Using existing blend file: {blend_file}")

    if not args.skip_convert:
        convert_to_usd(blend_file, output_dir)

    print(f"\n{'='*60}")
    print("  All done!")
    print(f"{'='*60}")
    print(f"  Blend file: {blend_file}")
    if not args.skip_convert:
        print(f"  USD file:   {os.path.join(output_dir, 'house.usdc')}")
    print(f"  Textures:   {os.path.join(output_dir, 'textures/')}")


if __name__ == "__main__":
    main()
