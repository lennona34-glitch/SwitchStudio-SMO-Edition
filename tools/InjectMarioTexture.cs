using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using Syroot.NintenTools.NSW.Bntx;

class TrackingStream : MemoryStream
{
    public List<Tuple<long, int>> LargeReads = new List<Tuple<long, int>>();
    public TrackingStream(byte[] buffer) : base(buffer) {}
    public override int Read(byte[] buffer, int offset, int count)
    {
        long pos = Position;
        int read = base.Read(buffer, offset, count);
        if (count >= 1000)
        {
            LargeReads.Add(Tuple.Create(pos, count));
        }
        return read;
    }
}

class Program
{
    [StructLayout(LayoutKind.Sequential)]
    public struct BlockDim
    {
        public ulong width;
        public ulong height;
        public ulong depth;
    }

    [DllImport("tegra_swizzle_x64.dll", EntryPoint = "block_height_mip0")]
    public static extern ulong BlockHeightMip0(ulong height);

    [DllImport("tegra_swizzle_x64.dll", EntryPoint = "swizzled_surface_size")]
    public static extern ulong SwizzledSurfaceSize(
        ulong width, ulong height, ulong depth,
        BlockDim blockDim, ulong blockHeightMip0,
        ulong bytesPerPixel, ulong mipmapCount, ulong arrayCount
    );

    [DllImport("tegra_swizzle_x64.dll", EntryPoint = "swizzle_surface")]
    public static extern unsafe void SwizzleSurface(
        ulong width, ulong height, ulong depth,
        byte* source, ulong sourceLength,
        byte* destination, ulong destinationLength,
        BlockDim blockDim, ulong blockHeightMip0,
        ulong bytesPerPixel, ulong mipmapCount, ulong arrayCount
    );

    static unsafe void Main(string[] args)
    {
        if (args.Length < 3)
        {
            Console.WriteLine("Usage: InjectMarioTexture.exe <bfres_path> <texture_name> <dds_path> [out_bfres_path]");
            return;
        }

        string bfresPath = args[0];
        string targetTexName = args[1];
        string ddsPath = args[2];
        string outBfresPath = args.Length >= 4 ? args[3] : bfresPath;

        Console.WriteLine("Loading original BFRES: " + bfresPath + "...");
        byte[] bfresBytes = File.ReadAllBytes(bfresPath);

        // Find BNTX header offset
        int bntxOffsetInBfres = -1;
        for (int i = 0; i < bfresBytes.Length - 4; i++)
        {
            if (bfresBytes[i] == 'B' && bfresBytes[i + 1] == 'N' && bfresBytes[i + 2] == 'T' && bfresBytes[i + 3] == 'X')
            {
                bntxOffsetInBfres = i;
                break;
            }
        }

        if (bntxOffsetInBfres < 0)
        {
            Console.WriteLine("Error: BNTX header not found in BFRES!");
            return;
        }

        byte[] bntxData = new byte[bfresBytes.Length - bntxOffsetInBfres];
        Array.Copy(bfresBytes, bntxOffsetInBfres, bntxData, 0, bntxData.Length);

        Texture targetTex = null;
        int targetIndex = -1;

        using (TrackingStream ts = new TrackingStream(bntxData))
        {
            BntxFile bntx = new BntxFile(ts);
            for (int i = 0; i < bntx.Textures.Count; i++)
            {
                if (bntx.Textures[i].Name.Equals(targetTexName, StringComparison.OrdinalIgnoreCase))
                {
                    targetTex = bntx.Textures[i];
                    targetIndex = i;
                    break;
                }
            }
        }

        if (targetTex == null)
        {
            Console.WriteLine("Error: Texture " + targetTexName + " not found!");
            return;
        }

        // Known exact offsets inside BNTX for Super Mario Odyssey characters
        int texOffsetInBntx = -1;
        if (targetTexName.Equals("MarioBody_alb", StringComparison.OrdinalIgnoreCase)) texOffsetInBntx = 8192;
        else if (targetTexName.Equals("MarioColorLuigiBody_alb", StringComparison.OrdinalIgnoreCase)) texOffsetInBntx = 8192;
        else if (targetTexName.Equals("MarioCap_alb", StringComparison.OrdinalIgnoreCase)) texOffsetInBntx = 8192;
        else if (targetTexName.Equals("MarioCaptainCap_alb", StringComparison.OrdinalIgnoreCase)) texOffsetInBntx = 8192;
        else if (targetTexName.Equals("MarioColorLuigiCap_alb", StringComparison.OrdinalIgnoreCase)) texOffsetInBntx = 8192;
        else if (targetTexName.Equals("MarioFace_alb", StringComparison.OrdinalIgnoreCase)) texOffsetInBntx = 37888;
        else if (targetTexName.Equals("MarioFaceHighMesh_alb", StringComparison.OrdinalIgnoreCase)) texOffsetInBntx = 57344;
        else if (targetTexName.Equals("MarioEyeHighMesh_alb", StringComparison.OrdinalIgnoreCase)) texOffsetInBntx = 8192;
        else if (targetTexName.Equals("MarioEye_alb", StringComparison.OrdinalIgnoreCase)) texOffsetInBntx = 210944;
        else if (targetTexName.Equals("MarioEyePupil_alb", StringComparison.OrdinalIgnoreCase))
        {
            texOffsetInBntx = (bfresBytes.Length > 500000) ? 718848 : 8192;
        }
        else if (targetTexName.Equals("MarioBodyHighMesh_alb", StringComparison.OrdinalIgnoreCase)) texOffsetInBntx = 4096;
        else if (targetTexName.Equals("MarioHairFace_alb", StringComparison.OrdinalIgnoreCase)) texOffsetInBntx = 130048;
        else
        {
            Console.WriteLine("Warning: Unknown texture name " + targetTexName);
            return;
        }

        int texOffsetInBfres = bntxOffsetInBfres + texOffsetInBntx;
        Console.WriteLine("Target texture: " + targetTex.Name + " (" + targetTex.Width + "x" + targetTex.Height + ") Mips=" + targetTex.MipCount);
        Console.WriteLine("  Offset in BFRES: 0x" + texOffsetInBfres.ToString("X") + " (" + texOffsetInBfres + ")");

        // Read DDS data (skip 128 byte DDS header)
        byte[] ddsFile = File.ReadAllBytes(ddsPath);
        byte[] linearData = new byte[ddsFile.Length - 128];
        Array.Copy(ddsFile, 128, linearData, 0, linearData.Length);
        Console.WriteLine("Read linear DDS payload: " + linearData.Length + " bytes");

        // Prepare Swizzle parameters
        string fmtStr = targetTex.Format.ToString();
        ulong bpp = (fmtStr.Contains("BC1") || fmtStr.Contains("BC4")) ? 8u : 16u;
        BlockDim blk = new BlockDim { width = 4, height = 4, depth = 1 };
        ulong bh0 = BlockHeightMip0(targetTex.Height);
        ulong swizzledSize = SwizzledSurfaceSize(targetTex.Width, targetTex.Height, 1, blk, bh0, bpp, targetTex.MipCount, 1);

        Console.WriteLine("Calculated swizzled size: " + swizzledSize + " bytes (targetTex.ImageSize = " + targetTex.ImageSize + ")");

        byte[] swizzled = new byte[swizzledSize];
        fixed (byte* pSrc = linearData)
        fixed (byte* pDst = swizzled)
        {
            SwizzleSurface(targetTex.Width, targetTex.Height, 1, pSrc, (ulong)linearData.Length, pDst, swizzledSize, blk, bh0, bpp, targetTex.MipCount, 1);
        }

        Console.WriteLine("Swizzled successfully! Length: " + swizzled.Length + " bytes");

        // Copy swizzled bytes in-place into original bfresBytes
        Array.Copy(swizzled, 0, bfresBytes, texOffsetInBfres, swizzled.Length);

        File.WriteAllBytes(outBfresPath, bfresBytes);
        Console.WriteLine("Wrote patched BFRES to " + outBfresPath + " (" + bfresBytes.Length + " bytes)");
    }
}
