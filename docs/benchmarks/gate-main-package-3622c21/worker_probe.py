"""Probe real packaged schema workers without service or identity bootstrap."""
import argparse
import json
import subprocess
import threading
import time
from pathlib import Path

from lingshu_gate.application import schema_validation as validation
from lingshu_gate.registry import ToolExecutionError

parser=argparse.ArgumentParser()
parser.add_argument('--native',type=Path)
args=parser.parse_args()
original=subprocess.Popen
children=[]

def tracked(*a,**kw):
    child=original(*a,**kw)
    children.append(child)
    return child

if args.native:
    validation._worker_command=lambda:[str(args.native),validation.WORKER_FLAG]
subprocess.Popen=tracked
schema={'type':'object','properties':{'value':{'type':'string'}},'required':['value']}
cases=[]

def check(name,contract,arguments,expected=None,**kw):
    start=time.monotonic()
    before=len(children)
    code=None
    try:
        validation.validate_arguments(contract,arguments,**kw)
    except ToolExecutionError as exc:
        code=exc.code
    assert code==expected,(name,code,expected)
    current=children[before:]
    assert all(c.poll() is not None for c in current),(name,'unreaped worker')
    cases.append({'case':name,'result':'pass','error_code':code,
                  'elapsed_seconds':round(time.monotonic()-start,4),
                  'workers_started':len(current),'all_workers_reaped':True})

check('valid',schema,{'value':'synthetic-value'})
check('invalid',schema,{'value':42},'catalog_arguments_invalid')
regex={'properties':{'text':{'type':'string','pattern':'^(a+)+$'}}}
check('deadline',regex,{'text':'a'*20_000+'!'},'catalog_validation_timeout',deadline=time.monotonic()+.5)
check('slot-reusable-after-deadline',schema,{'value':'valid'})
cancel=threading.Event()
timer=threading.Timer(.3,cancel.set)
timer.start()
try:
    check('cancel',regex,{'text':'a'*20_000+'!'},'catalog_validation_cancelled',cancel=cancel)
finally:
    timer.cancel()
    timer.join()
check('slot-reusable-after-cancel',schema,{'value':'valid'})
print(json.dumps({'mode':'native' if args.native else 'wheel',
                  'cases':cases,'all_workers_reaped':all(c.poll() is not None for c in children),
                  'workers_started':len(children)},sort_keys=True))
