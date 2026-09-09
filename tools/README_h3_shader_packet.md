# H3 shader packet helper

`h3_shader_packet.py` batch-exports Halo 3 shader evidence so H3 -> Reach material translation work does not require opening/dumping tags one at a time.

## Preferred workflow: use Baboon's scenario reference report

1. Open the H3EK `tags` folder in Baboon.
2. In **Folders** view, open `levels/solo/040_voi`.
3. Right-click `040_voi.scenario` and choose **Dump Tag References...**.
4. Save that report somewhere convenient, for example `D:\040_voi_references.txt`.
5. Run:

    py tools\h3_shader_packet.py "D:\SteamLibrary\steamapps\common\H3EK" --reference-report "D:\040_voi_references.txt" --output "D:\h3_shader_packet_040_voi" --copy-raw

Replace the H3EK path with your actual Halo 3 Editing Kit directory.

This is the preferred mode because Baboon's report follows the scenario's actual recursive tag dependency graph. The helper then extracts every shader-family tag named anywhere in that report, including shared/object shaders located outside `levels/solo/040_voi`.

## What it gathers

The contract side selects:

- `tags/shaders/shader.render_method_definition`
- every `*.render_method_option` under `tags/shaders/`

The fixture side selects either:

- every referenced shader-family tag found in a Baboon `Dump Tag References...` report, or
- as a fallback, every shader-family tag physically stored under `tags/levels/solo/040_voi/` (or another `--subtree`).

Shader-family tags include `.shader`, `.shader_custom`, `.shader_decal`, `.shader_foliage`, `.shader_fur`, `.shader_fur_stencil`, `.shader_glass`, `.shader_halogram`, `.shader_screen`, `.shader_terrain`, and `.shader_water`.

It invokes H3 `tool.exe export-tag-to-xml` for each selected tag, preserves the tag-relative directory layout in the output, records per-tag status in `manifest.json`, and can optionally copy the raw binary tags too.

This helper gathers evidence only. It deliberately does **not** translate H3 shader values into Reach values.

## Baboon bulk JSON: one action, not one tag at a time

For the Baboon JSON side of the research packet, you also do not need to export individual RMOPs manually:

1. Keep the H3EK `tags` folder open in Baboon.
2. In **Folders** view, right-click the top-level `shaders` folder.
3. Choose **Dump folder to JSON...**.
4. Point it at something like `D:\h3_shader_packet_040_voi\baboon_json\shaders`.

Baboon will dump the entire folder subtree to pretty-printed JSON while preserving the tag hierarchy. That captures the H3 `shader.render_method_definition`, all H3 material/model RMOPs, global shader options, and the rest of the shader contract in one operation.

## First run: dry run

To verify what the helper selected without invoking Tool:

    py tools\h3_shader_packet.py "D:\SteamLibrary\steamapps\common\H3EK" --reference-report "D:\040_voi_references.txt" --dry-run

The dry run creates `manifest.json` and prints every selected tag.

## Fallback: physical level subtree only

If you do not have a Baboon reference report yet:

    py tools\h3_shader_packet.py "D:\SteamLibrary\steamapps\common\H3EK" --output "D:\h3_shader_packet_040_voi" --copy-raw

That dumps the contract plus shader-family tags physically located under `levels/solo/040_voi`.

For another level/subtree:

    py tools\h3_shader_packet.py "D:\SteamLibrary\steamapps\common\H3EK" --subtree "levels\solo\030_outskirts" --output "D:\h3_shader_packet_030" --copy-raw

## Output layout

Typical output:

    manifest.json
    contract\
        shaders\
            shader.render_method_definition.xml
            ...render_method_option.xml
    fixtures\
        levels\solo\040_voi\...
        objects\...\shared_shader.shader.xml
        shaders\...\shared_shader.shader.xml
    raw_contract\        (only with --copy-raw)
    raw_fixtures\        (only with --copy-raw)
    baboon_json\         (when you use Baboon's bulk folder JSON dump)

Any stdout/stderr produced for an individual Tool invocation is stored next to that XML as `*.xml.log.txt`.

`manifest.json` also records referenced shader paths that Baboon named but that were not found in the H3EK tag tree.
