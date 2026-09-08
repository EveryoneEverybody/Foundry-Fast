"""Canonical namespace checks and hash-based ownership for generated files."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import time
import uuid

from . import DEFAULT_NAMESPACE, FORMAT


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def relative(value, *, allow_spaces=False):
    value = str(value).replace('\\', '/')
    parts = value.split('/')
    pattern=r'[A-Za-z0-9_. -]+' if allow_spaces else r'[A-Za-z0-9_.-]+'
    if (not value or any(not re.fullmatch(pattern, p) or p in {'.', '..'} or p!=p.strip()
                         or p.endswith('.') or p.split('.')[0].rstrip(' .').upper() in
                         {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)),
                          *(f'LPT{i}' for i in range(10))} for p in parts)):
        raise ValueError('Unsafe relative path: ' + value)
    return PurePosixPath(value)


def atomic_json(path, value, *, compact=False):
    path = Path(path)
    # The caller must already own and have validated this directory.
    temp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(value, stream, indent=None if compact else 2, sort_keys=True, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        deadline = time.monotonic() + 5
        while True:
            try:
                os.replace(temp, path)
                break
            except PermissionError as exc:
                # Windows readers may briefly omit FILE_SHARE_DELETE. Keep the
                # old complete report visible while retrying the atomic rename.
                if getattr(exc, 'winerror', None) not in {5, 32, 33} or time.monotonic() >= deadline:
                    raise
                time.sleep(.05)
    finally:
        temp.unlink(missing_ok=True)


class OutputPaths:
    def __init__(self, h3_root, reach_root, namespace=DEFAULT_NAMESPACE, *, allow_nested=False):
        self.h3 = Path(h3_root).resolve(strict=True)
        self.reach = Path(reach_root).resolve(strict=True)
        if self.h3 == self.reach or self.h3.is_relative_to(self.reach) or self.reach.is_relative_to(self.h3):
            raise ValueError('H3 and Reach roots must be separate')
        self.namespace = relative(namespace).as_posix().lower()
        if (not self.namespace.startswith('levels/h3_port/') or len(self.namespace.split('/')) < 3
                or (not allow_nested and len(self.namespace.split('/')) != 3)
                or self.namespace.split('/')[-1] in {'test', 'box'}):
            raise ValueError('Output must be a dedicated levels/h3_port/<asset> namespace')
        if self.namespace.startswith(DEFAULT_NAMESPACE + '/'):
            raise ValueError('The proof_box regression namespace cannot contain other generated environments')
        # Reach requires generated shader code identities to start with
        # shaders\ (tag_path_is_valid_for_location). Keep the same generated
        # asset identity and hash ownership under that engine-required root.
        self.infrastructure_namespace = ('shaders/'+self.namespace[len('levels/'):]
            if allow_nested and self.namespace != DEFAULT_NAMESPACE else None)
        self.roots = {}
        for name in ('data', 'tags'):
            root = (self.reach / name).resolve(strict=True)
            if not root.is_dir() or not root.is_relative_to(self.reach) or root == self.reach:
                raise ValueError('Reach data/tags root escapes the configured kit')
            self.roots[name] = root
        if self.roots['data'] == self.roots['tags']:
            raise ValueError('Reach data and tags roots must differ')
        self.h3_tags = (self.h3 / 'tags').resolve(strict=True)
        if not self.h3_tags.is_relative_to(self.h3):
            raise ValueError('H3 tags root escapes the configured source kit')
        # Check before creating any target directories, and again before writes.
        for kind in self.roots:
            self.destination(kind)

    @property
    def asset(self):
        return self.namespace.rsplit('/', 1)[1]

    @property
    def scenario(self):
        return self.namespace + '/' + self.asset

    def source(self, value):
        path = (self.h3_tags / relative(value)).resolve(strict=True)
        if not path.is_relative_to(self.h3_tags) or not path.is_file():
            raise ValueError('Source tag escapes H3 tags root')
        return path

    def destination(self, kind, suffix='', *, infrastructure=False):
        root = self.roots[kind]
        if infrastructure and (kind != 'tags' or not self.infrastructure_namespace):
            raise ValueError('This target has no owned shader infrastructure namespace')
        namespace = root / (self.infrastructure_namespace if infrastructure else self.namespace)
        # Normal Foundry animation authoring uses names such as "device
        # position.gr2". Tag identities/namespaces retain the strict grammar.
        path = namespace / relative(suffix,allow_spaces=kind=='data') if suffix else namespace
        # Reject any redirected component, even a link back inside the kit. This
        # prevents two textual asset identities from owning the same output.
        current = root
        for part in path.relative_to(root).parts:
            current = current / part
            if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
                raise ValueError('Output path contains a junction or symlink: ' + str(current))
        resolved = path.resolve()
        if (not resolved.is_relative_to(namespace) or not resolved.is_relative_to(root)
                or resolved.is_relative_to(self.h3)):
            raise ValueError('Output escapes the compiler namespace: ' + str(path))
        return resolved

    def owned_tag(self, identity):
        identity=relative(identity).as_posix()
        for namespace, infrastructure in [(self.namespace,False),(self.infrastructure_namespace,True)]:
            if namespace and identity.startswith(namespace+'/'):
                return self.destination('tags',identity[len(namespace)+1:],infrastructure=infrastructure)
        raise ValueError('Tag identity is outside the owned target namespaces: '+identity)

    def tag_directories(self):
        result=[self.destination('tags')]
        if self.infrastructure_namespace:
            result.append(self.destination('tags',infrastructure=True))
        return result

    def snapshot(self):
        result = {}
        locations=[('data',False),('tags',False)]
        if self.infrastructure_namespace:
            locations.append(('tags',True))
        for kind,infrastructure in locations:
            base = self.destination(kind,infrastructure=infrastructure)
            if not base.exists():
                continue
            for path in sorted(base.rglob('*')):
                # Check directories too; do not traverse a redirected subtree.
                checked = self.destination(kind, path.relative_to(base).as_posix(),infrastructure=infrastructure)
                if checked.is_file():
                    result[kind + '/' + checked.relative_to(self.roots[kind]).as_posix()] = digest(checked)
        return result

    def fingerprint(self):
        return hashlib.sha256(str(self.reach).casefold().encode()).hexdigest()


class Ownership:
    """A manifest outside tags/data owns exact hashes, never just an existing path."""
    def __init__(self, paths, report_dir):
        self.paths = paths
        self.directory = Path(report_dir).resolve()
        if self.directory.is_relative_to(paths.h3) or self.directory.is_relative_to(paths.reach):
            raise ValueError('Build reports and working data must be outside both editing kits')
        self.manifest = self.directory / ('proof_box_build_manifest.json' if paths.namespace == DEFAULT_NAMESPACE else 'environment_build_manifest.json')

    def preflight(self):
        actual = self.paths.snapshot()
        previous = None
        if self.manifest.exists():
            previous = json.loads(self.manifest.read_text(encoding='utf-8'))
            if (previous.get('format') != FORMAT + '.ownership' or previous.get('version') != 1
                    or previous.get('namespace') != self.paths.namespace
                    or previous.get('project_fingerprint') != self.paths.fingerprint()):
                raise ValueError('Build manifest belongs to a different compiler target')
        known = (previous or {}).get('files', {})
        for path, sha in actual.items():
            if known.get(path) != sha:
                raise ValueError('Refusing unowned or externally modified output: ' + path)
        # An interrupted worker has no completed after-snapshot. Never infer who
        # wrote a subsequently discovered file or silently adopt it.
        if previous and previous.get('status') == 'BUILDING':
            raise ValueError('Previous build was interrupted; review its journal before retrying')
        return actual

    def save(self, status, files, build_id):
        atomic_json(self.manifest, dict(format=FORMAT + '.ownership', version=1,
                    namespace=self.paths.namespace, project_fingerprint=self.paths.fingerprint(),
                    status=status, build_id=build_id, files=files))


@contextmanager
def build_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / '.proof_box.lock'
    with path.open('x', encoding='utf-8') as stream:
        stream.write(str(os.getpid()))
    try:
        yield
    finally:
        path.unlink()
