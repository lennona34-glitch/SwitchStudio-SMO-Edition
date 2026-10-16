using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Syroot.NintenTools.NSW.Bfres;
using Syroot.NintenTools.NSW.Bntx;
using Toolbox.Library;

// ExportModel.exe <in.bfres> <out_dir> [modelIndex]
//   out_dir/model.json   real geometry (positions/normals/uvs/indices per shape, bone-space applied), materials, bones
//   out_dir/<tex>.dds    every *_alb texture of the file (mip 0, linear BC1/BC3)
class Program
{
    static CultureInfo C = CultureInfo.InvariantCulture;

    static double[] Ident() { return new double[] { 1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1 }; }
    static double[] Mul(double[] a, double[] b)
    {
        var r = new double[16];
        for (int i = 0; i < 4; i++)
            for (int j = 0; j < 4; j++)
            {
                double s = 0;
                for (int k = 0; k < 4; k++) s += a[i * 4 + k] * b[k * 4 + j];
                r[i * 4 + j] = s;
            }
        return r;
    }
    static double[] Trans(double x, double y, double z) { var m = Ident(); m[3] = x; m[7] = y; m[11] = z; return m; }
    static double[] Scale(double x, double y, double z) { var m = Ident(); m[0] = x; m[5] = y; m[10] = z; return m; }
    static double[] RotX(double a) { var m = Ident(); double c = Math.Cos(a), s = Math.Sin(a); m[5] = c; m[6] = -s; m[9] = s; m[10] = c; return m; }
    static double[] RotY(double a) { var m = Ident(); double c = Math.Cos(a), s = Math.Sin(a); m[0] = c; m[2] = s; m[8] = -s; m[10] = c; return m; }
    static double[] RotZ(double a) { var m = Ident(); double c = Math.Cos(a), s = Math.Sin(a); m[0] = c; m[1] = -s; m[4] = s; m[5] = c; return m; }
    static double[] RotQ(double x, double y, double z, double w)
    {
        double n = Math.Sqrt(x * x + y * y + z * z + w * w); if (n < 1e-12) return Ident();
        x /= n; y /= n; z /= n; w /= n;
        var m = Ident();
        m[0] = 1 - 2 * (y * y + z * z); m[1] = 2 * (x * y - z * w);     m[2] = 2 * (x * z + y * w);
        m[4] = 2 * (x * y + z * w);     m[5] = 1 - 2 * (x * x + z * z); m[6] = 2 * (y * z - x * w);
        m[8] = 2 * (x * z - y * w);     m[9] = 2 * (y * z + x * w);     m[10] = 1 - 2 * (x * x + y * y);
        return m;
    }

    static double[] BoneLocal(Bone b)
    {
        double rx = b.Rotation.X, ry = b.Rotation.Y, rz = b.Rotation.Z, rw = b.Rotation.W;
        double[] R = b.FlagsRotation == BoneFlagsRotation.Quaternion
            ? RotQ(rx, ry, rz, rw)
            : Mul(RotZ(rz), Mul(RotY(ry), RotX(rx)));
        return Mul(Trans(b.Position.X, b.Position.Y, b.Position.Z), Mul(R, Scale(b.Scale.X, b.Scale.Y, b.Scale.Z)));
    }

    static string F(double v) { return v.ToString("0.#####", C); }

    static double Half(ushort h)
    {
        int sgn = (h >> 15) & 1, e = (h >> 10) & 0x1f, f = h & 0x3ff;
        double v;
        if (e == 0) v = f * Math.Pow(2, -24);
        else if (e == 31) v = f == 0 ? double.PositiveInfinity : double.NaN;
        else v = (1 + f / 1024.0) * Math.Pow(2, e - 15);
        return sgn == 1 ? -v : v;
    }

    // Decodes one attribute of vertex v into up to 4 components. Returns the component count.
    static int ReadAttr(VertexBuffer vb, string name, int v, double[] o)
    {
        VertexAttrib a = null;
        foreach (var x in vb.Attributes) if (x.Name == name) { a = x; break; }
        if (a == null) return 0;
        byte[] d = vb.Buffers[a.BufferIndex].Data;
        int stride = (int)vb.StrideArray[a.BufferIndex].Stride;
        int p = v * stride + a.Offset;
        string f = a.Format.ToString();   // Format_16_16_UNorm, Format_10_10_10_2_SNorm, ...
        var parts = f.Substring(7).Split('_');
        string kind = parts[parts.Length - 1];
        if (f.StartsWith("Format_10_10_10_2"))
        {
            uint w = BitConverter.ToUInt32(d, p);
            for (int i = 0; i < 3; i++)
            {
                int raw = (int)((w >> (10 * i)) & 0x3ff); if (raw >= 512) raw -= 1024;
                o[i] = Math.Max(-1.0, raw / 511.0);
            }
            o[3] = 0; return 3;
        }
        int bits = int.Parse(parts[0]); int n = parts.Length - 1;
        for (int i = 0; i < n && i < 4; i++)
        {
            double val;
            if (bits == 32 && kind == "Single") val = BitConverter.ToSingle(d, p + 4 * i);
            else if (bits == 16)
            {
                ushort u = BitConverter.ToUInt16(d, p + 2 * i);
                if (kind == "Single") val = Half(u);
                else if (kind == "UNorm") val = u / 65535.0;
                else if (kind == "SNorm") val = Math.Max(-1.0, (short)u / 32767.0);
                else if (kind == "UInt") val = u; else val = (short)u;
            }
            else
            {
                byte u = d[p + i];
                if (kind == "UNorm") val = u / 255.0;
                else if (kind == "SNorm") val = Math.Max(-1.0, (sbyte)u / 127.0);
                else if (kind == "UInt") val = u; else val = (sbyte)u;
            }
            o[i] = val;
        }
        return n;
    }

    static void Main(string[] args)
    {
        if (args.Length < 2) { Console.WriteLine("Usage: ExportModel.exe <in.bfres> <out_dir> [modelIndex]"); return; }
        string path = args[0], outDir = args[1];
        int modelIndex = args.Length > 2 ? int.Parse(args[2]) : 0;
        Directory.CreateDirectory(outDir);

        ResFile res = new ResFile(path);
        var sb = new StringBuilder();
        sb.Append("{\"file\":\"" + Path.GetFileName(path) + "\",\"models\":[");

        // ---- textures --------------------------------------------------------------------------------------
        var texInfo = new List<string>();
        if (res.ExternalFiles != null && res.ExternalFiles.Count > 0)
        {
            using (var ms = new MemoryStream(res.ExternalFiles[0].Data))
            {
                BntxFile bntx = new BntxFile(ms);
                foreach (var tex in bntx.Textures)
                {
                    texInfo.Add("{\"name\":\"" + tex.Name + "\",\"w\":" + tex.Width + ",\"h\":" + tex.Height + ",\"fmt\":\"" + tex.Format + "\"}");
                    if (!tex.Name.EndsWith("_alb", StringComparison.OrdinalIgnoreCase)) continue;
                    string fmt = tex.Format.ToString();
                    bool bc1 = fmt.Contains("BC1"), bc3 = fmt.Contains("BC3");
                    if (!bc1 && !bc3) continue;
                    uint bpp = bc1 ? 8u : 16u;
                    byte[] raw = tex.TextureData[0][0];
                    byte[] lin = TegraX1Swizzle.deswizzle(tex.Width, tex.Height, 1, 4, 4, 1, 0, bpp, (uint)tex.TileMode, (int)tex.BlockHeightLog2, raw);
                    using (var bw = new BinaryWriter(File.Create(Path.Combine(outDir, tex.Name + ".dds"))))
                    {
                        bw.Write(new char[] { 'D', 'D', 'S', ' ' }); bw.Write(124);
                        bw.Write(0x1 | 0x2 | 0x4 | 0x1000); bw.Write(tex.Height); bw.Write(tex.Width);
                        bw.Write(lin.Length); bw.Write(0); bw.Write(1);
                        for (int i = 0; i < 11; i++) bw.Write(0);
                        bw.Write(32); bw.Write(4); bw.Write((bc1 ? "DXT1" : "DXT5").ToCharArray());
                        bw.Write(0); bw.Write(0); bw.Write(0); bw.Write(0); bw.Write(0);
                        bw.Write(0x1000); bw.Write(0); bw.Write(0); bw.Write(0); bw.Write(0);
                        bw.Write(lin);
                    }
                }
            }
        }

        // ---- models ----------------------------------------------------------------------------------------
        bool firstModel = true;
        for (int mi = 0; mi < res.Models.Count; mi++)
        {
            if (modelIndex >= 0 && mi != modelIndex) continue;
            Model model = res.Models[mi];
            var bones = model.Skeleton.Bones;
            var world = new double[bones.Count][];
            for (int i = 0; i < bones.Count; i++)
            {
                var local = BoneLocal(bones[i]);
                int p = bones[i].ParentIndex;
                world[i] = (p >= 0 && p < i) ? Mul(world[p], local) : local;
            }
            var m2b = model.Skeleton.MatrixToBoneList;

            if (!firstModel) sb.Append(","); firstModel = false;
            sb.Append("{\"name\":\"" + model.Name + "\",\"shapes\":[");
            bool firstShape = true;
            foreach (Shape shape in model.Shapes)
            {
                if (shape.Meshes.Count == 0) continue;
                VertexBuffer vb = model.VertexBuffers[shape.VertexBufferIndex];
                Material mat = model.Materials[shape.MaterialIndex];
                string albedo = "";
                foreach (var t in mat.TextureRefs) if (t.EndsWith("_alb", StringComparison.OrdinalIgnoreCase)) { albedo = t; break; }
                if (albedo == "" && mat.TextureRefs.Count > 0) albedo = mat.TextureRefs[0];

                bool hasP = vb.Attributes.Any(a => a.Name == "_p0"), hasN = vb.Attributes.Any(a => a.Name == "_n0");
                bool hasU = vb.Attributes.Any(a => a.Name == "_u0"), hasI = vb.Attributes.Any(a => a.Name == "_i0");
                if (!hasP) continue;
                var tp = new double[4]; var tn = new double[4]; var tu = new double[4]; var ti = new double[4];
                int skin = shape.VertexSkinCount;

                var pos = new StringBuilder(); var nor = new StringBuilder(); var uv = new StringBuilder();
                int vc = (int)vb.VertexCount;
                for (int v = 0; v < vc; v++)
                {
                    double[] M = null;
                    if (skin == 0 && shape.BoneIndex < world.Length) M = world[shape.BoneIndex];
                    else if (skin == 1 && hasI)
                    {
                        ReadAttr(vb, "_i0", v, ti);
                        int idx = (int)ti[0];
                        int mtx = idx < shape.SkinBoneIndices.Count ? shape.SkinBoneIndices[idx] : idx;
                        int bi = mtx < m2b.Count ? m2b[mtx] : mtx;
                        if (bi >= 0 && bi < world.Length) M = world[bi];
                    }
                    ReadAttr(vb, "_p0", v, tp);
                    double x = tp[0], y = tp[1], z = tp[2];
                    if (M != null)
                    {
                        double ox = M[0] * x + M[1] * y + M[2] * z + M[3];
                        double oy = M[4] * x + M[5] * y + M[6] * z + M[7];
                        double oz = M[8] * x + M[9] * y + M[10] * z + M[11];
                        x = ox; y = oy; z = oz;
                    }
                    if (v > 0) { pos.Append(','); nor.Append(','); uv.Append(','); }
                    pos.Append(F(x) + "," + F(y) + "," + F(z));
                    if (hasN)
                    {
                        ReadAttr(vb, "_n0", v, tn);
                        double nx = tn[0], ny = tn[1], nz = tn[2];
                        if (M != null)
                        {
                            double ax = M[0] * nx + M[1] * ny + M[2] * nz, ay = M[4] * nx + M[5] * ny + M[6] * nz, az = M[8] * nx + M[9] * ny + M[10] * nz;
                            nx = ax; ny = ay; nz = az;
                        }
                        nor.Append(F(nx) + "," + F(ny) + "," + F(nz));
                    }
                    else nor.Append("0,1,0");
                    if (hasU) { ReadAttr(vb, "_u0", v, tu); uv.Append(F(tu[0]) + "," + F(tu[1])); } else uv.Append("0,0");
                }

                var idxs = new StringBuilder(); int n = 0;
                Mesh mesh = shape.Meshes[0];
                foreach (uint ix in mesh.GetIndices()) { if (n++ > 0) idxs.Append(','); idxs.Append(ix + mesh.FirstVertex); }

                if (!firstShape) sb.Append(","); firstShape = false;
                sb.Append("{\"name\":\"" + shape.Name + "\",\"material\":\"" + mat.Name + "\",\"albedo\":\"" + albedo + "\",\"textures\":[" +
                          string.Join(",", mat.TextureRefs.Select(t => "\"" + t + "\"")) + "],\"skin\":" + skin + ",\"bone\":\"" +
                          (shape.BoneIndex < bones.Count ? bones[shape.BoneIndex].Name : "") + "\",\"prim\":\"" + mesh.PrimitiveType +
                          "\",\"vertexCount\":" + vc + ",\"positions\":[" + pos + "],\"normals\":[" + nor + "],\"uvs\":[" + uv + "],\"indices\":[" + idxs + "]}");
            }
            sb.Append("],\"bones\":[");
            for (int i = 0; i < bones.Count; i++)
            {
                if (i > 0) sb.Append(",");
                sb.Append("{\"name\":\"" + bones[i].Name + "\",\"parent\":" + bones[i].ParentIndex + ",\"world\":[" + string.Join(",", world[i].Select(F)) + "]}");
            }
            sb.Append("]}");
        }
        sb.Append("],\"textures\":[" + string.Join(",", texInfo) + "]}");
        File.WriteAllText(Path.Combine(outDir, "model.json"), sb.ToString());
        Console.WriteLine("Wrote " + Path.Combine(outDir, "model.json") + " (" + sb.Length + " chars)");
    }
}
