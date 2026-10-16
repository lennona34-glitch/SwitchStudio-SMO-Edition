using System;
using System.IO;
using VGAudio.Containers.NintendoWare;
using VGAudio.Containers.Wave;

class Program
{
    static void Main(string[] args)
    {
        if (args.Length < 2)
        {
            Console.WriteLine("Usage: ConvertAudio.exe <input> <output>");
            return;
        }

        string inPath = args[0];
        string outPath = args[1];
        bool shouldLoop = true;

        for (int i = 2; i < args.Length; i++)
        {
            if (args[i].Equals("--noloop", StringComparison.OrdinalIgnoreCase))
                shouldLoop = false;
            else if (args[i].Equals("--loop", StringComparison.OrdinalIgnoreCase))
                shouldLoop = true;
        }

        if (inPath.EndsWith(".bfstm", StringComparison.OrdinalIgnoreCase))
        {
            // BFSTM to WAV
            using (var inStream = File.OpenRead(inPath))
            using (var outStream = File.Create(outPath))
            {
                var audio = new BCFstmReader().Read(inStream);
                new WaveWriter().WriteToStream(audio, outStream);
                Console.WriteLine("Converted " + inPath + " -> " + outPath + " (WAV)");
            }
        }
        else if (inPath.EndsWith(".wav", StringComparison.OrdinalIgnoreCase))
        {
            // WAV to BFSTM
            using (var inStream = File.OpenRead(inPath))
            using (var outStream = File.Create(outPath))
            {
                var audio = new WaveReader().Read(inStream);
                audio.SetLoop(shouldLoop);
                var config = new BxstmConfiguration();
                config.Codec = NwCodec.GcAdpcm;
                new BCFstmWriter(NwTarget.Cafe).WriteToStream(audio, outStream, config);
                Console.WriteLine("Converted " + inPath + " -> " + outPath + " (BFSTM, loop=" + shouldLoop + ")");
            }
        }
    }
}
