using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using Syroot.NintenTools.NSW.Bfres;

// PatchVertices.exe <in.bfres> <out.bfres> <patch.txt>
//   patch.txt: first line = shape name prefix; then one line per vertex:  index  x y z  packedNormal
//   packedNormal is the new 32-bit value for the _n0 attribute (10_10_10_2 SNorm), or -1 to leave the normal alone.
// Only the listed vertices are rewritten, in place; file size and layout are unchanged. The vertex buffer location is
// taken from the library's offsets and verified against the file's bytes before anything is written.
class Program
{
    static int Main(string[] args)
    {
        if (args.Length < 3) { Console.WriteLine("Usage: PatchVertices.exe <in.bfres> <out.bfres> <patch.txt>"); return 2; }
        var C = CultureInfo.InvariantCulture;
        byte[] file = File.ReadAllBytes(args[0]);
        string[] lines = File.ReadAllLines(args[2]);
        string shapeName = lines[0].Trim();

        ResFile res = new ResFile(args[0]);
        Model model = null; Shape shape = null;
        foreach (Model m in res.Models)
            foreach (Shape s in m.Shapes)
                if (shape == null && s.Name.StartsWith(shapeName, StringComparison.OrdinalIgnoreCase)) { model = m; shape = s; }
        if (shape == null) { Console.WriteLine("ERROR: shape not found: " + shapeName); return 1; }

        VertexBuffer vb = model.VertexBuffers[shape.VertexBufferIndex];
        VertexAttrib ap = vb.Attributes.First(a => a.Name == "_p0");
        VertexAttrib an = vb.Attributes.FirstOrDefault(a => a.Name == "_n0");

        // The loader does not record where a vertex buffer sits in the file (its offset reads 0), so find it by its full
        // contents and insist on exactly one match.
        Func<VertexAttrib, Tuple<long, int>> locate = (attr) =>
        {
            var buf = vb.Buffers[attr.BufferIndex];
            byte[] d = buf.Data;
            long found = -1; int hits = 0;
            for (int i = 0; i + d.Length <= file.Length; i++)
            {
                if (file[i] != d[0]) continue;
                int j = 1;
                while (j < d.Length && file[i + j] == d[j]) j++;
                if (j == d.Length) { found = i; hits++; }
            }
            if (hits != 1) throw new Exception("vertex buffer for " + attr.Name + " matched " + hits + " places in the file (need exactly 1)");
            return Tuple.Create(found, buf.Stride);
        };
        var pl = locate(ap);
        Tuple<long, int> nl = an != null ? locate(an) : null;
        Console.WriteLine("Verified vertex buffers for " + shape.Name + " (" + vb.VertexCount + " vertices)");

        int count = 0;
        for (int li = 1; li < lines.Length; li++)
        {
            var t = lines[li].Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
            if (t.Length < 5) continue;
            int idx = int.Parse(t[0]);
            if (idx < 0 || idx >= vb.VertexCount) throw new Exception("vertex index out of range: " + idx);
            long p = pl.Item1 + (long)idx * pl.Item2 + ap.Offset;
            for (int k = 0; k < 3; k++)
                Array.Copy(BitConverter.GetBytes(float.Parse(t[1 + k], C)), 0, file, p + 4 * k, 4);
            long packed = long.Parse(t[4], C);
            if (packed >= 0 && nl != null)
            {
                // keep the two spare top bits of the original value, replace the three 10-bit components
                long np = nl.Item1 + (long)idx * nl.Item2 + an.Offset;
                uint orig = BitConverter.ToUInt32(file, (int)np);
                uint merged = (orig & 0xC0000000u) | ((uint)packed & 0x3FFFFFFFu);
                Array.Copy(BitConverter.GetBytes(merged), 0, file, np, 4);
            }
            count++;
        }
        File.WriteAllBytes(args[1], file);
        Console.WriteLine("Patched " + count + " vertices");
        return 0;
    }
}
