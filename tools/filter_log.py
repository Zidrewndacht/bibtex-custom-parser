#!/usr/bin/env python3
import sys
import re

def main():
    # Pattern to strictly match the engine stats line
    engine_pattern = re.compile(r"Engine \d+:")

    # Determine input source (file argument or stdin)
    input_stream = open(sys.argv[1], 'r') if len(sys.argv) > 1 else sys.stdin

    try:
        for line in input_stream:
            if engine_pattern.search(line):
                print(line, end='')
    finally:
        if input_stream is not sys.stdin:
            input_stream.close()

if __name__ == "__main__":
    main()