import os
import re

fixed_width_re = re.compile(r'[^a-zA-Z0-9_-]width:\s*\d{3,}px', re.IGNORECASE)

for root, dirs, files in os.walk('templates'):
    for file in files:
        if file.endswith('.html'):
            path = os.path.join(root, file)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                
                printed_header = False
                for idx, line in enumerate(lines):
                    # Check if 'width:' is present and not preceded by 'max-'
                    if 'width:' in line.lower() and 'max-width' not in line.lower():
                        match = fixed_width_re.search(' ' + line)
                        if match:
                            if not printed_header:
                                print(f'{path}:')
                                printed_header = True
                            print(f'  Line {idx+1}: {line.strip()}')
            except Exception as e:
                print(f'Error reading {path}: {e}')
