import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_h3_scenario_scene import PKG
from h3_import_fixture import payload
from h3_scenario_content_fixture import content_inventory

o=importlib.import_module(PKG+'.scenario_objects')
c=importlib.import_module(PKG+'.scenario_content')
f=importlib.import_module(PKG+'.scenario_frames')


class AttachmentTests(unittest.TestCase):
    def test_selection_retains_source_record_and_variant(self):
        data=payload();child=dict(source_tag='objects/test/rifle.weapon',variant='authored',parent_marker='rack',child_marker='grip',source_fields=[{'name':'raw','decoder_value':'raw'}])
        data['default_variant']='rack';data['variants']=[dict(name='rack',children=[child]),dict(name='empty',children=[])]
        result,errors=o.children(data,'');self.assertFalse(errors)
        self.assertEqual(result[0]['source_tag'],child['source_tag']);self.assertEqual(result[0]['variant'],'authored')
        self.assertEqual(result[0]['source_fields'],child['source_fields'])
        self.assertEqual(o.children(data,'empty'),([],[]))
        self.assertTrue(o.children(data,'unknown')[1])

    def test_legacy_classless_child_not_guessed(self):
        data=payload();data['variants']=[dict(name='rack',children=[dict(object='objects/test/rifle')])]
        result,errors=o.children(data,'rack');self.assertEqual(result,[]);self.assertIn('tag class unavailable',errors[0])

    def test_duplicate_and_missing_markers_are_not_guessed(self):
        data=payload()
        with self.assertRaises(ValueError):f.marker_matrix(data,'missing')
        data['render']['markers']*=2
        with self.assertRaises(ValueError):f.marker_matrix(data,'attach')

    def test_semantic_path_skips_material_helper_and_reuses_source(self):
        content=c.plan(content_inventory());content['placements']=content['placements'][:2]
        source='objects/test/sound.sound_scenery'
        for row in content['placements']:row['source_tag']=source
        calls=[]
        def collect(gen):
            while True:
                try:next(gen)
                except StopIteration as result:return result.value
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'tags';path=root/source;path.parent.mkdir(parents=True);path.write_bytes(b'source untouched')
            output=Path(folder)/'output';output.mkdir();helper=Path(folder)/'helper.exe';helper.touch()
            class Process:
                returncode=0
                def __init__(self,args,**kwargs):
                    calls.append(args)
                    destination=Path(args[args.index('--output')+1])
                    (destination/'source.h3semantic.json').write_text(json.dumps(dict(format='foundry.h3-semantic',version=1,source_tag=source,game='halo3_mcc',destination_tags_written=False,records=[])))
                def poll(self):return 0
            with patch.object(o.subprocess,'Popen',Process):
                assets=collect(o.extract(content,root,output,helper,True));again=collect(o.extract(content,root,output,helper,True))
            self.assertEqual(len(calls),1);self.assertEqual(assets,again)
            self.assertEqual(assets[source]['status'],'semantic');self.assertEqual(path.read_bytes(),b'source untouched')


if __name__=='__main__':unittest.main()
