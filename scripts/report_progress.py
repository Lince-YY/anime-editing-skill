#!/usr/bin/env python3
"""Atomically record production progress; optionally wrap an explicitly supplied local command."""
import argparse
import json
import os
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from build_flow_panel import STATES, validate


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def file_lock(path, timeout=10):
    lock = path.with_name(path.name + '.lock')
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError('Progress record is locked; check its owning writer before removing the lock')
            time.sleep(0.05)
    try:
        (lock / 'owner.json').write_text(json.dumps({'pid': os.getpid(), 'created_at': now()}), encoding='utf-8')
        yield
    finally:
        (lock / 'owner.json').unlink(missing_ok=True)
        lock.rmdir()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', dir=path.parent, prefix='.' + path.name,
                                     suffix='.tmp', encoding='utf-8', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def update(path, step_id, status=None, progress=None, message=None, output=None,
           artifact=None, asset_type=None, report=None, expected_revision=None):
    path = Path(path).resolve()
    with file_lock(path):
        data = json.loads(path.read_text(encoding='utf-8'))
        validate(data, path.parent)
        revision = int(data.get('meta', {}).get('revision', 0))
        if expected_revision is not None and revision != expected_revision:
            raise ValueError('Revision conflict; reread the latest flow before editing')
        step = next((s for s in data['steps'] if s['id'] == step_id), None)
        if step is None:
            raise ValueError('Unknown step')
        if status:
            if status not in STATES:
                raise ValueError('Unknown status')
            step['status'] = status
            if message is None:
                step['message'] = {'planned': '计划中', 'running': '执行中',
                    'ready': '已产出，等待验收', 'accepted': '已记录接受',
                    'missing': '缺少所需产物', 'failed': '未通过，请查看执行记录'}[status]
            # Nodes inherit the current step instead of retaining a stale override.
            for node in data['chart']['nodes']:
                if node['step'] == step_id:
                    node.pop('status', None)
        if progress is not None:
            if not 0 <= progress <= 100:
                raise ValueError('Progress must be 0..100; omit it when unknown')
            step['progress'] = progress
        if message is not None:
            step['message'] = message
        if output is not None:
            step['output'] = output
            for node in data['chart']['nodes']:
                if node['step'] == step_id and not node.get('asset'):
                    node['text'] = output
        if artifact:
            source = Path(artifact).resolve()
            if not source.is_file():
                raise ValueError('Artifact is missing')
            if not asset_type:
                suffix = source.suffix.lower()
                asset_type = ('image' if suffix in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg') else
                              'audio' if suffix in ('.wav', '.mp3', '.flac', '.m4a', '.ogg') else 'video')
            key = 'step_%s_output' % step_id
            data.setdefault('assets', {})[key] = {'id': key, 'type': asset_type,
                'title': step['title'] + ' · 产物', 'caption': output or step.get('output', ''),
                'src': os.path.relpath(source, path.parent), 'status': 'ready'}
            if key not in step.setdefault('media', []):
                step['media'].append(key)
            for node in data['chart']['nodes']:
                if node['step'] == step_id:
                    node['asset'] = key
                    node.pop('text', None)
                    break
        if report:
            source = Path(report).resolve()
            if source.stat().st_size > 1024 * 1024:
                raise ValueError('Report is larger than 1 MiB; attach a concise report')
            report_data = json.loads(source.read_text(encoding='utf-8'))
            step['content'] = json.dumps(report_data, ensure_ascii=False, indent=2)
        step['updated_at'] = now()
        data.setdefault('meta', {}).update({'revision': revision + 1, 'updated_at': now()})
        validate(data, path.parent)
        atomic_write(path, data)
        return {'step': step_id, 'status': step['status'], 'revision': revision + 1}


def initialize(path, title, names):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not names or any(not name.strip() for name in names):
        raise ValueError('Provide nonempty step names')
    with file_lock(path):
        if path.exists():
            raise ValueError('Refusing to overwrite an existing flow')
        steps = [{'id': i, 'short_title': name, 'title': name, 'status': 'planned',
                  'environment': '待环境体检与选路确认', 'tools': [], 'input': '待准备',
                  'action': '待执行', 'output': '尚未产出', 'content': '', 'media': []}
                 for i, name in enumerate(names, 1)]
        data = {'meta': {'title': title, 'date': now()[:10], 'updated_at': now(), 'revision': 1},
                'steps': steps, 'assets': {}, 'runtime': [], 'runtime_groups': [],
                'chart': {'lanes': [{'name': '制作进度', 'place': 'hybrid', 'detail': '按实际执行补充工具与位置'}],
                          'nodes': [{'id': 'step_%s' % s['id'], 'row': 0, 'step': s['id'], 'place': 'hybrid',
                                     'title': s['title'], 'caption': '尚未开始', 'text': '等待执行'} for s in steps],
                          'links': [['step_%s' % i, 'step_%s' % (i + 1)] for i in range(1, len(steps))]}}
        validate(data, path.parent)
        atomic_write(path, data)


def stop_owned_process(process):
    if process.poll() is not None:
        return
    if os.name == 'posix':
        os.killpg(process.pid, signal.SIGTERM)
    else:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=10)
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        if os.name == 'posix':
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait(timeout=3)


def run_command(args):
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        raise ValueError('Supply an explicit command after --')
    if args.timeout <= 0:
        raise ValueError('Timeout must be positive')
    log = Path(args.log).resolve()
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists():
        raise ValueError('Use a new log path for every run')
    update(args.data, args.step, 'running', 0, '执行中；百分比仅在有真实进度时更新')
    process = None
    old_term = signal.getsignal(signal.SIGTERM)
    def cancelled(*_args):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, cancelled)
    try:
        with log.open('x', encoding='utf-8') as stream:
            process = subprocess.Popen(command, cwd=args.cwd, stdout=stream, stderr=subprocess.STDOUT,
                                       start_new_session=(os.name == 'posix'))
            code = process.wait(timeout=args.timeout)
        if code == 0:
            update(args.data, args.step, 'ready', 100, '命令执行完成，产物和效果待验收',
                   args.output or '已执行，等待内容验收', args.artifact, args.asset_type, args.report_json)
        else:
            update(args.data, args.step, 'failed', message='命令失败，退出码 %s；查看本地执行日志' % code)
        return code if 0 <= code <= 125 else 1
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        if process:
            stop_owned_process(process)
        update(args.data, args.step, 'failed', message='执行超时或被取消；已停止本次子进程')
        return 124 if isinstance(exc, subprocess.TimeoutExpired) else 130
    except (OSError, ValueError) as exc:
        if process:
            stop_owned_process(process)
        update(args.data, args.step, 'failed', message='命令或产物登记失败；查看终端错误')
        raise exc
    finally:
        signal.signal(signal.SIGTERM, old_term)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='operation', required=True)
    init = sub.add_parser('init')
    init.add_argument('--data', type=Path, required=True)
    init.add_argument('--title', required=True)
    init.add_argument('--steps', required=True, help='Comma-separated names')
    for name in ('update', 'run'):
        p = sub.add_parser(name)
        p.add_argument('--data', type=Path, required=True)
        p.add_argument('--step', type=int, required=True)
        p.add_argument('--output')
        p.add_argument('--artifact', type=Path)
        p.add_argument('--asset-type', choices=['image', 'video', 'audio'])
        p.add_argument('--report-json', type=Path, help='Explicitly include this JSON in the local report')
        if name == 'update':
            p.add_argument('--status', choices=sorted(STATES))
            p.add_argument('--progress', type=float)
            p.add_argument('--message')
            p.add_argument('--expected-revision', type=int)
        else:
            p.add_argument('--timeout', type=float, default=600)
            p.add_argument('--cwd', type=Path)
            p.add_argument('--log', required=True)
            p.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        if args.operation == 'init':
            initialize(args.data, args.title, [name.strip() for name in args.steps.split(',')])
            result = {'created': str(args.data)}
        elif args.operation == 'update':
            result = update(args.data, args.step, args.status, args.progress, args.message, args.output,
                            args.artifact, args.asset_type, args.report_json, args.expected_revision)
        else:
            raise SystemExit(run_command(args))
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, 'progress: %s\n' % exc)


if __name__ == '__main__':
    main()
