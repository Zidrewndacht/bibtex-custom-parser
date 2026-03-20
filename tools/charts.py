#!/usr/bin/env python3
"""
Power Usage vs. Paper Consensus Progress Visualization
- Extract verifier timestamps from llm_log JSON field
- Remaining papers on LEFT axis (main), starting at 0
- Wall power on RIGHT axis (secondary), starting at 0, scaled to 50% of paper scale
- Aligned grid lines: power ticks at half the interval of paper ticks
- Normalized time scale (elapsed minutes from start, starts at 0)
- High-contrast colors for print, double-column layout
- Black axis labels, colored tick numbers, granular y-axis ticks
- Time gridlines restored: 20-min major ticks with labels, 10-min minor ticks
"""

import csv
import sqlite3
import json
from datetime import datetime
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, FuncFormatter, MultipleLocator

# ============================================================================
# CONFIGURATION
# ============================================================================
# CSV_PATH = "sensor_log.csv"
# DB_PATH = "1959_750ot_classified.db"
# OUTPUT_PATH = "consensus_progress.png"

CSV_PATH = "1gpu.csv"
DB_PATH = "1gpu.sqlite"
OUTPUT_PATH = "consensus_progress.png"

# Smoothing window for power data (number of samples for rolling average)
POWER_SMOOTHING_WINDOW = 24

# Tick interval for remaining papers (e.g., 100 papers per major tick)
PAPER_TICK_INTERVAL = 100

# Time tick intervals (minutes)
TIME_MAJOR_INTERVAL = 20  # Labels every 20 minutes
TIME_MINOR_INTERVAL = 10  # Grid lines every 10 minutes

# ============================================================================
# PARSE POWER LOG CSV (dynamic column detection)
# ============================================================================
def parse_power_log(csv_path):
    """Parse the power monitoring CSV file, finding relevant columns by header name."""
    power_data = []
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f, delimiter=';')
        header = next(reader)
        
        col_timestamp = None
        col_psu_power_in = None
        
        for i, col_name in enumerate(header):
            col_name_lower = col_name.lower().strip()
            if col_name_lower.startswith('date/time') or ('timestamp' in col_name_lower):
                col_timestamp = i
            elif 'psu power in' in col_name_lower and '[w]' in col_name_lower:
                col_psu_power_in = i
        
        if col_timestamp is None:
            raise ValueError("Could not find timestamp column in CSV header")
        
        for row in reader:
            if len(row) <= col_timestamp:
                continue
            
            timestamp_str = row[col_timestamp].strip()
            try:
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            except ValueError:
                continue
            
            def parse_float(val):
                try:
                    return float(val.replace(',', '.'))
                except (ValueError, AttributeError):
                    return 0.0
            
            psu_power_in = parse_float(row[col_psu_power_in]) if col_psu_power_in and len(row) > col_psu_power_in else 0.0
            
            power_data.append({
                'timestamp': timestamp,
                'psu_power_in': psu_power_in,
            })
    
    return power_data

# ============================================================================
# SMOOTH TIME SERIES WITH ROLLING AVERAGE
# ============================================================================
def smooth_series(values, window_size):
    """Apply centered rolling average with edge handling."""
    if len(values) < window_size:
        return values
    
    smoothed = []
    half_window = window_size // 2
    
    for i in range(len(values)):
        start = max(0, i - half_window)
        end = min(len(values), i + half_window + 1)
        window = values[start:end]
        smoothed.append(sum(window) / len(window))
    
    return smoothed

# ============================================================================
# EXTRACT VERIFIER TIMESTAMPS FROM LLM_LOG
# ============================================================================
def get_verifier_timestamps(db_path):
    """Get verifier timestamps from llm_log JSON field."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, llm_log FROM papers WHERE llm_log IS NOT NULL AND llm_log != '[]'")
    
    verifier_timestamps = []
    
    for paper_id, llm_log_json in cursor.fetchall():
        try:
            llm_log = json.loads(llm_log_json)
            if not isinstance(llm_log, list):
                continue
            
            verifier_times = []
            for entry in llm_log:
                if entry.get('type') == 'verifier' and 'timestamp' in entry:
                    try:
                        ts = datetime.fromisoformat(entry['timestamp'].replace('Z', '+00:00'))
                        verifier_times.append(ts)
                    except (ValueError, KeyError):
                        continue
            
            if verifier_times:
                verifier_timestamps.append(max(verifier_times))
                
        except json.JSONDecodeError:
            continue
    
    conn.close()
    verifier_timestamps.sort()
    return verifier_timestamps

# ============================================================================
# BUILD REMAINING PAPERS LINE
# ============================================================================
def build_remaining_papers_line(power_data, verifier_timestamps):
    """Build the remaining papers line starting at DB size, decreasing by 1 at each verifier timestamp."""
    if not power_data:
        return []
    
    total_papers = len(verifier_timestamps)
    
    remaining_line = []
    paper_idx = 0
    remaining = total_papers
    
    for power_entry in power_data:
        current_time = power_entry['timestamp']
        
        while paper_idx < len(verifier_timestamps) and verifier_timestamps[paper_idx] <= current_time:
            remaining -= 1
            paper_idx += 1
        
        remaining_line.append({
            'timestamp': current_time,
            'remaining': remaining,
        })
    
    return remaining_line

# ============================================================================
# CONVERT TO ELAPSED TIME (MINUTES FROM START)
# ============================================================================
def convert_to_elapsed_minutes(data, start_time):
    """Convert timestamps to elapsed minutes from start time."""
    elapsed_data = []
    for entry in data:
        elapsed_seconds = (entry['timestamp'] - start_time).total_seconds()
        elapsed_minutes = elapsed_seconds / 60.0
        elapsed_data.append({
            'elapsed_minutes': elapsed_minutes,
            **{k: v for k, v in entry.items() if k != 'timestamp'}
        })
    return elapsed_data

# ============================================================================
# CREATE VISUALIZATION
# ============================================================================
def create_visualization(power_data, remaining_papers_line, output_path):
    """Create visualization with aligned grid lines and proportional scales."""
    if not power_data or not remaining_papers_line:
        print("Error: No data to plot")
        return
    
    # Get start time for normalization
    start_time = power_data[0]['timestamp']
    
    # Convert to elapsed time
    power_elapsed = convert_to_elapsed_minutes(power_data, start_time)
    remaining_elapsed = convert_to_elapsed_minutes(remaining_papers_line, start_time)
    
    # Extract data
    elapsed_minutes = [d['elapsed_minutes'] for d in power_elapsed]
    psu_power_raw = [d['psu_power_in'] for d in power_elapsed]
    
    psu_power = smooth_series(psu_power_raw, POWER_SMOOTHING_WINDOW)
    
    remaining_minutes = [d['elapsed_minutes'] for d in remaining_elapsed]
    remaining_count = [d['remaining'] for d in remaining_elapsed]
    
    # Create figure for double-column layout
    fig, ax1 = plt.subplots(figsize=(7, 5))
    
    # HIGH-CONTRAST COLORS
    COLOR_REMAINING = '#1f77b4'      # Pure Blue
    COLOR_WALL_POWER = '#ff7f0e'     # Crimson Red
    
    # PRIMARY AXIS (LEFT) - Remaining Papers
    ax1.set_xlabel('Elapsed Time (minutes)', fontsize=16, fontweight='bold', color='black')
    ax1.set_ylabel('Remaining Papers', fontsize=16, fontweight='bold', color='black')
    
    # Plot remaining papers as step line
    ax1.plot(remaining_minutes, remaining_count, color=COLOR_REMAINING, linewidth=3, 
             label='Remaining Papers', drawstyle='steps-post', alpha=0.95)
    
    # Calculate paper axis scale
    max_papers = max(remaining_count)
    paper_axis_max = max_papers * 1.05  # 5% padding
    
    # FORCE Y-AXIS TO START AT 0
    ax1.set_ylim(0, paper_axis_max)
    
    # Tick settings for papers: black label, colored numbers, granular ticks
    ax1.yaxis.set_major_locator(MultipleLocator(PAPER_TICK_INTERVAL))
    ax1.tick_params(axis='y', labelcolor=COLOR_REMAINING, labelsize=12)
    
    # SECONDARY AXIS (RIGHT) - Wall Power
    ax2 = ax1.twinx()
    ax2.set_ylabel('Wall Power [W]', fontsize=16, fontweight='bold', color='black')
    
    # Plot smoothed wall power curve
    ax2.plot(elapsed_minutes, psu_power, color=COLOR_WALL_POWER, linewidth=3, 
             label='Wall Power (PSU In)', alpha=0.9)
    
    # ALIGN POWER SCALE TO PAPER SCALE: power_max = paper_max / 2
    power_axis_max = paper_axis_max / 1.0
    power_tick_interval = PAPER_TICK_INTERVAL / 1.0
    
    # FORCE POWER Y-AXIS TO START AT 0 WITH ALIGNED SCALE
    ax2.set_ylim(0, power_axis_max)
    
    # Tick settings for power: same grid alignment, half interval
    ax2.yaxis.set_major_locator(MultipleLocator(power_tick_interval))
    ax2.tick_params(axis='y', labelcolor=COLOR_WALL_POWER, labelsize=12)
    
    # GRID LINES: Enable horizontal grid from left axis (shared by both y-axes)
    ax1.grid(True, axis='y', alpha=0.4, linestyle='--', linewidth=0.5)
    
    # TIME AXIS: Start at 0, with 20-min major ticks (labeled) and 10-min minor ticks (grid only)
    ax1.set_xlim(0, elapsed_minutes[-1])
    
    # Major ticks: every 20 minutes with labels
    ax1.xaxis.set_major_locator(MultipleLocator(TIME_MAJOR_INTERVAL))
    ax1.xaxis.set_major_formatter(FuncFormatter(lambda x, p: f'{x:.0f}'))
    
    # Minor ticks: every 10 minutes for finer grid lines (no labels)
    ax1.xaxis.set_minor_locator(MultipleLocator(TIME_MINOR_INTERVAL))
    
    # Enable vertical grid lines at both major and minor ticks
    ax1.grid(True, axis='x', which='major', alpha=0.4, linestyle='--', linewidth=0.5)
    ax1.grid(True, axis='x', which='minor', alpha=0.2, linestyle='--', linewidth=0.5)
    
    # Tick label styling
    ax1.tick_params(axis='x', labelsize=12, which='major')
    ax1.tick_params(axis='x', which='minor', length=4)
    
    # Combine legends with larger font
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper right', fontsize=11, framealpha=0.9)
    
    fig.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"Visualization saved to: {output_path}")
    
    # Print summary statistics
    total_duration = elapsed_minutes[-1]
    total_papers = remaining_count[0] if remaining_count else 0
    verified = total_papers - (remaining_count[-1] if remaining_count else 0)
    
    print("\n=== Summary Statistics ===")
    print(f"Total papers with verifier logs: {total_papers}")
    print(f"Papers verified: {verified}")
    print(f"Remaining at end: {remaining_count[-1] if remaining_count else 'N/A'}")
    print(f"Total duration: {total_duration:.1f} minutes")
    print(f"Paper scale: 0-{paper_axis_max:.0f} (ticks every {PAPER_TICK_INTERVAL})")
    print(f"Power scale: 0-{power_axis_max:.0f} (ticks every {power_tick_interval:.0f})")
    if psu_power:
        print(f"Avg Wall Power (smoothed): {sum(psu_power)/len(psu_power):.2f} W")
        print(f"Wall Power range: {min(psu_power):.2f} - {max(psu_power):.2f} W")

# ============================================================================
# MAIN
# ============================================================================
def main():
    print("Loading power log data...")
    power_data = parse_power_log(CSV_PATH)
    print(f"  Loaded {len(power_data)} power samples")
    
    print("Querying database for verifier timestamps from llm_log...")
    verifier_timestamps = get_verifier_timestamps(DB_PATH)
    print(f"  Found {len(verifier_timestamps)} papers with verifier timestamps")
    
    print("Building remaining papers line...")
    remaining_papers_line = build_remaining_papers_line(power_data, verifier_timestamps)
    
    print("Creating visualization...")
    create_visualization(power_data, remaining_papers_line, OUTPUT_PATH)
    
    print("\nDone!")

if __name__ == "__main__":
    main()