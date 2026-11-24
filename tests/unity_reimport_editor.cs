using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Animations;
using UnityEngine.Playables;

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
            try {
                CheckReimport();
                if (File.Exists(Path.Combine(Path.GetDirectoryName(Project), "vault.json"))) {
                    CheckContactUpdate();
                    StartVaultPlayback();
                }
            } catch (Exception error) { Debug.LogException(error); EditorApplication.Exit(1); throw; }
        }

        static void CheckReimport()
        {
            CheckTerrains();
            PackageImporter.Configure();
            CheckPbr(MaterialPath, .2f);
            CheckPbr(Root + "/LODs/LOD1/TS_Mat_000.mat", .8f);
            CheckPbr("Assets/LegacyFactors/TS_Mat_000.mat", .5f, 1f);
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
            CheckPbr(MaterialPath, .2f);
            CheckPbr(Root + "/LODs/LOD1/TS_Mat_000.mat", .8f);
            Debug.Log("TRELLIS MATERIAL PASS");
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

        [Serializable] class Anchor { public string name; public Vector3 point; }
        [Serializable] class Vault { public string clip,bone; public Anchor[] anchors; public Vector3 bind,target; public float[] interval; }

        static void CheckContactUpdate()
        {
            const string root="Assets/Vault", path=root+"/model.fbx";
            var importer=(ModelImporter)AssetImporter.GetAtPath(path);
            Assert(string.IsNullOrEmpty(importer.motionNodeName),"initial contact model has baked travel");
            var package=JsonUtility.FromJson<PackageImporter.Package>(File.ReadAllText(root+"/studio-export.json"));
            importer.motionNodeName=importer.transformPaths.Single(p=>p.EndsWith("/"+package.motion_root));
            importer.SaveAndReimport();
            try {
                var retained=importer.motionNodeName;
                var manifest=Path.Combine(Packages,"Vault","studio-export.json");
                try { PackageImporter.PreviewUpdate(root,manifest,PackageImporter.UpdateParts.Model,false); }
                catch (InvalidDataException error) when (error.Message.Contains("Root Motion Node")) {
                    Assert(importer.motionNodeName==retained,"artist root extraction preserved");
                    return;
                }
                throw new Exception("Incompatible contact update was accepted");
            } finally { importer.motionNodeName=""; importer.SaveAndReimport(); }
        }

        public static void StartVaultPlayback()
        {
            EditorSettings.enterPlayModeOptionsEnabled=true;
            EditorSettings.enterPlayModeOptions=EnterPlayModeOptions.DisableDomainReload;
            EditorApplication.update += VaultPlaybackUpdate;
            EditorApplication.EnterPlaymode();
        }

        static void VaultPlaybackUpdate()
        {
            if (!EditorApplication.isPlaying || !Application.isPlaying || EditorApplication.isCompiling) return;
            EditorApplication.update -= VaultPlaybackUpdate;
            try {
                var file=Path.Combine(Path.GetDirectoryName(Project), "vault.json");
                CheckVault(JsonUtility.FromJson<Vault>(File.ReadAllText(file)));
                EditorApplication.Exit(0);
            } catch (Exception error) { Debug.LogException(error); EditorApplication.Exit(1); }
        }

        static Matrix4x4 BindFrame(Vector3[] points)
        {
            var matrix=Matrix4x4.identity;
            for (int i=1;i<4;i++) matrix.SetColumn(i-1,points[i]-points[0]);
            var p=points[0];
            matrix.SetColumn(3,new Vector4(p.x,p.y,p.z,1f));
            Assert(Mathf.Abs(matrix.determinant)>.001f,"nondegenerate bind frame");
            return matrix;
        }

        static void CheckVault(Vault expected)
        {
            const string path="Assets/Vault/model.fbx";
            var instance=UnityEngine.Object.Instantiate(AssetDatabase.LoadAssetAtPath<GameObject>(path));
            try {
                var joints=instance.GetComponentsInChildren<Transform>(true).ToDictionary(t=>t.name,t=>t);
                var skin=instance.GetComponentsInChildren<SkinnedMeshRenderer>()
                    .First(r=>expected.anchors.All(a=>r.bones.Any(b=>b.name==a.name)));
                var bind=skin.bones.Select((bone,index)=>new {bone.name, matrix=skin.localToWorldMatrix*skin.sharedMesh.bindposes[index].inverse})
                    .ToDictionary(b=>b.name,b=>b.matrix);
                var basis=BindFrame(expected.anchors.Select(a=>(Vector3)bind[a.name].GetColumn(3)).ToArray()) *
                          BindFrame(expected.anchors.Select(a=>a.point).ToArray()).inverse;
                var hand=joints[expected.bone];
                var offset=bind[hand.name].inverse.MultiplyPoint3x4(basis.MultiplyPoint3x4(expected.bind));
                var target=basis.MultiplyPoint3x4(expected.target);
                var clip=AssetDatabase.LoadAllAssetsAtPath(path).OfType<AnimationClip>()
                    .Where(c=>!c.name.StartsWith("__preview__",StringComparison.Ordinal))
                    .Single(c=>c.name==expected.clip || c.name.EndsWith("|"+expected.clip));
                Assert(Mathf.Abs(clip.length-2f)<.01f,"retimed FBX duration");
                var animator=instance.GetComponent<Animator>();
                Assert(string.IsNullOrEmpty(((ModelImporter)AssetImporter.GetAtPath(path)).motionNodeName),
                       "contact clip keeps its authored skeleton travel");
                animator.applyRootMotion=true;
                animator.cullingMode=AnimatorCullingMode.AlwaysAnimate;
                var graph=PlayableGraph.Create("TRELLIS vault QA");
                float worst=0; Vector3 sample=Vector3.zero;
                try {
                    graph.SetTimeUpdateMode(DirectorUpdateMode.Manual);
                    var playable=AnimationClipPlayable.Create(graph,clip);
                    AnimationPlayableOutput.Create(graph,"Vault",animator).SetSourcePlayable(playable);
                    graph.Play();
                    graph.Evaluate(0);
                    for(int frame=1;frame<=Mathf.FloorToInt(expected.interval[1]*192);frame++) {
                        graph.Evaluate(1f/192);
                        if (frame/192f < expected.interval[0]) continue;
                        sample=hand.TransformPoint(offset);
                        worst=Mathf.Max(worst,Vector3.Distance(sample,target));
                    }
                } finally { graph.Destroy(); }
                Debug.Log("TRELLIS vault measurement: root path "+((ModelImporter)AssetImporter.GetAtPath(path)).motionNodeName+" actor="+animator.transform.position+" sample="+sample+" target="+target);
                Assert(worst<.045f,"palm on crate in retimed Unity animation, maximum error (m) "+worst+" target="+target+" palm="+sample+" bind axis scales="+basis.lossyScale);
                Debug.Log("TRELLIS VAULT PASS, maximum palm error (m) "+worst);
            } finally { UnityEngine.Object.DestroyImmediate(instance); }
        }

        static void CheckPbr(string path, float cutoff, float strength=.34f)
        {
            var material = AssetDatabase.LoadAssetAtPath<Material>(path);
            Assert(Mathf.Abs(material.GetFloat("_Cutoff")-cutoff)<1e-5f &&
                material.IsKeywordEnabled("_ALPHATEST_ON") && material.renderQueue==2450, "MASK cutoff and alpha test");
            Assert(Mathf.Abs(material.GetFloat("_OcclusionStrength")-strength)<1e-5f &&
                material.IsKeywordEnabled("_OCCLUSIONMAP"), "occlusion strength and keyword");
            string texturePath = AssetDatabase.GetAssetPath(material.GetTexture("_OcclusionMap"));
            var importer = (TextureImporter)AssetImporter.GetAtPath(texturePath);
            Assert(!importer.sRGBTexture && importer.swizzleG == TextureImporterSwizzle.R, "linear red-to-green occlusion");
            importer.isReadable = true;
            importer.textureCompression = TextureImporterCompression.Uncompressed;
            importer.SaveAndReimport();
            Color pixel = AssetDatabase.LoadAssetAtPath<Texture2D>(texturePath).GetPixel(0,0);
            Assert(Mathf.Abs(pixel.g - 39f/255) < .01f, "actual imported green reads glTF occlusion");
        }

        static void CheckTerrains()
        {
            const string prefix = "Assets/Terrains/";
            string Manifest(string name) => prefix+name+"/terrain-manifest.json";
            void SelectTerrain(string name) => Selection.activeObject=AssetDatabase.LoadMainAssetAtPath(Manifest(name));
            string Data(string name) => prefix+name+"/"+name+"-TerrainData.asset";
            SelectTerrain("A"); TrellisLocal.Editor.TrellisTerrainImporter.ImportAll();
            SelectTerrain("B"); TrellisLocal.Editor.TrellisTerrainImporter.ImportAll();
            Assert(!File.Exists(Data("C")), "only selected terrain imported");
            var a=AssetDatabase.LoadAssetAtPath<TerrainData>(Data("A"));
            a.SetHeights(0,0,new float[,]{{.45f}});
            a.SetAlphamaps(0,0,new float[,,]{{{0f,1f,0f}}});
            var layer=a.terrainLayers[0];
            layer.tileSize=new Vector2(13,13); EditorUtility.SetDirty(layer); EditorUtility.SetDirty(a);
            string prefab=prefix+"A/A.prefab";
            var contents=PrefabUtility.LoadPrefabContents(prefab);
            new GameObject("Artist edit").transform.SetParent(contents.transform,false);
            PrefabUtility.SaveAsPrefabAsset(contents,prefab); PrefabUtility.UnloadPrefabContents(contents);
            AssetDatabase.SaveAssets();
            var previous=new[]{Data("A"),prefab,prefix+"A/Soil.terrainlayer",Data("B")}.ToDictionary(p=>p,Bytes);
            SelectTerrain("C"); TrellisLocal.Editor.TrellisTerrainImporter.ImportAll();
            SelectTerrain("A"); TrellisLocal.Editor.TrellisTerrainImporter.ImportAll();
            Assert(File.Exists(Data("C")) && previous.All(item=>Bytes(item.Key).SequenceEqual(item.Value)), "sculpt, paint, layer and prefab survived");
            TrellisLocal.Editor.TrellisTerrainImporter.CreateTerrain(Manifest("A"),true);
            Assert(a.GetHeight(0,0)<.001f && a.GetAlphamaps(0,0,1,1)[0,0,0]>.99f &&
                layer.tileSize==new Vector2(6,6) && AssetDatabase.LoadAssetAtPath<GameObject>(prefab).transform.Find("Artist edit")==null,
                "explicit rebuild of selected terrain");
            Assert(Bytes(Data("B")).SequenceEqual(previous[Data("B")]),"rebuild isolated from other terrains");
            Debug.Log("TRELLIS TERRAIN PASS");
        }

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
