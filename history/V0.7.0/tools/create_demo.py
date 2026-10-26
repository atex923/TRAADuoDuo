"""Create an explicitly named new sample database; never overwrite."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from traaduoduo.store import ProjectStore

parser = argparse.ArgumentParser()
parser.add_argument('destination', type=Path)
args = parser.parse_args()
payload = ProjectStore.create(args.destination, '示範工程（可自行修改）')
basic = dict(payload['pages']['basic'], number='DEMO-001', start='2026-09-01')
ProjectStore(args.destination).save({'basic': basic, 'holidays': [['2026-09-25', '示範假期']]}, 0)
print(payload['path'])
