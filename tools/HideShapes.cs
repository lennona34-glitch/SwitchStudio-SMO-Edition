using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Syroot.NintenTools.NSW.Bfres;

// HideShapes.exe <in.bfres> <out.bfres> <name-substring> [<name-substring> ...]
// Makes the matching shapes invisible by zeroing their index (triangle) data in place: every triangle becomes
// degenerate and is never drawn. File size and layout are untouched. The location of each shape's index data is
// derived from the library's own offsets and cross-checked against the file contents for EVERY shape first.
class Program
{
    static int Find(byte[] hay, byte[] needle, int from)
    {
        for (int i = from; i <= hay.Length - needle.Length; i++)
        {
            int j = 0;
            while (j < needle.Length && hay[i + j] == needle[j]) j++;
            if (j == needle.Length) return i;
        }
        return -1;
    }

    static int Main(string[] args)
    {
        if (args.Length < 3) { Console.WriteLine("Usage: HideShapes.exe <in.bfres> <out.bfres> <name-substring>..."); return 2; }
        byte[] file = File.ReadAllBytes(args[0]);
        ResFile res = new ResFile(args[0]);
        FieldInfo fData = typeof(Mesh).GetField("Data", BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Public);
        FieldInfo fOff = typeof(Mesh).GetField("DataOffset", BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Public);

        var meshes = new List<Tuple<string, byte[], long>>();
        foreach (Model m in res.Models)
            foreach (Shape s in m.Shapes)
            {
                if (s.Meshes.Count == 0) continue;
                byte[] data = (byte[])fData.GetValue(s.Meshes[0]);
                long off = (long)fOff.GetValue(s.Meshes[0]);
                if (data == null || data.Length == 0) continue;
                meshes.Add(Tuple.Create(s.Name, data, off));
            }

        // Candidate pool start: occurrence of the first shape's data minus its DataOffset; keep the one for which every
        // shape's data is found at pool + DataOffset.
        long pool = long.MinValue;
        int searchFrom = 0, occ;
        while ((occ = Find(file, meshes[0].Item2, searchFrom)) >= 0)
        {
            long cand = occ - meshes[0].Item3;
            bool all = true;
            foreach (var me in meshes)
            {
                long at = cand + me.Item3;
                if (at < 0 || at + me.Item2.Length > file.Length) { all = false; break; }
                for (int i = 0; i < me.Item2.Length; i++) if (file[at + i] != me.Item2[i]) { all = false; break; }
                if (!all) break;
            }
            if (all) { pool = cand; break; }
            searchFrom = occ + 1;
        }
        if (pool == long.MinValue) { Console.WriteLine("ERROR: could not verify index data locations"); return 1; }
        Console.WriteLine("Index data pool verified at 0x" + pool.ToString("X") + " for " + meshes.Count + " shapes");

        int hidden = 0;
        foreach (var me in meshes)
        {
            if (!args.Skip(2).Any(n => me.Item1.IndexOf(n, StringComparison.OrdinalIgnoreCase) >= 0)) continue;
            long at = pool + me.Item3;
            for (int i = 0; i < me.Item2.Length; i++) file[at + i] = 0;
            Console.WriteLine("  hid " + me.Item1 + " (" + me.Item2.Length + " bytes of indices at 0x" + at.ToString("X") + ")");
            hidden++;
        }
        if (hidden == 0) { Console.WriteLine("ERROR: no shape matched"); return 1; }
        File.WriteAllBytes(args[1], file);
        return 0;
    }
}
