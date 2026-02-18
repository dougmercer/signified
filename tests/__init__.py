import sys
from pathlib import Path
src = Path(__file__).parent.parent / 'src'
sys.path.insert(0, str(src.resolve()))