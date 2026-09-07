"""Validate a report's schema and graph invariants without opening either kit.

Usage: python validate_port_census.py path/to/040_voi_portability_report.json
Uses jsonschema when installed; graph checks always run with the stdlib.
"""
import collections
import json
from pathlib import Path
import sys

def validate(path):
    report = json.loads(Path(path).read_bytes())
    assert report['format'] == 'foundry.h3-reach-portability-census'
    assert report['version'] == 1
    try:
        import jsonschema
    except ImportError:
        print('jsonschema unavailable; running structural and graph invariant checks')
    else:
        schema = Path(__file__).resolve().parents[1] / 'data/port_census.schema.json'
        jsonschema.validate(report, json.loads(schema.read_bytes()))
    tags = report['tags']
    paths = [t['source_path'] for t in tags]
    assert paths == sorted(set(paths)), 'Tag order/identity collision'
    assert len({t['source_identity']['id'] for t in tags}) == len(tags)
    lookup = {t['source_path']: t for t in tags}
    edges = [(e['source'], e['target']) for e in report['dependencies']]
    assert edges == sorted(set(edges)), 'Edge ordering or duplication'
    edge_set = set(edges)
    reverse = collections.defaultdict(set)
    forward = collections.defaultdict(set)
    for a, b in edges:
        assert a in lookup and b in lookup
        reverse[b].add(a)
        forward[a].add(b)
    scenario = report['source']['scenario']
    for t in tags:
        p = t['source_path']
        assert set(t['references']) == forward[p]
        assert set(t['referenced_by']) == reverse[p]
        assert t['direct_dependency'] == (p != scenario and scenario in reverse[p])
        assert t['only_transitive'] == (p != scenario and not t['direct_dependency'])
        first = t['first_reached_by']
        assert first[0] == scenario and first[-1] == p
        assert len(first) == t['dependency_depth'] + 1
        assert all((a, b) in edge_set for a, b in zip(first, first[1:]))
        assert all(v == 'NOT_TESTED' for v in t['proven_target_status'].values())
    assert report['summary']['unique_h3_tags'] == len(tags)
    assert report['summary']['missing_references'] == sum(not t['exists'] for t in tags)
    counts = collections.Counter(t['source_group'] for t in tags)
    assert counts == {g['group']: g['total_unique_tags'] for g in report['tag_groups']}
    destinations = [m['proposed_destination'] for m in report['proposed_path_map']]
    assert len(destinations) == len(set(destinations)) == len(tags)
    assert set(report['minimum_boot_set']['source_assets']) <= set(paths)
    for cluster in report['minimum_combat_set']['candidate_encounter_clusters']:
        assert set(cluster['additional_source_assets']) <= set(paths)
    for call in report['scripts']['call_sites']:
        assert call['location']['line'] >= 1 and call['location']['column'] >= 1
        assert call['classification'] in {'DIRECT', 'SIGNATURE_CHANGE', 'RENAMED', 'EMULATABLE', 'STUB_CANDIDATE', 'UNSUPPORTED', 'UNKNOWN'}
    assert not any(report['safety'].values())
    print(f'PASS: schema v1 and graph invariants; {len(tags)} tags, {len(edges)} edges')
    return report

if __name__ == '__main__':
    validate(sys.argv[1])
