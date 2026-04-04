import numpy as np

# Read the file
with open(r'c:\Users\ABHINAV\Downloads\last4weeks_paper_trade.py', 'r') as f:
    lines = f.readlines()

# Find and replace the problematic line
new_lines = []
for i, line in enumerate(lines):
    if "close = pd.to_numeric(intr['Close'].squeeze(), errors='coerce').dropna()" in line:
        indent = len(line) - len(line.lstrip())
        new_lines.append(' ' * indent + "close_squeezed = intr['Close'].squeeze()\n")
        new_lines.append(' ' * indent + "if isinstance(close_squeezed, (int, float, np.float64)):\n")
        new_lines.append(' ' * (indent + 4) + "close_squeezed = pd.Series([close_squeezed])\n")
        new_lines.append(' ' * indent + "close = pd.to_numeric(close_squeezed, errors='coerce').dropna()\n")
    else:
        new_lines.append(line)

# Write back
with open(r'c:\Users\ABHINAV\Downloads\last4weeks_paper_trade.py', 'w') as f:
    f.writelines(new_lines)

print("Patched last4weeks_paper_trade.py")
