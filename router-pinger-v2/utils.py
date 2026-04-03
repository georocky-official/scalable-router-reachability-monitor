import csv
import os

def append_to_csv(filename, row_dict, fieldnames):
    """Append a single row to CSV, creating file with header if needed."""
    file_exists = os.path.exists(filename)
    with open(filename, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row_dict)