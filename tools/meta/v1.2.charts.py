#!/usr/bin/env python3
"""
Power Usage vs. Paper Consensus Progress Visualization
- MINIMAL VERSION: Uses 'changed' field only, CSV first row as start time
"""

import csv
import sqlite3
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MultipleLocator
from pathlib import Path

# ============================================================================
# CONFIGURATION - Paths relative to THIS script
# ============================================================================
SCRIPT_DIR = Path(__file__).parent.resolve()
CSV_PATH = SCRIPT_DIR / "sensor_log.CSV"   # Match exact case
DB_PATH = SCRIPT_DIR / "db.sqlite"
OUTPUT_PATH = SCRIPT_DIR / "consensus_progress.png"

POWER_SMOOTHING_WINDOW = 24
PAPER_TICK_INTERVAL = 100
TIME_MAJOR_INTERVAL = 20
TIME_MINOR_INTERVAL = 10

# ============================================================================
# PARSE POWER LOG CSV
# ============================================================================
def parse_power_log(csv_path):
    """Parse power CSV, return list of {timestamp, psu_power_in}."""
    power_data = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        header = next(reader)
        
        # Find columns by name (case-insensitive)
        col_ts = next(i for i, h in enumerate(header) if 'date/time' in h.lower())
        col_power = next(i for i, h in enumerate(header) if 'psu power in' in h.lower() and '[w]' in h.lower())
        
        for row in reader:
            if len(row) <= max(col_ts, col_power):
                continue
            try:
                ts = datetime.fromisoformat(row[col_ts].strip().replace('Z', '+00:00'))
                power = float(row[col_power].strip().replace(',', '.'))
                power_data.append({'timestamp': ts, 'power': power})
            except (ValueError, IndexError):
                continue
    return power_data

# ============================================================================
# SMOOTH TIME SERIES
# ============================================================================
def smooth_series(values, window):
    """Centered rolling average with edge handling."""
    if len(values) < window:
        return values
    half = window // 2
    return [
        sum(values[max(0,i-half):min(len(values),i+half+1)]) / 
        len(values[max(0,i-half):min(len(values),i+half+1)])
        for i in range(len(values))
    ]

# ============================================================================
# GET PAPER COMPLETION TIMESTAMPS FROM 'changed' FIELD ONLY
# ============================================================================
def get_paper_timestamps(db_path):
    """Get list of 'changed' timestamps for papers that have one."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Simple query: just get the 'changed' field, filter empty/null
    cursor.execute("SELECT changed FROM papers WHERE changed IS NOT NULL AND changed != ''")
    
    timestamps = []
    for (changed_str,) in cursor.fetchall():
        try:
            ts = datetime.fromisoformat(changed_str.strip().replace('Z', '+00:00'))
            timestamps.append(ts)
        except (ValueError, AttributeError):
            continue
    
    conn.close()
    timestamps.sort()
    return timestamps

# ============================================================================
# BUILD REMAINING PAPERS LINE
# ============================================================================
def build_remaining_line(power_data, paper_timestamps):
    """Start at total papers, decrement by 1 at each paper's 'changed' time."""
    if not power_data:
        return []
    
    total = len(paper_timestamps)
    remaining_line = []
    idx = 0
    remaining = total
    
    for entry in power_data:
        ts = entry['timestamp']
        while idx < len(paper_timestamps) and paper_timestamps[idx] <= ts:
            remaining -= 1
            idx += 1
        remaining_line.append({'timestamp': ts, 'remaining': remaining})
    
    return remaining_line

# ============================================================================
# CONVERT TO ELAPSED MINUTES
# ============================================================================
def to_elapsed(data, start):
    """Convert timestamps to minutes from start time."""
    return [
        {'elapsed': (e['timestamp'] - start).total_seconds() / 60, **{k:v for k,v in e.items() if k!='timestamp'}}
        for e in data
    ]

# ============================================================================
# CREATE PLOT
# ============================================================================
def plot(power_data, remaining_data, output_path):
    if not power_data or not remaining_data:
        print("❌ No data to plot")
        return
    
    start = power_data[0]['timestamp']
    
    # Convert to elapsed minutes
    power_elapsed = to_elapsed(power_data, start)
    remaining_elapsed = to_elapsed(remaining_data, start)
    
    # Extract series
    times = [d['elapsed'] for d in power_elapsed]
    power_raw = [d['power'] for d in power_elapsed]
    power_smooth = smooth_series(power_raw, POWER_SMOOTHING_WINDOW)
    
    rem_times = [d['elapsed'] for d in remaining_elapsed]
    rem_count = [d['remaining'] for d in remaining_elapsed]
    
    # Colors
    C_REM = '#1f77b4'   # Blue
    C_PWR = '#ff7f0e'   # Orange
    
    fig, ax1 = plt.subplots(figsize=(7, 5))
    
    # LEFT AXIS: Remaining Papers
    ax1.set_xlabel('Elapsed Time (minutes)', fontsize=14, fontweight='bold', color='black')
    ax1.set_ylabel('Remaining Papers', fontsize=14, fontweight='bold', color='black')
    ax1.plot(rem_times, rem_count, color=C_REM, linewidth=2.5, label='Remaining Papers', drawstyle='steps-post')
    
    max_rem = max(rem_count) if rem_count else 1
    ax1.set_ylim(0, max(max_rem * 1.05, 1))  # Avoid singular transform
    ax1.yaxis.set_major_locator(MultipleLocator(PAPER_TICK_INTERVAL))
    ax1.tick_params(axis='y', labelcolor=C_REM, labelsize=11)
    
    # RIGHT AXIS: Wall Power
    ax2 = ax1.twinx()
    ax2.set_ylabel('Wall Power [W]', fontsize=14, fontweight='bold', color='black')
    ax2.plot(times, power_smooth, color=C_PWR, linewidth=2.5, label='Wall Power', alpha=0.95)
    
    # Scale power axis to 50% of paper axis (as requested)
    paper_max = ax1.get_ylim()[1]
    ax2.set_ylim(0, paper_max / 2.0)
    ax2.yaxis.set_major_locator(MultipleLocator(PAPER_TICK_INTERVAL / 2.0))
    ax2.tick_params(axis='y', labelcolor=C_PWR, labelsize=11)
    
    # Grid
    ax1.grid(True, axis='y', alpha=0.3, linestyle='--', linewidth=0.5)
    
    # Time axis: 20-min major (labeled), 10-min minor (grid only)
    ax1.set_xlim(0, times[-1] if times else 0)
    ax1.xaxis.set_major_locator(MultipleLocator(TIME_MAJOR_INTERVAL))
    ax1.xaxis.set_minor_locator(MultipleLocator(TIME_MINOR_INTERVAL))
    ax1.grid(True, axis='x', which='major', alpha=0.3, linestyle='--')
    ax1.grid(True, axis='x', which='minor', alpha=0.15, linestyle=':')
    ax1.tick_params(axis='x', labelsize=11)
    
    # Legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right', fontsize=10, framealpha=0.95)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✅ Saved: {output_path}")
    
    # Summary
    print(f"\n📊 Summary:")
    print(f"   Papers processed: {len(rem_count) and rem_count[0] or 0}")
    print(f"   Duration: {times[-1]:.1f} min")
    print(f"   Avg Power: {sum(power_smooth)/len(power_smooth):.1f} W")

# ============================================================================
# MAIN
# ============================================================================
def main():
    print("🔌 Loading power data...")
    power_data = parse_power_log(CSV_PATH)
    print(f"   → {len(power_data)} samples")
    
    print("📄 Loading paper timestamps from 'changed' field...")
    paper_ts = get_paper_timestamps(DB_PATH)
    print(f"   → {len(paper_ts)} papers with 'changed' timestamp")
    
    if not paper_ts:
        print("⚠️  No papers found with 'changed' timestamps. Check DB schema/values.")
        return
    
    print("📉 Building remaining papers series...")
    remaining = build_remaining_line(power_data, paper_ts)
    
    print("🎨 Generating plot...")
    plot(power_data, remaining, OUTPUT_PATH)

if __name__ == "__main__":
    main()