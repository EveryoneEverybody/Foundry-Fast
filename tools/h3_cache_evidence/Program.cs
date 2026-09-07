// Read-only diagnostic, separate from native authoring. Never exports tags/pixels.
using Reclaimer.Blam.Common;
using Reclaimer.Blam.Halo3;
using System.Security.Cryptography;
using System.Text.Json;
using System.IO;

if (args.Length < 2)
    throw new ArgumentException("Usage: H3CacheEvidence request.json stock_h3.map [stock_h3.map ...]");
using var request = JsonDocument.Parse(File.ReadAllText(args[0]));
if (request.RootElement.GetProperty("version").GetInt32() != 1)
    throw new InvalidDataException("Unsupported evidence request version");
static string Identity(string path) => path.Replace('\\', '/').ToLowerInvariant();
var requestedShaders = request.RootElement.GetProperty("shaders").EnumerateArray()
    .Select(v => Identity(v.GetString()!)).ToHashSet();
var requestedBitmaps = request.RootElement.GetProperty("bitmaps").EnumerateArray()
    .Select(v => Identity(v.GetString()!)).ToHashSet();
var results = new List<object>();
foreach (var file in args.Skip(1))
{
    // Reclaimer CacheFactory opens cache streams with FileAccess.Read.
    var cache = CacheFactory.ReadCacheFile(file);
    if (!cache.CacheType.ToString().Contains("Halo3", StringComparison.Ordinal))
        throw new InvalidDataException("Only H3 cache evidence is supported");
    var tags = cache.TagIndex.ToList();
    var shaders = new List<object>();
    foreach (var item in tags.Where(t => t.ClassCode == "rmsh" && requestedShaders.Contains(Identity(t.TagName) + ".shader")))
    {
        var shader = item.ReadMetadata<ShaderTag>();
        var definition = shader.RenderMethodDefinitionReference.Tag.ReadMetadata<RenderMethodDefinitionTag>();
        if (definition.Categories.Count != shader.ShaderOptions.Count)
            throw new InvalidDataException("Cannot infer missing shader option selections");
        var categories = definition.Categories.Select((c, i) => new {
            name = c.Name.ToString(), index = shader.ShaderOptions[i].OptionIndex,
            option = c.Options[shader.ShaderOptions[i].OptionIndex].Name.ToString()
        }).ToArray();
        var properties = new List<object>();
        foreach (var props in shader.ShaderProperties)
        {
            var template = props.TemplateReference.Tag.ReadMetadata<RenderMethodTemplateTag>();
            if (template.Usages.Count != props.ShaderMaps.Count || template.Arguments.Count != props.TilingData.Count)
                throw new InvalidDataException("Template sampler/constant cardinality differs; cannot infer bindings");
            properties.Add(new {
                template = props.TemplateReference.Tag.TagName,
                samplers = props.ShaderMaps.Select((m, i) => new {
                    index = i, usage = template.Usages[i].ToString(), valid = m.BitmapReference.IsValid,
                    bitmap = m.BitmapReference.Tag?.TagName, group = m.BitmapReference.Tag?.ClassCode,
                    bitmap_tag_id = m.BitmapReference.TagId, tiling_index = m.TilingIndex
                }).ToArray(),
                arguments = template.Arguments.Select((s, i) => new { index = i, name = s.ToString() }).ToArray(),
                constants = props.TilingData.Select(v => new[] { v.X, v.Y, v.Z, v.W }).ToArray()
            });
        }
        shaders.Add(new { name = item.TagName, id = item.Id, offset = item.MetaPointer.Address, categories, properties });
    }
    using var stream = new FileStream(file, FileMode.Open, FileAccess.Read, FileShare.Read);
    results.Add(new {
        source_kind = "retail_cache",
        cache = Path.GetFullPath(file), sha256 = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant(),
        bytes = stream.Length, cache_type = cache.CacheType.ToString(), build = cache.BuildString,
        scenario = cache.TagIndex.GetGlobalTag("scnr").TagName,
        reader = new { name = "Reclaimer", commit = "6209415badf398a17a895d4d726b67eea850c67f", mode = "read-only" },
        tag_count = tags.Count,
        bitmap_queries = requestedBitmaps.Order().Select(name => new {
            source = name, matches = tags.Where(t => t.ClassCode == "bitm" && Identity(t.TagName) + ".bitmap" == name)
                .Select(t => new { name = t.TagName, id = t.Id }).ToArray()
        }).ToArray(),
        shaders, policy = "Metadata evidence only; no tag/pixel output or compiled runtime resource copying"
    });
}
Console.WriteLine(JsonSerializer.Serialize(results, new JsonSerializerOptions { WriteIndented = true }));
