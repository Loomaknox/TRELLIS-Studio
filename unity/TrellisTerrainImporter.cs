#if UNITY_EDITOR
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

namespace TrellisLocal.Editor
{
    public static class TrellisTerrainImporter
    {
        [Serializable] public class Manifest
        {
            public string name, raw;
            public int resolution, seed;
            public float size_m, height_m;
        }

        const string ManifestName = "terrain-manifest.json";
        const string RebuildMenu = "Tools/TRELLIS/Rebuild selected terrain from source...";
        static readonly string[] LayerNames = { "Soil", "Rock", "Grass" };

        static string[] SelectedManifests()
        {
            return Selection.objects.Select(AssetDatabase.GetAssetPath)
                .Select(path => AssetDatabase.IsValidFolder(path) ? path + "/" + ManifestName : path)
                .Where(path => path.StartsWith("Assets/", StringComparison.Ordinal) &&
                    Path.GetFileName(path) == ManifestName && File.Exists(path))
                .Distinct().ToArray();
        }

        [MenuItem("Tools/TRELLIS/Import Unity terrains")]
        public static void ImportAll()
        {
            var selected = SelectedManifests();
            if (selected.Length == 0)
                Debug.Log("TRELLIS: Select a terrain-manifest.json or its containing folder in the Project window.");
            foreach (var manifest in selected) CreateTerrain(manifest);
        }

        [MenuItem(RebuildMenu, true)]
        static bool CanRebuild() => SelectedManifests().Length == 1;

        [MenuItem(RebuildMenu)]
        static void Rebuild()
        {
            var selected = SelectedManifests();
            if (selected.Length == 1 && EditorUtility.DisplayDialog("Rebuild selected TRELLIS terrain?",
                selected[0] + "\n\nReplace the sculpted heights, painted weights, layer settings and prefab from this source? " +
                "Back up any edits you want to keep before rebuilding.", "Rebuild this terrain", "Cancel"))
                CreateTerrain(selected[0], true);
        }

        public static string CreateTerrain(string manifestPath) => CreateTerrain(manifestPath, false);

        public static string CreateTerrain(string manifestPath, bool rebuild)
        {
            var info=JsonUtility.FromJson<Manifest>(File.ReadAllText(manifestPath));
            string folder=Path.GetDirectoryName(manifestPath).Replace('\\','/');
            if ((folder != "Assets" && !folder.StartsWith("Assets/", StringComparison.Ordinal)) || info == null ||
                !LocalFilename(info.name) || !LocalFilename(info.raw) || info.resolution < 33 ||
                info.resolution > 4097 || !Mathf.IsPowerOfTwo(info.resolution - 1) ||
                !(info.size_m > 0 && info.height_m > 0))
                throw new InvalidDataException("Invalid TRELLIS terrain manifest.");
            string dataPath=folder+"/"+info.name+"-TerrainData.asset";
            string prefab=folder+"/"+info.name+".prefab";
            string matPath=folder+"/"+info.name+"-Terrain.mat";
            if (!rebuild && (File.Exists(dataPath) || File.Exists(prefab) || File.Exists(matPath) ||
                LayerNames.Any(name => File.Exists(folder+"/"+name+".terrainlayer"))))
            {
                Debug.Log("TRELLIS: Skipped existing terrain in "+folder+". Use Rebuild selected terrain from source to replace local edits.");
                return File.Exists(prefab) ? prefab : null;
            }
            var bytes=File.ReadAllBytes(folder+"/"+info.raw);
            if(bytes.Length != info.resolution*info.resolution*2) throw new InvalidDataException("Incomplete RAW heightmap.");
            foreach (string name in LayerNames.SelectMany(layer => new[] {layer+".png",layer+"Normal.png"}).Append("Splatmap.png"))
                if (AssetDatabase.LoadAssetAtPath<Texture2D>(folder+"/"+name) == null)
                    throw new InvalidDataException("Missing or unreadable terrain texture: "+name);
            var heights=new float[info.resolution,info.resolution];
            for(int z=0;z<info.resolution;z++) for(int x=0;x<info.resolution;x++)
            { int i=2*(z*info.resolution+x); heights[z,x]=(bytes[i]|bytes[i+1]<<8)/65535f; }
            var data=AssetDatabase.LoadAssetAtPath<TerrainData>(dataPath);
            if(data==null) { data=new TerrainData(); AssetDatabase.CreateAsset(data,dataPath); }
            data.heightmapResolution=info.resolution;
            data.size=new Vector3(info.size_m,info.height_m,info.size_m);
            data.SetHeights(0,0,heights);
            var layerNames=LayerNames;
            var layers=new TerrainLayer[3];
            for(int i=0;i<3;i++)
            {
                string layerPath=folder+"/"+layerNames[i]+".terrainlayer";
                var layer=AssetDatabase.LoadAssetAtPath<TerrainLayer>(layerPath);
                if(layer==null) { layer=new TerrainLayer(); AssetDatabase.CreateAsset(layer,layerPath); }
                layer.diffuseTexture=LoadTexture(folder+"/"+layerNames[i]+".png",true,false);
                layer.normalMapTexture=LoadTexture(folder+"/"+layerNames[i]+"Normal.png",false,false,true);
                layer.tileSize=new Vector2(6,6); layer.smoothness=.05f; layer.metallic=0;
                layers[i]=layer; EditorUtility.SetDirty(layer); AssetDatabase.SaveAssetIfDirty(layer);
            }
            data.terrainLayers=layers;
            data.alphamapResolution=256;
            var splat=LoadTexture(folder+"/Splatmap.png",false,true);
            var alpha=new float[256,256,3];
            for(int z=0;z<256;z++) for(int x=0;x<256;x++)
            {
                Color c=splat.GetPixelBilinear(x/255f,1-z/255f);
                float total=Mathf.Max(c.r+c.g+c.b,.001f);
                alpha[z,x,0]=c.r/total;alpha[z,x,1]=c.g/total;alpha[z,x,2]=c.b/total;
            }
            data.SetAlphamaps(0,0,alpha);
            var root=Terrain.CreateTerrainGameObject(data);
            try
            {
                root.name=info.name;
                var terrain=root.GetComponent<Terrain>();
                var shader=Shader.Find("Universal Render Pipeline/Terrain/Lit");
                if(shader!=null)
                {
                    var mat=AssetDatabase.LoadAssetAtPath<Material>(matPath);
                    if(mat==null) {mat=new Material(shader);AssetDatabase.CreateAsset(mat,matPath);}
                    terrain.materialTemplate=mat;
                }
                terrain.drawInstanced=true;
                terrain.heightmapPixelError=5;
                PrefabUtility.SaveAsPrefabAsset(root,prefab);
                EditorUtility.SetDirty(data);AssetDatabase.SaveAssetIfDirty(data);return prefab;
            }
            finally { UnityEngine.Object.DestroyImmediate(root); }
        }

        static bool LocalFilename(string name) => !string.IsNullOrWhiteSpace(name) && name != "." && name != ".." &&
            name.IndexOfAny(Path.GetInvalidFileNameChars()) < 0 && !name.Contains("/") && !name.Contains("\\");

        static Texture2D LoadTexture(string path,bool srgb,bool readable,bool normal=false)
        {
            AssetDatabase.ImportAsset(path,ImportAssetOptions.ForceSynchronousImport);
            var importer=AssetImporter.GetAtPath(path) as TextureImporter;
            if(importer!=null)
            { importer.textureType=normal?TextureImporterType.NormalMap:TextureImporterType.Default;
              importer.sRGBTexture=srgb;importer.isReadable=readable;importer.wrapMode=readable?TextureWrapMode.Clamp:TextureWrapMode.Repeat;
              importer.textureCompression=TextureImporterCompression.Uncompressed;importer.SaveAndReimport(); }
            return AssetDatabase.LoadAssetAtPath<Texture2D>(path);
        }
    }
}
#endif
