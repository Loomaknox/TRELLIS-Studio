using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace TrellisStudio
{
    public static class ReimportRegression
    {
        const string Root = "Assets/Installed";
        const string Model = Root + "/model.fbx";
        const string MaterialPath = Root + "/TS_Mat_000.mat";
        const string TexturePath = Root + "/Textures/TS_Mat_000_BaseColor.png";
        const string Wrapper = Root + "/StudioAsset.prefab";
        const string Lod = Root + "/LODs/LOD1/model.fbx";
        static readonly string Project = Path.GetFullPath(Path.Combine(Application.dataPath, ".."));
        static readonly string Packages = Path.Combine(Path.GetDirectoryName(Project), "packages");

        public static void Run()
        {
            PackageImporter.Configure();
            var crouch = Path.Combine(Path.GetDirectoryName(Project), "crouch.json");
            if (File.Exists(crouch)) CheckCharacter(JsonUtility.FromJson<Character>(File.ReadAllText(crouch)));
            var custom = AssetDatabase.LoadAssetAtPath<Material>(MaterialPath);
            Assert(custom != null, "initial configure creates a material");
            custom.color = Color.magenta;
            EditorUtility.SetDirty(custom);
            const string RemapPath = "Assets/ArtistRemap.mat";
            var remap = new Material(custom) { color = Color.cyan };
            AssetDatabase.CreateAsset(remap, RemapPath);
            var slot = new AssetImporter.SourceAssetIdentifier(typeof(Material), "TS_Mat_000");
            var importer = (ModelImporter)AssetImporter.GetAtPath(Model);
            importer.AddRemap(slot, remap);
            importer.globalScale = 1.25f;
            importer.SaveAndReimport();
            var wrapper = PrefabUtility.LoadPrefabContents(Wrapper);
            Assert(wrapper.GetComponent<LODGroup>().lodCount == 2, "legacy export configures both LOD levels");
            Assert(AssetDatabase.LoadAssetAtPath<Material>(Root + "/LODs/LOD1/TS_Mat_000.mat") != null, "legacy detail material is configured");
            new GameObject("Hand-authored part").transform.SetParent(wrapper.transform, false);
            PrefabUtility.SaveAsPrefabAsset(wrapper, Wrapper);
            PrefabUtility.UnloadPrefabContents(wrapper);
            AssetDatabase.SaveAssets();

            var mesh = AssetDatabase.LoadAllAssetsAtPath(Model).OfType<Mesh>().First();
            var bounds = mesh.bounds.size.x;
            var materialGuid = AssetDatabase.AssetPathToGUID(MaterialPath);
            var textureGuid = AssetDatabase.AssetPathToGUID(TexturePath);
            var modelGuid = AssetDatabase.AssetPathToGUID(Model);
            var modelMeta = Bytes(Model + ".meta");
            var prefabBytes = Bytes(Wrapper);
            var originalTexture = Bytes(TexturePath);
            var originalLod = Bytes(Lod);
            var lodGuid = AssetDatabase.AssetPathToGUID(Lod);
            Assert(AssetDatabase.TryGetGUIDAndLocalFileIdentifier(mesh, out string _, out long meshId), "initial mesh identifier");
            const string Use = "Assets/UsesImportedMesh.prefab";
            var use = new GameObject("Uses installed model");
            use.AddComponent<MeshFilter>().sharedMesh = mesh;
            use.AddComponent<MeshRenderer>().sharedMaterial = custom;
            PrefabUtility.SaveAsPrefabAsset(use, Use);
            UnityEngine.Object.DestroyImmediate(use);

            // The original Configure action is idempotent after manual edits.
            PackageImporter.Configure();
            Assert(AssetDatabase.LoadAssetAtPath<Material>(MaterialPath).color == Color.magenta, "configure preserves colour");
            Assert(Bytes(Wrapper).SequenceEqual(prefabBytes), "configure preserves wrapper edits");
            Assert(((ModelImporter)AssetImporter.GetAtPath(Model)).GetExternalObjectMap()[slot] == remap, "configure preserves custom remap");
            string updated = Path.Combine(Packages, "Updated", "studio-export.json");
            Expect<InvalidDataException>(() => PackageImporter.PreviewUpdate(Root, updated, PackageImporter.UpdateParts.Model, false));
            var modelPlan = PackageImporter.PreviewUpdate(Root, updated, PackageImporter.UpdateParts.Model, true);
            Assert(modelPlan.Files.Count == 1 && modelPlan.Files[0].AssetPath == Model, "geometry-only preview");
            var incomingModel = modelPlan.Files[0].Source;
            var beforeChange = File.ReadAllBytes(incomingModel);
            File.AppendAllText(incomingModel, "changed after preview");
            Expect<IOException>(() => PackageImporter.ApplyUpdate(modelPlan));
            File.WriteAllBytes(incomingModel, beforeChange);
            PackageImporter.ApplyUpdate(modelPlan);
            Assert(AssetDatabase.AssetPathToGUID(Model) == modelGuid, "FBX GUID survived");
            Assert(Bytes(Model + ".meta").SequenceEqual(modelMeta), "FBX .meta survived");
            Assert(((ModelImporter)AssetImporter.GetAtPath(Model)).globalScale == 1.25f, "custom import scale survived");
            Assert(((ModelImporter)AssetImporter.GetAtPath(Model)).GetExternalObjectMap()[slot] == remap, "custom remap survived");
            Assert(Bytes(TexturePath).SequenceEqual(originalTexture), "geometry-only update keeps the texture bytes");
            Assert(Bytes(Lod).SequenceEqual(originalLod), "geometry-only update keeps the LOD file");
            Assert(Bytes(Wrapper).SequenceEqual(prefabBytes), "hand-edited wrapper survived");
            var used = AssetDatabase.LoadAssetAtPath<GameObject>(Use);
            var updatedMesh = used.GetComponent<MeshFilter>().sharedMesh;
            Assert(updatedMesh != null && updatedMesh.bounds.size.x > bounds * 1.5f, "prefab reference sees the changed geometry");
            Assert(AssetDatabase.TryGetGUIDAndLocalFileIdentifier(updatedMesh, out string newGuid, out long newMeshId) &&
                newGuid == modelGuid && newMeshId == meshId, "mesh local id survived");
            Assert(AssetDatabase.AssetPathToGUID(MaterialPath) == materialGuid &&
                used.GetComponent<MeshRenderer>().sharedMaterial.color == Color.magenta, "custom material survived");

            var textures = PackageImporter.PreviewUpdate(Root, updated, PackageImporter.UpdateParts.Textures, true);
            Assert(textures.Files.Count == 2 && textures.Files[0].AssetPath == TexturePath &&
                textures.Files.All(file => file.AssetPath.EndsWith(".png")), "textures-only preview covers root and LOD");
            PackageImporter.ApplyUpdate(textures);
            Assert(!Bytes(TexturePath).SequenceEqual(originalTexture) &&
                AssetDatabase.AssetPathToGUID(TexturePath) == textureGuid, "texture bytes changed, GUID kept");
            Assert(AssetDatabase.LoadAssetAtPath<Material>(MaterialPath).color == Color.magenta, "texture update preserves material parameters");
            var auxiliary = PackageImporter.PreviewUpdate(Root, updated, PackageImporter.UpdateParts.AuxiliaryModels, true);
            Assert(auxiliary.Files.Count == 1 && auxiliary.Files[0].AssetPath == Lod, "LOD-only preview");
            PackageImporter.ApplyUpdate(auxiliary);
            Assert(!Bytes(Lod).SequenceEqual(originalLod) && AssetDatabase.AssetPathToGUID(Lod) == lodGuid &&
                Bytes(Wrapper).SequenceEqual(prefabBytes), "LOD update keeps GUID and wrapper");
            var stableModel = Bytes(Model);
            var incompatible = PackageImporter.PreviewUpdate(Root, Path.Combine(Packages, "Incompatible", "studio-export.json"),
                PackageImporter.UpdateParts.Model, true);
            Expect<InvalidDataException>(() => PackageImporter.ApplyUpdate(incompatible));
            Assert(Bytes(Model).SequenceEqual(stableModel) && Bytes(Model + ".meta").SequenceEqual(modelMeta), "failed update restores bytes and .meta");
            Assert(AssetDatabase.LoadAssetAtPath<GameObject>(Use).GetComponent<MeshFilter>().sharedMesh != null, "references survive rollback");
            Debug.Log("TRELLIS REIMPORT PASS");
        }

        [Serializable] class Clip { public string name; public float duration; }
        [Serializable] class Surface { public string name, albedo; }
        [Serializable] class Character {
            public string[] bones, ankles, hips, knees;
            public Clip[] clips;
            public Surface[] surfaces;
            public float height;
        }

        static void CheckCharacter(Character expected)
        {
            const string path = "Assets/Crouch/model.fbx";
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            Assert(model != null, "animated FBX import");
            var importer = (ModelImporter)AssetImporter.GetAtPath(path);
            Assert(importer.animationType == ModelImporterAnimationType.Generic, "Generic rig");
            var remaps = importer.GetExternalObjectMap();
            foreach (var surface in expected.surfaces) {
                var slot = new AssetImporter.SourceAssetIdentifier(typeof(Material), surface.name);
                Assert(remaps.TryGetValue(slot, out var asset) && asset is Material, "material " + surface.name);
                if (!string.IsNullOrEmpty(surface.albedo)) {
                    var mat = (Material)asset;
                    var texture = mat.GetTexture(mat.HasProperty("_BaseMap") ? "_BaseMap" : "_MainTex");
                    Assert(AssetDatabase.GetAssetPath(texture) == "Assets/Crouch/" + surface.albedo, "albedo " + surface.name);
                }
            }
            var instance = UnityEngine.Object.Instantiate(model);
            try {
                var transforms = instance.GetComponentsInChildren<Transform>(true);
                Transform Joint(string name) => transforms.First(joint => joint.name == name);
                Assert(expected.bones.All(name => transforms.Any(joint => joint.name == name)), "all source joints imported");
                var renderers = instance.GetComponentsInChildren<SkinnedMeshRenderer>();
                Assert(renderers.Length > 0 && renderers.All(r => r.sharedMaterials.All(m => m != null)), "skinned materials");
                float low = float.PositiveInfinity, high = float.NegativeInfinity;
                foreach (var renderer in renderers) {
                    // Mesh vertices are in bind space. Renderer bounds include animation
                    // excursions, and BakeMesh measures the instance's current pose.
                    foreach (var point in renderer.sharedMesh.vertices) {
                        float y = renderer.transform.TransformPoint(point).y;
                        low = Math.Min(low, y);
                        high = Math.Max(high, y);
                    }
                }
                Assert(Math.Abs(high - low - expected.height) < expected.height * .02f,
                    $"bind height {high-low:F4} m, expected {expected.height:F4} m");
                var clips = AssetDatabase.LoadAllAssetsAtPath(path).OfType<AnimationClip>()
                    .Where(c => !c.name.StartsWith("__preview__", StringComparison.Ordinal)).ToArray();
                foreach (var recipe in expected.clips) {
                    var matches = clips.Where(c => c.name == recipe.name || c.name.EndsWith("|" + recipe.name)).ToArray();
                    Assert(matches.Length == 1, "one imported take for " + recipe.name + " in " + string.Join(", ", clips.Select(c => c.name)));
                    var clip = matches[0];
                    Assert(Math.Abs(clip.length - recipe.duration) < .06f, "source clip duration");
                    if (!recipe.name.ToLowerInvariant().Contains("crouch")) continue;
                    clip.SampleAnimation(instance, 0);
                    var anchors = expected.ankles.Select(name => Joint(name).position).ToArray();
                    foreach (var seconds in new[] { .1f, 43f/60, 1.5f, 137f/60, clip.length }) {
                        clip.SampleAnimation(instance, seconds);
                        for (int side = 0; side < anchors.Length; side++) {
                            Assert(Vector3.Distance(anchors[side], Joint(expected.ankles[side]).position) < .01f,
                                "planted ankle at " + seconds);
                            Assert(Joint(expected.knees[side]).position.y < Joint(expected.hips[side]).position.y + .03f,
                                "knee below hip at " + seconds);
                        }
                    }
                }
                Debug.Log("TRELLIS CHARACTER PASS");
            } finally { UnityEngine.Object.DestroyImmediate(instance); }
        }

        static byte[] Bytes(string path) => File.ReadAllBytes(Path.Combine(Project, path));

        static void Assert(bool condition, string message)
        {
            if (!condition) throw new Exception("Unity reimport regression: " + message);
        }

        static void Expect<T>(Action act) where T : Exception
        {
            try { act(); }
            catch (T) { return; }
            throw new Exception("Unity reimport regression expected " + typeof(T).Name);
        }
    }
}
