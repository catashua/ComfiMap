import os
import csv
import glob
import re

folder = r"C:\Users\Student\Downloads\1.01_tradeoff_outputs"
pattern = os.path.join(folder, "route_*_*_tradeoffs.csv")
files = sorted(glob.glob(pattern))

output_path = os.path.join(r"C:\Users\Student\Downloads", "1.01_m_summary.csv")

DENOM_TOL = 1e-6  # treat |cd_short - cd_cool| below this as "no m"

results = []
fname_re = re.compile(r"route_(\d+)_(\d+)_tradeoffs\.csv", re.IGNORECASE)

for f in files:
    fname = os.path.basename(f)
    match = fname_re.match(fname)
    if not match:
        print(f"WARNING: filename pattern not matched for {fname}, skipping")
        continue

    month, hour = match.group(1), match.group(2)

    total = 0
    valid_nonzero_m = []

    with open(f, newline='', encoding='utf-8-sig') as csvfile:
        reader = csv.DictReader(csvfile)
        required_cols = {'d_short', 'cd_short', 'd_cool', 'cd_cool'}
        if not required_cols.issubset(set(reader.fieldnames)):
            print(f"WARNING: missing required columns in {fname}, skipping")
            continue

        for row in reader:
            total += 1
            try:
                d_short = float(row['d_short'])
                cd_short = float(row['cd_short'])
                d_cool = float(row['d_cool'])
                cd_cool = float(row['cd_cool'])
            except (ValueError, TypeError):
                continue  # missing/non-numeric -> m doesn't exist

            denom = cd_short - cd_cool
            if abs(denom) < DENOM_TOL:
                continue  # denominator effectively zero -> m doesn't exist

            m = abs((d_short - d_cool) / denom)

            if m != 0:
                valid_nonzero_m.append(m)

    valid_count = len(valid_nonzero_m)
    pct_nonzero = (valid_count / total * 100) if total > 0 else 0
    avg_m = sum(valid_nonzero_m) / valid_count if valid_count > 0 else 0

    results.append({
        'filename': fname,
        'month': month,
        'hour': hour,
        'total_rows': total,
        'valid_m_count': valid_count,
        'pct_m_nonzero': pct_nonzero,
        'avg_m_nonzero': avg_m
    })

with open(output_path, 'w', newline='', encoding='utf-8') as out:
    writer = csv.DictWriter(out, fieldnames=[
        'filename', 'month', 'hour', 'total_rows', 'valid_m_count',
        'pct_m_nonzero', 'avg_m_nonzero'
    ])
    writer.writeheader()
    writer.writerows(results)

print(f"Done. Processed {len(results)} files. Output written to: {output_path}")


