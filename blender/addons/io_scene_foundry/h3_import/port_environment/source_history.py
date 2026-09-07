"""Attach historical authoring evidence without authority over runtime bindings.

An exact loose reference can name a real historical asset and still differ from
the shipped sampler. History is a separate provenance axis, never a fallback
texture resolver. Supplied assertions remain distinguished from file hash checks.
"""
from collections import Counter
from copy import deepcopy
from pathlib import Path

from .dependencies import bitmap_path
from .paths import digest


def annotate(report, document):
    if document.get('format') != 'h3_authoring_source_history' or document.get('version') != 1:
        raise ValueError('Unsupported authoring-history evidence format')
    verified = {}
    for original in document['records']:
        row = deepcopy(original)
        identity = bitmap_path(row['source_bitmap'])
        if identity in verified:
            raise ValueError('Ambiguous historical source identity: '+identity)
        if (row['classification'] != 'HISTORICAL_H3_AUTHORING_ASSET'
            or row['runtime_binding_authority'] is not False
            or row['allowed_use'] != 'SOURCE_HISTORY_OR_OPTIONAL_FUTURE_AUTHORING_RECONSTRUCTION'):
            raise ValueError('Historical evidence cannot authorize a runtime bitmap substitution')
        if not all(row.get(k) for k in ('assertion', 'evidence_kind', 'confidence', 'verification_limit')):
            raise ValueError('Historical evidence must state its assertion, origin and verification limits')
        artifact = row['artifact']; path = Path(artifact['path']).resolve(strict=True)
        if path.stat().st_size != artifact['bytes'] or digest(path) != artifact['sha256']:
            raise ValueError('Historical artifact no longer matches recorded bytes: '+str(path))
        row.update(source_bitmap=identity, artifact_verification='LOCAL_FILE_HASH_VERIFIED',
                   runtime_binding_authority=False)
        verified[identity] = row
    # Validate the entire evidence document before changing the audit report.
    # Dependency gate records retain their original diagnostic objects; history
    # annotates copies so it cannot rewrite an unresolved contract by aliasing.
    rows = deepcopy(report['missing_references'])
    matched = set()
    for row in rows:
        identity = bitmap_path(row['source_bitmap'])
        history = verified.get(identity)
        if history is None:
            continue
        matched.add(identity)
        row['source_history'] = deepcopy(history)
        row['source_history_classification'] = history['classification']
        row['runtime_resolution_classification'] = row.get('runtime_resolution_classification', row['classification'])
        if row['classification'] == 'STALE_LOOSE_REFERENCE_VERIFIED_RUNTIME_BINDING':
            row['classification'] = 'HISTORICAL_AUTHORING_REFERENCE_VERIFIED_RUNTIME_BINDING'
        # An unresolved active reference remains unresolved. History alone never
        # clears the dependency gate or adds pixels to the authoring manifest.
    report['source_history'] = dict(records=[verified[k] for k in sorted(verified)],
        unmatched_identities=sorted(set(verified)-matched), runtime_binding_authority=False,
        policy='Historical asset existence and installed retail sampler identity are independent facts')
    report['missing_references'] = rows
    report['classification_counts'] = dict(Counter(r['classification'] for r in report['missing_references']))
