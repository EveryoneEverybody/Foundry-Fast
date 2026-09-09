# H3 shader packet helper

`h3_shader_packet.py` batch-exports Halo 3 shader evidence so H3 -> Reach material translation work does not require opening/dumping tags one at a time.

## What it gathers

By default it selects:

- `tags/shaders/shader.render_method_definition`
- every `*.render_method_option` under `tags/shaders/`
- every shader-family tag under `tags/levels/solo/040_voi/`

Shader-family tags include `.shader`, `.shader_custom`, `.shader_decal`, `.shader_foliage`, `.shader_fur`, `.shader_fur_stencil`, `.shader_glass`, `.shader_halogram`, `.shader_screen`, `.shader_terrain`, and `.shader_water`.

It invokes H3 `tool.exe export-tag-to-xml` for each selected tag, preserves the tag-relative directory layout in the output, records per-tag status in `manifest.json`, and can optionally copy the raw binary tags too.

This helper gathers evidence only. It deliberately does **not** translate H3 shader values into Reach values.

## First run: dry run

From the Foundry-Fast checkout:

    py tools\h3_shader_packet.py "D:\SteamLibrary\steamapps\common\H3EK" --dry-run

Replace the H3EK path with your actual Halo 3 Editing Kit directory.

The dry run creates the manifest and prints every selected tag without invoking Tool.

## Export the packet

    py tools\h3_shader_packet.py "D:\SteamLibrary\steamapps\common\H3EK" --output "D:\h3_shader_packet_040_voi"

To include the original binary tags as well:

    py tools\h3_shader_packet.py "D:\SteamLibrary\steamapps\common\H3EK" --output "D:\h3_shader_packet_040_voi" --copy-raw

## Another level/subtree

    py tools\h3_shader_packet.py "D:\SteamLibrary\steamapps\common\H3EK" --subtree "levels\solo\030_outskirts" --output "D:\h3_shader_packet_030"

## Output layout

Typical output:

    manifest.json
    contract\
        shaders\
            shader.render_method_definition.xml
            ...render_method_option.xml
    fixtures\
        levels\solo\040_voi\...
    raw_contract\        (only with --copy-raw)
    raw_fixtures\        (only with --copy-raw)

Any stdout/stderr produced for an individual Tool invocation is stored next to that XML as `*.xml.log.txt`.

## Scope limitation

The current helper finds shader tags physically stored under the selected level subtree. It does **not yet** follow the scenario's complete dependency graph to shared/object shaders outside that folder. The next step is to feed Baboon's dependency index into this collector so a scenario path such as `040_voi.scenario` yields the complete shader closure automatically.
